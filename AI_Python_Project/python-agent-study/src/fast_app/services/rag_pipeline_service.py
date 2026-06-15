import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext, RetrievalOptions, RetrievedDoc, RagMode, RetrievalFilters
from fast_app.graph.rag_state import RagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse, RagScoreBreakdown, RagSource
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.retrieval_fusion import reciprocal_rank_fusion
from fast_app.services.rag_context_builder import build_rag_context
from fast_app.components.rerankers.base import BaseReranker
from fast_app.domain.rag_stream_models import RagStreamEvent


# `__name__` 是当前模块名。
# 在这个文件中，`__name__` 大概率是：
# ```text
# fast_app.services.rag_pipeline_service
# ```
# 所以日志输出时可以看到：
# ```text
# fast_app.services.rag_pipeline_service
# ```
# 这能帮助你判断日志来自哪个模块。
logger = get_logger(__name__)

DEFAULT_SOURCE_PREVIEW_CHARS = 120

# 并发召回
# 过滤文档
# 合并去重
# 构造上下文
# 生成回答
# 流式生成 token
# 抛出业务异常


# ---------------------------------------------------------------------------
# Deprecated legacy functions
# 下面这些函数是早期过程式 RAG 实现，当前已经封装到 components 目录：
# - `milvus_retrieve` -> `MockVectorRetriever.retrieve`
# - `es_retrieve` -> `MockKeywordRetriever.retrieve`
# - `generate_answer_node` -> `MockLLMClient.generate`
# - `stream_answer_node` -> `MockLLMClient.stream`
# - `run_rag` -> `RagPipeline.run`
# - `run_rag_stream` -> `RagPipeline.stream`
#
# 保留这些函数用于学习 async、召回、上下文构造和流式输出。
# 新代码不要继续依赖本区域的旧入口函数。
# ---------------------------------------------------------------------------
async def milvus_retrieve(query: str) -> list[RetrievedDoc]:
    """Deprecated: 旧版 Milvus 模拟召回，请使用 `MockVectorRetriever.retrieve`。

    参数示例：
        query="什么是混合检索？"
    """
    # 模拟 Milvus 网络 IO
    await asyncio.sleep(1)

    return [
        RetrievedDoc(
            id="doc_milvus_001",
            content=f"Milvus 向量召回结果：{query} 通常需要向量相似度搜索。",
            score=0.91,
            source="milvus",
        ),
        RetrievedDoc(
            id="doc_shared_001",
            content="混合检索会结合语义召回和关键词召回。",
            score=0.86,
            source="milvus",
        ),
    ]


async def es_retrieve(query: str) -> list[RetrievedDoc]:
    """Deprecated: 旧版 ElasticSearch 模拟召回，请使用 `MockKeywordRetriever.retrieve`。

    参数示例：
        query="什么是混合检索？"
    """
    # 模拟 ElasticSearch 网络 IO
    await asyncio.sleep(1)

    return [
        RetrievedDoc(
            id="doc_es_001",
            content=f"ElasticSearch 关键词召回结果：{query} 可以通过 BM25 匹配关键词。",
            score=0.88,
            source="elasticsearch",
        ),
        RetrievedDoc(
            id="doc_shared_001",
            content="混合检索会结合语义召回和关键词召回。",
            score=0.84,
            source="elasticsearch",
        ),
    ]


def filter_docs_by_score(
    docs: list[RetrievedDoc],
    min_score: float,
) -> list[RetrievedDoc]:
    """过滤低于最小相关性分数的文档。"""
    return [
        doc for doc in docs
        if doc.score >= min_score
    ]


# 不同检索mode对分数采用不同的处理，keyword hybrid 模式暂时不使用min_score过滤 文档8-2
def filter_docs_by_mode(
    docs: list[RetrievedDoc],
    mode: RagMode,
    min_score: float,
) -> list[RetrievedDoc]:
    if min_score <= 0:
        return docs

    if mode == "vector":
        return filter_docs_by_score(
            docs=docs,
            min_score=min_score,
        )

    if mode == "keyword":
        return docs

    if mode == "hybrid":
        return docs

    return docs


