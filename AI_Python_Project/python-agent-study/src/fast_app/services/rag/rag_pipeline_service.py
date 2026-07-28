import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever

from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    rag_langsmith_pipeline_trace,
    rag_langsmith_request_step_trace,
)
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext, RetrievalOptions, RetrievedDoc, RagMode, RetrievalFilters
from fast_app.graph.rag.rag_state import RagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse, RagScoreBreakdown, RagSource
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.knowledge.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
    merge_permission_scope_into_filter_dict,
)
from fast_app.services.rag.retrieval_fusion import reciprocal_rank_fusion
from fast_app.services.rag.rag_context_builder import build_rag_context
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.rag.rag_context_assembler import build_context_observation
from fast_app.components.rerankers.base import BaseReranker
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.services.rag.guarded_streaming import (
    GuardedStreamState,
    guarded_answer_delta_events,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService


# `__name__` 是当前模块名。
# 在这个文件中，`__name__` 大概率是：
# ```text
# fast_app.services.rag.rag_pipeline_service
# ```
# 所以日志输出时可以看到：
# ```text
# fast_app.services.rag.rag_pipeline_service
# ```
# 这能帮助你判断日志来自哪个模块。
logger = get_logger(__name__)

DEFAULT_SOURCE_PREVIEW_CHARS = 120

# 日志里只记录前几个 doc.id。避免把完整 content 写进日志。
def build_top_doc_ids(docs: list[RetrievedDoc], limit: int = 5) -> list[str]:
    return [doc.id for doc in docs[:limit]]


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
    filters = merge_permission_scope_into_filter_dict(
        filters=req.filters.model_dump(),
        permission_scope=req._retrieval_permission_scope,
        knowledge_version=req._knowledge_version,
    )

    return RetrievalOptions(
        top_k=req.top_k,
        candidate_k=candidate_k,
        filters=build_retrieval_filters_from_mapping(filters),
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
        context=RagContext(query="...", docs=[...], context_text="...")
    """
    # 模拟 LLM 调用
    await asyncio.sleep(1)

    return (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"核心结论：混合检索会同时利用向量检索和关键词检索，"
        f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
        f"参考上下文：\n{context.context_text}"
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
        context=RagContext(query="...", docs=[...], context_text="...")
    """
    answer = (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"混合检索的核心是：同时使用向量检索和关键词检索，"
        f"然后合并、去重、排序，得到更稳定的结果。\n\n"
        f"上下文摘要：{context.context_text}"
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
            id=str(doc.metadata.get("logical_record_id") or doc.id),
            doc_id=(
                str(doc.metadata["doc_id"])
                if doc.metadata.get("doc_id")
                else None
            ),
            logical_chunk_id=(
                str(doc.metadata["logical_record_id"])
                if doc.metadata.get("logical_record_id")
                else None
            ),
            logical_parent_id=(
                str(doc.metadata["logical_parent_id"])
                if doc.metadata.get("logical_parent_id")
                else None
            ),
            source_revision=(
                str(doc.metadata["source_revision"])
                if doc.metadata.get("source_revision")
                else None
            ),
            parent_id=(
                str(
                    doc.metadata.get("logical_parent_id")
                    or doc.metadata.get("parent_id")
                )
                if (
                    doc.metadata.get("logical_parent_id")
                    or doc.metadata.get("parent_id")
                )
                else None
            ),
            matched_child_ids=[
                str(child_id)
                for child_id in doc.metadata.get(
                    "matched_logical_child_ids",
                    doc.metadata.get("matched_child_ids", []),
                )
            ],
            chunk_level=(
                doc.metadata.get("chunk_level")
                if doc.metadata.get("chunk_level") in {"parent", "child"}
                else None
            ),
            source=doc.source,
            retrieval_sources=normalize_retrieval_sources(doc),
            title=doc.title,
            section_path=extract_section_path(doc),
            metadata=_public_source_metadata(doc.metadata),
            score=doc.score,
            scores=score_breakdown_to_source_scores(doc),
            content_preview=build_content_preview(doc.content),
        )
        for doc in docs
    ]


def _public_source_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """移除版本化物理主键，避免 React 把内部存储 ID 当成稳定身份。"""

    internal_fields = {
        "physical_record_id",
        "physical_parent_id",
        "parent_id",
        "chunk_id",
        "matched_child_ids",
    }
    return {
        key: value
        for key, value in metadata.items()
        if key not in internal_fields
    }


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
        prompt_guard: PromptGuardService | None = None,
        parent_expander: MarkdownParentContextExpander | None = None,
    ):
        """初始化 RAG Pipeline 依赖。
        """
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client
        self.reranker = reranker
        self.prompt_guard = prompt_guard
        self.parent_expander = parent_expander

    async def _ensure_query_allowed(self, query: str, *, source: str) -> None:
        if self.prompt_guard is not None:
            await self.prompt_guard.ensure_user_input_allowed(query, source=source)

    async def _ensure_output_allowed(self, answer: str, *, source: str) -> str:
        if self.prompt_guard is None:
            return answer

        return await self.prompt_guard.ensure_output_allowed(answer, source=source)

    async def _audit_stream_output(self, answer: str, *, source: str) -> None:
        if self.prompt_guard is not None:
            await self.prompt_guard.audit_stream_output(answer, source=source)

    async def _assemble_context(
        self,
        req: RagChatRequest,
        docs: list[RetrievedDoc],
        *,
        source: str,
        expand_parents: bool = True,
    ) -> RagContext:
        filters = merge_permission_scope_into_filter_dict(
            filters=req.filters.model_dump(),
            permission_scope=req._retrieval_permission_scope,
            knowledge_version=req._knowledge_version,
        )
        return await assemble_rag_context(
            settings=self.settings,
            query=req.query,
            docs=docs,
            filters=filters,
            source=source,
            parent_expander=self.parent_expander if expand_parents else None,
            prompt_guard=self.prompt_guard,
        )

    def _langsmith_trace(self, req: RagChatRequest, operation: str):
        return rag_langsmith_pipeline_trace(
            self.settings,
            req,
            "classic",
            operation,
        )

    def _langsmith_step_trace(
        self,
        req: RagChatRequest,
        operation: str,
        step_name: str,
        step_index: int,
        run_type: str,
        inputs: dict[str, object],
    ):
        return rag_langsmith_request_step_trace(
            self.settings,
            req,
            "classic",
            operation,
            step_name,
            step_index,
            run_type,
            inputs,
        )

    # 重排序模型报错时降级处理 rerank 是增强能力 增强能力失败时，不应该直接让普通问答接口失败
    async def rerank_with_fallback(
        self,
        query: str,
        docs: list[RetrievedDoc],
    ) -> list[RetrievedDoc]:
        if not docs:
            return []

        start_time = perf_counter()
        rerank_top_k = min(self.settings.rerank_top_k, len(docs))

        logger.info(
            "rag_rerank %s",
            format_log_fields(
                event="rag.rerank.start",
                pipeline_provider="classic",
                candidate_count=len(docs),
                top_k=rerank_top_k,
                top_doc_ids=build_top_doc_ids(docs),
            ),
        )

        try:
            reranked_docs = await self.reranker.rerank(
                query=query,
                docs=docs,
                top_k=rerank_top_k,
            )
            latency_ms = (perf_counter() - start_time) * 1000
            logger.info(
                "rag_rerank %s",
                format_log_fields(
                    event="rag.rerank.finish",
                    pipeline_provider="classic",
                    candidate_count=len(docs),
                    result_count=len(reranked_docs),
                    top_k=rerank_top_k,
                    latency_ms=round(latency_ms, 2),
                    fallback=False,
                    top_doc_ids=build_top_doc_ids(reranked_docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag.rerank.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rerank_threshold_ms,
                slow_component="rerank",
                pipeline_provider="classic",
                candidate_count=len(docs),
                result_count=len(reranked_docs),
                top_k=rerank_top_k,
                fallback=False,
            )
            return reranked_docs
        except ExternalServiceError as exc:
            fallback_docs = docs[: self.settings.rerank_top_k]
            latency_ms = (perf_counter() - start_time) * 1000
            logger.warning(
                "rag_rerank %s",
                format_log_fields(
                    event="rag.rerank.fallback",
                    pipeline_provider="classic",
                    candidate_count=len(docs),
                    result_count=len(fallback_docs),
                    top_k=rerank_top_k,
                    latency_ms=round(latency_ms, 2),
                    fallback=True,
                    error_type=type(exc).__name__,
                    top_doc_ids=build_top_doc_ids(fallback_docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag.rerank.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rerank_threshold_ms,
                slow_component="rerank",
                pipeline_provider="classic",
                candidate_count=len(docs),
                result_count=len(fallback_docs),
                top_k=rerank_top_k,
                fallback=True,
                error_type=type(exc).__name__,
            )
            return fallback_docs

    #非流式普通接口
    async def run(self, req: RagChatRequest) -> RagChatResponse:
        with self._langsmith_trace(req, "run"):
            return await self._run(req)

    async def _run(self, req: RagChatRequest) -> RagChatResponse:
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
            await self._ensure_query_allowed(req.query, source="classic.run.input")
            state: RagState = {
                "query": req.query,
                "docs": [],
                "context": None,
                "answer": None,
            }

            with self._langsmith_step_trace(
                req=req,
                operation="run",
                step_name="retrieve",
                step_index=1,
                run_type="retriever",
                inputs={
                    "query": req.query,
                    "mode": req.mode,
                    "top_k": req.top_k,
                    "candidate_k": req.candidate_k,
                    "min_score": req.min_score,
                    "filters": req.filters.model_dump(),
                },
            ) as trace_run:
                docs = await self.retrieve(req)
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "doc_count": len(docs),
                            "top_doc_ids": build_top_doc_ids(docs),
                        }
                    )

            with self._langsmith_step_trace(
                req=req,
                operation="run",
                step_name="rerank",
                step_index=2,
                run_type="chain",
                inputs={
                    "query": req.query,
                    "input_doc_count": len(docs),
                    "top_doc_ids": build_top_doc_ids(docs),
                },
            ) as trace_run:
                docs = await self.rerank_with_fallback(req.query, docs)
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": len(docs),
                            "top_doc_ids": build_top_doc_ids(docs),
                        }
                    )

            logger.info("RAG 召回完成: docs_count=%s", len(docs))

            with self._langsmith_step_trace(
                req=req,
                operation="run",
                step_name="build_context",
                step_index=3,
                run_type="chain",
                inputs={
                    "query": req.query,
                    "doc_count": len(docs),
                    "top_doc_ids": build_top_doc_ids(docs),
                },
            ) as trace_run:
                context = await self._assemble_context(
                    req,
                    docs,
                    source="classic.run.documents",
                )
                docs = context.docs
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "context_doc_count": len(context.docs),
                            "context_length": len(context.context_text),
                            **build_context_observation(context),
                        }
                    )
            state["context"] = context
            state["docs"] = docs

            logger.info("RAG 上下文构造完成: context_docs_count=%s", len(context.docs))

            with self._langsmith_step_trace(
                req=req,
                operation="run",
                step_name="generate",
                step_index=4,
                run_type="chain",
                inputs={
                    "query": state["query"],
                    "context_doc_count": len(context.docs),
                    "context_length": len(context.context_text),
                },
            ) as trace_run:
                answer = await self.llm_client.generate(
                    query=state["query"],
                    context=context,
                )
                answer = await self._ensure_output_allowed(
                    answer,
                    source="classic.run.output",
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "answer_length": len(answer),
                            "source_count": len(context.docs),
                        }
                    )
            state["answer"] = answer

            logger.info("RAG 回答生成完成: answer_length=%s", len(answer))
        except Exception as exc:
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
            log_slow_operation(
                logger=logger,
                event="rag.pipeline.slow",
                latency_ms=latency_ms,
                threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
                slow_component="pipeline",
                pipeline_provider="classic",
                status="failed",
                query=req.query,
                mode=req.mode,
                top_k=req.top_k,
                error_type=type(exc).__name__,
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
        log_slow_operation(
            logger=logger,
            event="rag.pipeline.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_rag_pipeline_threshold_ms,
            slow_component="pipeline",
            pipeline_provider="classic",
            status="success",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            source_count=len(docs),
            answer_length=len(answer),
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
        with self._langsmith_trace(req, "stream"):
            async for token in self._stream(req):
                yield token

    async def _stream(
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
        await self._ensure_query_allowed(req.query, source="classic.stream.input")

        with self._langsmith_step_trace(
            req=req,
            operation="stream",
            step_name="retrieve",
            step_index=1,
            run_type="retriever",
            inputs={
                "query": req.query,
                "mode": req.mode,
                "top_k": req.top_k,
                "candidate_k": req.candidate_k,
                "min_score": req.min_score,
                "filters": req.filters.model_dump(),
            },
        ) as trace_run:
            docs = await self.retrieve(req)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "doc_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )

        with self._langsmith_step_trace(
            req=req,
            operation="stream",
            step_name="rerank",
            step_index=2,
            run_type="chain",
            inputs={
                "query": req.query,
                "input_doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
        ) as trace_run:
            docs = await self.rerank_with_fallback(req.query, docs)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "output_doc_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )

        logger.info("RAG Stream 召回完成: docs_count=%s", len(docs))

        with self._langsmith_step_trace(
            req=req,
            operation="stream",
            step_name="build_context",
            step_index=3,
            run_type="chain",
            inputs={
                "query": req.query,
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
        ) as trace_run:
            context = await self._assemble_context(
                req,
                docs,
                source="classic.stream.documents",
                expand_parents=False,
            )
            docs = context.docs
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "context_doc_count": len(context.docs),
                        "context_length": len(context.context_text),
                        **build_context_observation(context),
                    }
                )

        logger.info("RAG Stream 上下文构造完成: context_docs_count=%s", len(context.docs))

        token_count = 0

        with self._langsmith_step_trace(
            req=req,
            operation="stream",
            step_name="stream_generate",
            step_index=4,
            run_type="chain",
            inputs={
                "query": req.query,
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            answer_parts: list[str] = []
            async for token in self.llm_client.stream(req.query, context):
                token_count += 1
                answer_parts.append(token)
                yield token

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "token_count": token_count,
                        "source_count": len(context.docs),
                    }
                )

        await self._audit_stream_output(
            "".join(answer_parts),
            source="classic.stream.output",
        )
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
            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.vector.start",
                    pipeline_provider="classic",
                    retrieval_mode=req.mode,
                    retriever="vector",
                    query=req.query,
                    top_k=req.top_k,
                    candidate_k=options.candidate_k,
                    min_score=req.min_score,
                ),
            )

            start_time = perf_counter()
            try:
                docs = await self.vector_retriever.retrieve(req.query, options)
                filtered_docs = filter_docs_by_score(docs, req.min_score)
                returned_docs = filtered_docs[: req.top_k]
                latency_ms = (perf_counter() - start_time) * 1000

                logger.info(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.vector.finish",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever="vector",
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        raw_count=len(docs),
                        filtered_count=len(filtered_docs),
                        returned_count=len(returned_docs),
                        latency_ms=round(latency_ms, 2),
                        top_doc_ids=build_top_doc_ids(returned_docs),
                    ),
                )
                log_slow_operation(
                    logger=logger,
                    event="rag.retrieval.slow",
                    latency_ms=latency_ms,
                    threshold_ms=self.settings.slow_retrieval_threshold_ms,
                    slow_component="retrieval",
                    pipeline_provider="classic",
                    retrieval_mode=req.mode,
                    retriever="vector",
                    top_k=req.top_k,
                    candidate_k=options.candidate_k,
                    returned_count=len(returned_docs),
                )

                if len(returned_docs) == 0:
                    raise NoSearchResultError(
                        f"没有找到满足 min_score={req.min_score} 的向量检索结果"
                    )

                return returned_docs
            except Exception:
                latency_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.vector.failed",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever="vector",
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        latency_ms=round(latency_ms, 2),
                    ),
                )
                raise

        if req.mode == "keyword":
            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.keyword.start",
                    pipeline_provider="classic",
                    retrieval_mode=req.mode,
                    retriever="keyword",
                    query=req.query,
                    top_k=req.top_k,
                    candidate_k=options.candidate_k,
                    min_score=req.min_score,
                ),
            )

            start_time = perf_counter()
            try:
                docs = await self.keyword_retriever.retrieve(req.query, options)
                filtered_docs = filter_docs_by_mode(docs, req.mode, req.min_score)
                returned_docs = filtered_docs[: req.top_k]
                latency_ms = (perf_counter() - start_time) * 1000

                logger.info(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.keyword.finish",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever="keyword",
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        raw_count=len(docs),
                        filtered_count=len(filtered_docs),
                        returned_count=len(returned_docs),
                        latency_ms=round(latency_ms, 2),
                        top_doc_ids=build_top_doc_ids(returned_docs),
                    ),
                )
                log_slow_operation(
                    logger=logger,
                    event="rag.retrieval.slow",
                    latency_ms=latency_ms,
                    threshold_ms=self.settings.slow_retrieval_threshold_ms,
                    slow_component="retrieval",
                    pipeline_provider="classic",
                    retrieval_mode=req.mode,
                    retriever="keyword",
                    top_k=req.top_k,
                    candidate_k=options.candidate_k,
                    returned_count=len(returned_docs),
                )

                if len(returned_docs) == 0:
                    raise NoSearchResultError(
                        f"没有找到满足 min_score={req.min_score} 的关键词检索结果"
                    )

                return returned_docs
            except Exception:
                latency_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.keyword.failed",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever="keyword",
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        latency_ms=round(latency_ms, 2),
                    ),
                )
                raise

        logger.info(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.hybrid.start",
                pipeline_provider="classic",
                retrieval_mode=req.mode,
                query=req.query,
                top_k=req.top_k,
                candidate_k=options.candidate_k,
                min_score=req.min_score,
            ),
        )

        async def retrieve_source(
            retriever_name: str,
            retriever: BaseRetriever,
        ) -> list[RetrievedDoc] | Exception:
            source_start_time = perf_counter()
            try:
                docs = await retriever.retrieve(req.query, options)
                filtered_docs = filter_docs_by_mode(
                    docs=docs,
                    mode=req.mode,
                    min_score=req.min_score,
                )
                latency_ms = (perf_counter() - source_start_time) * 1000
                logger.info(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.source.finish",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever=retriever_name,
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        raw_count=len(docs),
                        filtered_count=len(filtered_docs),
                        returned_count=len(filtered_docs),
                        latency_ms=round(latency_ms, 2),
                        top_doc_ids=build_top_doc_ids(filtered_docs),
                    ),
                )
                return filtered_docs
            except Exception as exc:
                latency_ms = (perf_counter() - source_start_time) * 1000
                logger.warning(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.source.failed",
                        pipeline_provider="classic",
                        retrieval_mode=req.mode,
                        retriever=retriever_name,
                        query=req.query,
                        top_k=req.top_k,
                        candidate_k=options.candidate_k,
                        min_score=req.min_score,
                        latency_ms=round(latency_ms, 2),
                        error_type=type(exc).__name__,
                    ),
                )
                return exc

        hybrid_start_time = perf_counter()
        results = await asyncio.gather(
            retrieve_source("vector", self.vector_retriever),
            retrieve_source("keyword", self.keyword_retriever),
        )

        successful_doc_lists: list[list[RetrievedDoc]] = []

        for result in results:
            if isinstance(result, Exception):
                continue

            successful_doc_lists.append(result)

        if len(successful_doc_lists) == 0:
            latency_ms = (perf_counter() - hybrid_start_time) * 1000
            logger.error(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.failed",
                    pipeline_provider="classic",
                    retrieval_mode=req.mode,
                    query=req.query,
                    top_k=req.top_k,
                    candidate_k=options.candidate_k,
                    min_score=req.min_score,
                    latency_ms=round(latency_ms, 2),
                    source_count=0,
                ),
            )
            raise ExternalServiceError("所有召回源都失败")

        input_doc_count = sum(len(docs) for docs in successful_doc_lists)
        unique_doc_count = len(
            {doc.id for docs in successful_doc_lists for doc in docs}
        )
        merged_docs = reciprocal_rank_fusion(
            doc_lists=successful_doc_lists,
            top_k=req.top_k,
        )
        latency_ms = (perf_counter() - hybrid_start_time) * 1000

        logger.info(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.rrf.finish",
                pipeline_provider="classic",
                retrieval_mode=req.mode,
                query=req.query,
                top_k=req.top_k,
                candidate_k=options.candidate_k,
                min_score=req.min_score,
                source_count=len(successful_doc_lists),
                input_doc_count=input_doc_count,
                unique_doc_count=unique_doc_count,
                output_doc_count=len(merged_docs),
                latency_ms=round(latency_ms, 2),
                top_doc_ids=build_top_doc_ids(merged_docs),
            ),
        )
        log_slow_operation(
            logger=logger,
            event="rag.retrieval.slow",
            latency_ms=latency_ms,
            threshold_ms=self.settings.slow_retrieval_threshold_ms,
            slow_component="retrieval",
            pipeline_provider="classic",
            retrieval_mode=req.mode,
            retriever="hybrid",
            top_k=req.top_k,
            candidate_k=options.candidate_k,
            source_count=len(successful_doc_lists),
            input_doc_count=input_doc_count,
            unique_doc_count=unique_doc_count,
            output_doc_count=len(merged_docs),
        )

        if len(merged_docs) == 0:
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的混合检索结果"
            )

        return merged_docs

    # 流式事件接口
    async def stream_events(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[RagStreamEvent, None]:
        with self._langsmith_trace(req, "stream_events"):
            async for event in self._stream_events(req):
                yield event

    async def _stream_events(
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
        # prompt_guard 检测 Prompt注入
        await self._ensure_query_allowed(
            req.query,
            source="classic.stream_events.input",
        )

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="retrieve",
            step_index=1,
            run_type="retriever",
            inputs={
                "query": req.query,
                "mode": req.mode,
                "top_k": req.top_k,
                "candidate_k": req.candidate_k,
                "min_score": req.min_score,
                "filters": req.filters.model_dump(),
            },
        ) as trace_run:
            docs = await self.retrieve(req)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "doc_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="rerank",
            step_index=2,
            run_type="chain",
            inputs={
                "query": req.query,
                "input_doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
        ) as trace_run:
            docs = await self.rerank_with_fallback(req.query, docs)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "output_doc_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="emit_sources",
            step_index=3,
            run_type="chain",
            inputs={
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
        ) as trace_run:
            context = await self._assemble_context(
                req,
                docs,
                source="classic.stream_events.documents",
            )
            docs = context.docs
            sources = docs_to_sources(context.docs)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "source_count": len(sources),
                        "top_source_ids": [source.id for source in sources[:5]],
                    }
                )

        yield RagStreamEvent(
            event="sources",
            data={
                "sources": sources,
            },
        )

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="build_context",
            step_index=4,
            run_type="chain",
            inputs={
                "query": req.query,
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
        ) as trace_run:
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "context_doc_count": len(context.docs),
                        "context_length": len(context.context_text),
                        **build_context_observation(context),
                    }
                )

        token_count = 0

        with self._langsmith_step_trace(
            req=req,
            operation="stream_events",
            step_name="stream_generate",
            step_index=5,
            run_type="chain",
            inputs={
                "query": req.query,
                "context_doc_count": len(context.docs),
                "context_length": len(context.context_text),
            },
        ) as trace_run:
            stream_state = GuardedStreamState()
            async for event in guarded_answer_delta_events(
                self.llm_client.stream(req.query, context),
                prompt_guard=self.prompt_guard,
                source="classic.stream_events.output",
                mode=self.settings.prompt_guard_stream_output_mode,
                max_chars=self.settings.prompt_guard_stream_chunk_max_chars,
                state=stream_state,
            ):
                yield event

            token_count = stream_state.raw_token_count
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "token_count": token_count,
                        "source_count": len(context.docs),
                        "blocked_by_prompt_guard": stream_state.blocked,
                        "emitted_answer_length": len(stream_state.answer),
                    }
                )

        logger.info(
            "RAG Stream Events 输出完成: token_count=%s",
            token_count,
        )
