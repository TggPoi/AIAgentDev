import asyncio
from collections.abc import AsyncGenerator

from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.graph.rag_state import RagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError

from fast_app.core.config import Settings
from fast_app.core.logging import get_logger

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

# 并发召回
# 过滤文档
# 合并去重
# 构造上下文
# 生成回答
# 流式生成 token
# 抛出业务异常


async def milvus_retrieve(query: str) -> list[RetrievedDoc]:
    """模拟从 Milvus 按语义相似度召回文档。"""
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
    """模拟从 ElasticSearch 按关键词召回文档。"""
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


async def retrieve_node(req: RagChatRequest) -> list[RetrievedDoc]:
    """根据检索模式执行召回、过滤、合并和异常处理。"""
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
        filtered_docs = filter_docs_by_score(docs, req.min_score)

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
        filtered_docs = filter_docs_by_score(
            docs=result,
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
    """模拟调用 LLM，根据问题和上下文生成最终回答。"""
    # 模拟 LLM 调用
    await asyncio.sleep(1)

    return (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"核心结论：混合检索会同时利用向量检索和关键词检索，"
        f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
        f"参考上下文：\n{context.text}"
    )


async def run_rag(req: RagChatRequest) -> RagChatResponse:
    """执行一次完整的非流式 RAG 流程。"""
    # 这里用 RagState 模拟后续接入 LangGraph 时的图状态。
    state: RagState = {
        "query": req.query,
        "docs": [],
        "context": None,
        "answer": None,
    }

    docs = await retrieve_node(req)
    state["docs"] = docs

    context = build_context_node(docs)
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
    """模拟 LLM 流式输出，把完整回答拆成字符逐个返回。"""
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
    """执行完整 RAG 流程，并以异步生成器形式流式返回回答。"""
    logger.info(
        "开始执行 RAG Stream Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
        req.query,
        req.mode,
        req.top_k,
        req.min_score,
    )

    docs = await retrieve_node(req)

    logger.info("RAG Stream 召回完成: docs_count=%s", len(docs))

    context = build_context_node(docs)

    logger.info("RAG Stream 上下文构造完成: context_docs_count=%s", len(context.docs))

    token_count = 0

    async for token in stream_answer_node(req.query, context):
        token_count += 1
        yield token

    # 后续如果真的需要排查 token 级别问题（每个 token 都打一条日志），可以临时用 `DEBUG` 日志。
    logger.info("RAG Stream 输出完成: token_count=%s", token_count)



# Router 以后不直接依赖 run_rag / run_rag_stream。
# Router 只依赖 RagPipeline。
# RagPipeline 内部暂时复用原有函数。
# 后续再逐步把真实 Retriever、LLMClient、Settings 注入进 RagPipeline。
class RagPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        print(f"当前应用环境: {settings.app_env}")
        print(f"当前 LLM 模型: {settings.llm_model_name}")

    async def run(self, req: RagChatRequest) -> RagChatResponse:
        return await run_rag(req)

    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        async for token in run_rag_stream(req):
            yield token