def merge_docs_by_id(
    doc_lists: list[list[RetrievedDoc]],
    top_k: int,
) -> list[RetrievedDoc]:
    """按文档 id 合并多路召回结果，并保留最高分版本。"""
    doc_map: dict[str, RetrievedDoc] = {}

    for docs in doc_lists:
        for doc in docs:
            existing = doc_map.get(doc.id)

            # 同一篇文档可能来自多个召回源，这里保留分数最高的那条。
            if existing is None or doc.score > existing.score:
                doc_map[doc.id] = doc

    # 合并后按相关性从高到低排序，再截取 top_k。
    # 这里已经完成 id 去重，可以直接对 values 中的 RetrievedDoc 排序。
    merged_docs = sorted(
        doc_map.values(),
        key=lambda doc: doc.score,
        reverse=True,
    )

    return merged_docs[:top_k]

# 不同检索来源的分数拆分
def score_breakdown_to_source_scores(doc: RetrievedDoc) -> RagScoreBreakdown:
    return RagScoreBreakdown(
        vector_score=doc.scores.vector_score,
        keyword_score=doc.scores.keyword_score,
        rrf_score=doc.scores.rrf_score,
        rerank_score=doc.scores.rerank_score,
    )

# 兼容旧 mock、旧 demo、旧构造代码，如果 retrieval_sources 为空，就回退到 [doc.source] 主来源
def normalize_retrieval_sources(doc: RetrievedDoc) -> list[str]:
    if doc.retrieval_sources:
        # set 去重 sorted 用来保证 response 顺序稳定，方便阅读
        return sorted(set(doc.retrieval_sources))

    return [doc.source]

# 从 metadata 中提取 section_path section_path 理论上应该是 list[str]，但外部数据不一定永远干净。
# 单独 helper 可以做防御性转换，避免 API response 因 metadata 形状异常报错。
def extract_section_path(doc: RetrievedDoc) -> list[str]:
    section_path = doc.metadata.get("section_path")

    if not isinstance(section_path, list):
        return []

    return [str(item) for item in section_path]

# 把 API request 转成内部检索参数
def build_retrieval_options(req: RagChatRequest) -> RetrievalOptions:
    candidate_k = max(req.candidate_k or req.top_k, req.top_k)

    return RetrievalOptions(
        top_k=req.top_k,
        candidate_k=candidate_k,
        filters=RetrievalFilters(
            source_path=req.filters.source_path,
            section_path=req.filters.section_path,
        ),
    )


async def retrieve_node(req: RagChatRequest) -> list[RetrievedDoc]:
    """根据检索模式执行召回、过滤、合并和异常处理。"""
    
    # 构建查询条件
    options = build_retrieval_options(req)

    if req.mode == "vector":
        logger.info("开始向量检索: query=%s", req.query)

        docs = await milvus_retrieve(req.query)
        filtered_docs = filter_docs_by_score(docs, req.min_score)

        # 不用 f-string的原因：当日志等级被过滤掉时，参数形式可以避免不必要的字符串拼接。【logging 系统会在真正需要输出时再格式化。】
        logger.info(
            "向量检索完成: raw_count=%s, filtered_count=%s",
            len(docs),
            len(filtered_docs),
        )

        if len(filtered_docs) == 0:
            logger.warning("向量检索无结果: min_score=%s", req.min_score)
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的向量检索结果"
            )

        return filtered_docs[: req.top_k]

    if req.mode == "keyword":
        logger.info("开始关键词检索: query=%s", req.query)

        docs = await es_retrieve(req.query)
        filtered_docs = filter_docs_by_mode(docs, req.mode, req.min_score)

        logger.info(
            "关键词检索完成: raw_count=%s, filtered_count=%s",
            len(docs),
            len(filtered_docs),
        )

        if len(filtered_docs) == 0:
            logger.warning("关键词检索无结果: min_score=%s", req.min_score)
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的关键词检索结果"
            )

        return filtered_docs[: req.top_k]

    #上面两个单独的检索模式被跳过，混合检索开始
    logger.info("开始混合检索: query=%s", req.query)

    results = await asyncio.gather(
        milvus_retrieve(req.query),
        es_retrieve(req.query),
        return_exceptions=True,
    )

    successful_doc_lists: list[list[RetrievedDoc]] = []

    for result in results:
        if isinstance(result, Exception):
            logger.warning("召回源失败: %s", result)
            continue

        # 单个召回源成功时也要先做分数过滤，再进入合并流程。
        filtered_docs = filter_docs_by_mode(
            docs=result,
            mode=req.mode,
            min_score=req.min_score,
        )
        successful_doc_lists.append(filtered_docs)

    if len(successful_doc_lists) == 0:
        logger.error("混合检索失败: 所有召回源都失败")
        raise ExternalServiceError("所有召回源都失败")

    merged_docs = merge_docs_by_id(
        doc_lists=successful_doc_lists,
        top_k=req.top_k,
    )

    logger.info(
        "混合检索合并完成: source_count=%s, merged_count=%s",
        len(successful_doc_lists),
        len(merged_docs),
    )

    if len(merged_docs) == 0:
        logger.warning("混合检索无结果: min_score=%s", req.min_score)
        raise NoSearchResultError(
            f"没有找到满足 min_score={req.min_score} 的混合检索结果"
        )

    return merged_docs


