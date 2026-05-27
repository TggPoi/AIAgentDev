import asyncio
from collections.abc import AsyncGenerator

from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.graph.rag_state import RagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError

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
        # 纯向量模式只查询 Milvus。
        docs = await milvus_retrieve(req.query)
        filtered_docs = filter_docs_by_score(docs, req.min_score)

        if len(filtered_docs) == 0:
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的向量检索结果"
            )

        return filtered_docs[: req.top_k]

    if req.mode == "keyword":
        # 纯关键词模式只查询 ElasticSearch。
        docs = await es_retrieve(req.query)
        filtered_docs = filter_docs_by_score(docs, req.min_score)

        if len(filtered_docs) == 0:
            raise NoSearchResultError(
                f"没有找到满足 min_score={req.min_score} 的关键词检索结果"
            )

        return filtered_docs[: req.top_k]

    # hybrid 模式：Milvus + ES 并发召回
    results = await asyncio.gather(
        milvus_retrieve(req.query),
        es_retrieve(req.query),
        return_exceptions=True,
    )

    successful_doc_lists: list[list[RetrievedDoc]] = []

    for result in results:
        if isinstance(result, Exception):
            # 真实工程中这里应该写日志
            print(f"召回源失败: {result}")
            continue

        # 单个召回源成功时也要先做分数过滤，再进入合并流程。
        filtered_docs = filter_docs_by_score(
            docs=result,
            min_score=req.min_score,
        )
        successful_doc_lists.append(filtered_docs)

    if len(successful_doc_lists) == 0:
        raise ExternalServiceError("所有召回源都失败")

    merged_docs = merge_docs_by_id(
        doc_lists=successful_doc_lists,
        top_k=req.top_k,
    )

    if len(merged_docs) == 0:
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
    docs = await retrieve_node(req)
    context = build_context_node(docs)

    async for token in stream_answer_node(req.query, context):
        yield token
