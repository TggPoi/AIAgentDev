# 异步 RAG 业务流程

import asyncio
from collections.abc import AsyncGenerator

from app.domain.rag_models import RagContext, RetrievedDoc
from app.graph.rag_state import RagState
from app.schemas.rag_schema import RagRequest, RagResponse


class RagPipelineError(Exception):
    pass


async def milvus_retrieve(query: str) -> list[RetrievedDoc]:
    # 模拟 Milvus 网络 IO 延迟
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
    # 模拟 ElasticSearch 网络 IO 延迟
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
    # 过滤掉低于分数阈值的文档
    return [
        doc for doc in docs
        if doc.score >= min_score
    ]


def merge_docs_by_id(
    doc_lists: list[list[RetrievedDoc]],
    top_k: int,
) -> list[RetrievedDoc]:
    # 使用 dict 按 id 去重
    # 如果同一个 id 出现多次，保留 score 更高的版本
    doc_map: dict[str, RetrievedDoc] = {}

    for docs in doc_lists:
        for doc in docs:
            existing = doc_map.get(doc.id)

            if existing is None or doc.score > existing.score:
                doc_map[doc.id] = doc

    # 按 score 从高到低排序
    merged_docs = sorted(
        doc_map.values(),#获取去重后的文档列表
        key=lambda doc: doc.score,#一行的lambda表达式，按照文档的score属性进行排序
        reverse=True,#倒序排序
    )

    return merged_docs[:top_k]


async def retrieve_node(req: RagRequest) -> list[RetrievedDoc]:
    # 根据 mode 决定走哪种召回方式
    if req.mode == "vector":
        docs = await milvus_retrieve(req.query)
        return filter_docs_by_score(docs, req.min_score)[: req.top_k]

    if req.mode == "keyword":
        docs = await es_retrieve(req.query)
        return filter_docs_by_score(docs, req.min_score)[: req.top_k]

    # hybrid 模式：Milvus 和 ES 并发召回
    results = await asyncio.gather(
        milvus_retrieve(req.query),
        es_retrieve(req.query),
        return_exceptions=True,
    )

    successful_doc_lists: list[list[RetrievedDoc]] = []

    for result in results:
        if isinstance(result, Exception):
            # 真实工程中这里应该记录日志
            print(f"召回源失败: {result}")
            continue

        filtered_docs = filter_docs_by_score(
            docs=result,
            min_score=req.min_score,
        )
        successful_doc_lists.append(filtered_docs)

    if len(successful_doc_lists) == 0:
        raise RagPipelineError("所有召回源都失败")

    return merge_docs_by_id(
        doc_lists=successful_doc_lists,
        top_k=req.top_k,
    )


def build_context_node(docs: list[RetrievedDoc]) -> RagContext:
    if len(docs) == 0:
        raise RagPipelineError("没有可用于构造上下文的文档")

    context_parts: list[str] = []

    for index, doc in enumerate(docs):
        context_parts.append(
            f"[{index}] source={doc.source}, score={doc.score}\n{doc.content}"
        )

    context_text = "\n\n".join(context_parts)

    return RagContext(
        text=context_text,
        docs=docs,
    )


async def generate_answer_node(
    query: str,
    context: RagContext,
) -> str:
    # 模拟 LLM API 调用延迟
    await asyncio.sleep(1)

    return (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"核心结论：混合检索会同时利用向量检索和关键词检索，"
        f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
        f"参考上下文：\n{context.text}"
    )


async def run_rag(req: RagRequest) -> RagResponse:
    # 初始化状态，模拟 LangGraph State
    state: RagState = {
        "query": req.query,
        "docs": [],
        "context": None,
        "answer": None,
    }

    # 1. 检索节点
    docs = await retrieve_node(req)
    state["docs"] = docs

    # 2. 构造上下文节点
    context = build_context_node(docs)
    state["context"] = context

    # 3. 生成回答节点
    answer = await generate_answer_node(
        query=state["query"],
        context=context,
    )
    state["answer"] = answer

    # 4. 构造 API 响应模型
    return RagResponse(
        query=state["query"],
        answer=state["answer"] or "",
        sources=[doc.id for doc in state["docs"]],
    )


async def stream_answer_node(
    query: str,
    context: RagContext,
) -> AsyncGenerator[str, None]:
    # 这里模拟 LLM token streaming
    answer = (
        f"根据检索到的上下文，回答问题：{query}\n"
        f"混合检索的核心是：同时使用向量检索和关键词检索，"
        f"然后合并、去重、排序，得到更稳定的结果。\n\n"
        f"上下文摘要：{context.text}"
    )

    for char in answer:
        await asyncio.sleep(0.02)
        yield char


async def run_rag_stream(req: RagRequest) -> AsyncGenerator[str, None]:
    # 1. 先完成检索
    docs = await retrieve_node(req)

    # 2. 构造上下文
    context = build_context_node(docs)

    # 3. 流式生成回答
    async for token in stream_answer_node(req.query, context):
        yield token