def build_context_node(docs: list[RetrievedDoc]) -> RagContext:
    """把召回文档拼接成 LLM 可消费的上下文。"""
    if len(docs) == 0:
        raise NoSearchResultError("没有可用于构造上下文的文档")

    context_parts: list[str] = []

    for index, doc in enumerate(docs):
        # 给每段上下文带上来源和分数，便于回答时引用与排查。
        context_parts.append(
            f"[{index}] source={doc.source}, score={doc.score}\n{doc.content}"
        )

    return RagContext(
        text="\n\n".join(context_parts),
        docs=docs,
    )


async def generate_answer_node(
    query: str,
    context: RagContext,
) -> str:
    """Deprecated: 旧版 LLM 回答生成，请使用 `MockLLMClient.generate`。

    参数示例：
        query="什么是混合检索？"
        context=RagContext(text="...", docs=[...])
    """
    # 模拟 LLM 调用
    await asyncio.sleep(1)

    return (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"核心结论：混合检索会同时利用向量检索和关键词检索，"
        f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
        f"参考上下文：\n{context.text}"
    )


async def run_rag(req: RagChatRequest) -> RagChatResponse:
    """Deprecated: 旧版非流式 RAG 入口，请使用 `RagPipeline.run`。

    参数示例：
        req=RagChatRequest(
            query="什么是混合检索？",
            mode="hybrid",
            top_k=5,
            min_score=0.0,
        )
    """
    # 这里用 RagState 模拟后续接入 LangGraph 时的图状态。
    state: RagState = {
        "query": req.query,
        "docs": [],
        "context": None,
        "answer": None,
    }

    docs = await retrieve_node(req)
    state["docs"] = docs

    context = build_rag_context(req.query, docs)
    state["context"] = context

    answer = await generate_answer_node(
        query=state["query"],
        context=context,
    )
    state["answer"] = answer

    return RagChatResponse(
        query=state["query"],
        answer=state["answer"] or "",
        sources=[doc.id for doc in state["docs"]], 
    )


async def stream_answer_node(
    query: str,
    context: RagContext,
) -> AsyncGenerator[str, None]:
    """Deprecated: 旧版 LLM 流式输出，请使用 `MockLLMClient.stream`。

    参数示例：
        query="什么是混合检索？"
        context=RagContext(text="...", docs=[...])
    """
    answer = (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"混合检索的核心是：同时使用向量检索和关键词检索，"
        f"然后合并、去重、排序，得到更稳定的结果。\n\n"
        f"上下文摘要：{context.text}"
    )

    for char in answer:
        # 通过短暂 sleep 模拟真实模型逐 token 返回的延迟。
        await asyncio.sleep(0.02)
        yield char


async def run_rag_stream(req: RagChatRequest) -> AsyncGenerator[str, None]:
    """Deprecated: 旧版流式 RAG 入口，请使用 `RagPipeline.stream`。

    参数示例：
        req=RagChatRequest(
            query="什么是混合检索？",
            mode="hybrid",
            top_k=5,
            min_score=0.0,
        )
    """
    logger.info(
        "开始执行 RAG Stream Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
        req.query,
        req.mode,
        req.top_k,
        req.min_score,
    )

    docs = await retrieve_node(req)

    logger.info("RAG Stream 召回完成: docs_count=%s", len(docs))

    context = build_rag_context(req.query, docs)

    logger.info("RAG Stream 上下文构造完成: context_docs_count=%s", len(context.docs))

    token_count = 0

    async for token in stream_answer_node(req.query, context):
        token_count += 1
        yield token

    # 后续如果真的需要排查 token 级别问题（每个 token 都打一条日志），可以临时用 `DEBUG` 日志。
    logger.info("RAG Stream 输出完成: token_count=%s", token_count)

# 文档内容长度截断
def build_content_preview(
    content: str,
    max_chars: int = DEFAULT_SOURCE_PREVIEW_CHARS,
) -> str:
    normalized = " ".join(content.split())

    if len(normalized) <= max_chars:
        return normalized

    return normalized[:max_chars].rstrip() + "..."

# 文档内容重新封装 内部 RetrievedDoc 转 API RagSource 的唯一出口
def docs_to_sources(docs: list[RetrievedDoc]) -> list[RagSource]:
    return [
        RagSource(
            id=doc.id,
            source=doc.source,
            retrieval_sources=normalize_retrieval_sources(doc),
            title=doc.title,
            section_path=extract_section_path(doc),
            metadata=doc.metadata,
            score=doc.score,
            scores=score_breakdown_to_source_scores(doc),
            content_preview=build_content_preview(doc.content),
        )
        for doc in docs
    ]


class RagPipeline:
    """RAG 业务编排类。

    这个类负责把一次 RAG 请求拆成几个稳定步骤：
    1. 根据请求模式选择向量检索、关键词检索或混合检索。
    2. 按 `min_score` 过滤低相关性文档。
    3. 在混合检索模式下合并多路召回结果并按文档 id 去重。
    4. 把召回文档构造成 LLM 上下文。
    5. 调用 LLM client 生成普通回答或流式 token。
    """

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker,
    ):
        """初始化 RAG Pipeline 依赖。
        """
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client
        self.reranker = reranker

    # 重排序模型报错时降级处理 rerank 是增强能力 增强能力失败时，不应该直接让普通问答接口失败
    async def rerank_with_fallback(
        self,
        query: str,
        docs: list[RetrievedDoc],
    ) -> list[RetrievedDoc]:
        if not docs:
            return []

        try:
            return await self.reranker.rerank(
                query=query,
                docs=docs,
                top_k=min(self.settings.rerank_top_k, len(docs)),
            )
        except ExternalServiceError as exc:
            logger.warning("Rerank 失败，使用召回结果降级继续: %s", exc)
            return docs[: self.settings.rerank_top_k]

    #非流式普通接口
    async def run(self, req: RagChatRequest) -> RagChatResponse:
        """执行一次完整的非流式 RAG 请求。"""

        start_time = perf_counter()
        logger.info(
            "rag_pipeline %s",
            format_log_fields(
                event="rag.pipeline.start",
                pipeline_provider="classic",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
            ),
        )

        try:
            state: RagState = {
                "query": req.query,
                "docs": [],
                "context": None,
                "answer": None,
            }
            
            docs = await self.retrieve(req)
            docs = await self.rerank_with_fallback(req.query, docs)

            state["docs"] = docs

            logger.info("RAG 召回完成: docs_count=%s", len(docs))

            context = build_rag_context(req.query, docs)
            state["context"] = context

            logger.info("RAG 上下文构造完成: context_docs_count=%s", len(context.docs))

            answer = await self.llm_client.generate(
                query=state["query"],
                context=context,
            )
            state["answer"] = answer

            logger.info("RAG 回答生成完成: answer_length=%s", len(answer))
        except Exception:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "rag_pipeline %s",
                format_log_fields(
                    event="rag.pipeline.failed",
                    pipeline_provider="classic",
                    query=req.query,
                    mode=req.mode,
                    top_k=req.top_k,
                    candidate_k=req.candidate_k,
                    min_score=req.min_score,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise

        latency_ms = (perf_counter() - start_time) * 1000
        logger.info(
            "rag_pipeline %s",
            format_log_fields(
                event="rag.pipeline.finish",
                pipeline_provider="classic",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                candidate_k=req.candidate_k,
                min_score=req.min_score,
                latency_ms=round(latency_ms, 2),
                source_count=len(docs),
                answer_length=len(answer),
            ),
        )

        return RagChatResponse(
            query=state["query"],
            answer=state["answer"] or "",
            sources=docs_to_sources(docs),
        )

    # 流式接口，只以异步生成器形式流式返回 token，未实现stream event
    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        """执行完整 RAG 请求，并以异步生成器形式流式返回 token。"""

        logger.info(
            "开始执行 RAG Stream Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )

        docs = await self.retrieve(req)

        docs = await self.rerank_with_fallback(req.query, docs)

        logger.info("RAG Stream 召回完成: docs_count=%s", len(docs))

        context = build_rag_context(req.query, docs)

        logger.info("RAG Stream 上下文构造完成: context_docs_count=%s", len(context.docs))

        token_count = 0

        async for token in self.llm_client.stream(req.query, context):
            token_count += 1
            yield token

        logger.info("RAG Stream 输出完成: token_count=%s", token_count)

    # 检索文档
    async def retrieve(self, req: RagChatRequest) -> list[RetrievedDoc]:
        """根据请求模式召回文档并完成过滤、合并、去重。

        功能：
            - `mode="vector"`：只调用 `vector_retriever`。
            - `mode="keyword"`：只调用 `keyword_retriever`。
            - `mode="hybrid"`：并发调用向量检索器和关键词检索器，
              再按文档 id 去重，并按分数从高到低排序。

        可能抛出的异常：
            NoSearchResultError:
                召回源有返回，但过滤后为空。

            ExternalServiceError:
                混合检索时所有召回源都抛出异常。
        """
        options = build_retrieval_options(req)

        if req.mode == "vector":
            logger.info("开始向量检索: query=%s", req.query)

            docs = await self.vector_retriever.retrieve(req.query, options)
            filtered_docs = filter_docs_by_score(docs, req.min_score)

            logger.info(
                "向量检索完成: raw_count=%s, filtered_count=%s",
                len(docs),
                len(filtered_docs),
            )

            if len(filtered_docs) == 0:
                logger.warning("向量检索无结果: min_score=%s", req.min_score)
                raise NoSearchResultError(
                    f"没有找到满足 min_score={req.min_score} 的向量检索结果"
                )

            return filtered_docs[: req.top_k]

        if req.mode == "keyword":
            logger.info("开始关键词检索: query=%s", req.query)

            docs = await self.keyword_retriever.retrieve(req.query, options)
            filtered_docs = filter_docs_by_mode(docs, req.mode, req.min_score)

            logger.info(
                "关键词检索完成: raw_count=%s, filtered_count=%s",
                len(docs),
                len(filtered_docs),
            )

            if len(filtered_docs) == 0:
                logger.warning("关键词检索无结果: min_score=%s", req.min_score)
                raise NoSearchResultError(
                    f"没有找到满足 min_score={req.min_score} 的关键词检索结果"
                )

            return filtered_docs[: req.top_k]

        # 开始混合检索模式
        logger.info("开始混合检索: query=%s", req.query)

        results = await asyncio.gather(
            self.vector_retriever.retrieve(req.query, options),
            self.keyword_retriever.retrieve(req.query, options),
            return_exceptions=True,
        )

        successful_doc_lists: list[list[RetrievedDoc]] = []

        for result in results:
            if isinstance(result, Exception):
                logger.warning("召回源失败: %s", result)
                continue

            filtered_docs = filter_docs_by_mode(
                docs=result,
                mode=req.mode,
                min_score=req.min_score,
            )
            successful_doc_lists.append(filtered_docs)

        if len(successful_doc_lists) == 0:
            logger.error("混合检索失败: 所有召回源都失败")
            raise ExternalServiceError("所有召回源都失败")

        # 旧版本，直接通过id去重合并
        # merged_docs = merge_docs_by_id(
        #     doc_lists=successful_doc_lists,
        #     top_k=req.top_k,
        # )

        # 新版本，使用RRF方案
        merged_docs = reciprocal_rank_fusion(
            doc_lists=successful_doc_lists,
            top_k=req.top_k,
        )

        logger.info(
            "混合检索合并完成: source_count=%s, merged_count=%s",
            len(successful_doc_lists),
            len(merged_docs),
        )

        if len(merged_docs) == 0:
            logger.warning("混合检索无结果: min_score=%s", req.min_score)
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的混合检索结果"
            )

        return merged_docs

    # 流式事件接口
    async def stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        logger.info(
            "开始执行 RAG Stream Events Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )

        docs = await self.retrieve(req)
        docs = await self.rerank_with_fallback(req.query, docs)

        yield RagStreamEvent(
            event="sources",
            data={
                "sources": docs_to_sources(docs),
            },
        )

        context = build_rag_context(req.query, docs)

        token_count = 0

        async for token in self.llm_client.stream(req.query, context):
            token_count += 1
            yield RagStreamEvent(
                event="token",
                data={
                    "token": token,
                },
            )

        logger.info(
            "RAG Stream Events 输出完成: token_count=%s",
            token_count,
        )
