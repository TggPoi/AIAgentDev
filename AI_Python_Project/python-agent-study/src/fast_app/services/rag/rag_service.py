import asyncio
from collections.abc import AsyncGenerator

from fast_app.schemas.rag_schema import (
    RetrievedDocument,
    SearchRequest,
    SearchResponse,
)
from fast_app.services.exceptions import DocumentNotFoundError, NoSearchResultError


async def mock_milvus_search(query: str) -> list[RetrievedDocument]:
    # 模拟 Milvus 网络 IO
    await asyncio.sleep(1)

    return [
        RetrievedDocument(
            id="doc_001",
            content=f"Milvus vector result for: {query}",
            score=0.91,
            source="milvus",
        ),
        RetrievedDocument(
            id="doc_shared",
            content="Hybrid retrieval combines vector search and keyword search.",
            score=0.86,
            source="milvus",
        ),
    ]


async def mock_es_search(query: str) -> list[RetrievedDocument]:
    # 模拟 ElasticSearch 网络 IO
    await asyncio.sleep(1)

    return [
        RetrievedDocument(
            id="doc_002",
            content=f"ElasticSearch keyword result for: {query}",
            score=0.88,
            source="elasticsearch",
        ),
        RetrievedDocument(
            id="doc_shared",
            content="Hybrid retrieval combines vector search and keyword search.",
            score=0.84,
            source="elasticsearch",
        ),
    ]


def filter_docs_by_score(
    docs: list[RetrievedDocument],
    min_score: float,
) -> list[RetrievedDocument]:
    return [
        doc for doc in docs
        if doc.score >= min_score
    ]


def merge_docs_by_id(
    doc_lists: list[list[RetrievedDocument]],
    top_k: int,
) -> list[RetrievedDocument]:
    doc_map: dict[str, RetrievedDocument] = {}

    for docs in doc_lists:
        for doc in docs:
            existing = doc_map.get(doc.id)

            if existing is None or doc.score > existing.score:
                doc_map[doc.id] = doc

    merged_docs = sorted(
        doc_map.values(),
        key=lambda doc: doc.score,
        reverse=True,
    )

    return merged_docs[:top_k]


async def search(req: SearchRequest) -> SearchResponse:
    if req.mode == "vector":
        docs = await mock_milvus_search(req.query)
        filtered_docs = filter_docs_by_score(docs, req.min_score)

    elif req.mode == "keyword":
        docs = await mock_es_search(req.query)
        filtered_docs = filter_docs_by_score(docs, req.min_score)

    else:
        milvus_docs, es_docs = await asyncio.gather(
            mock_milvus_search(req.query),
            mock_es_search(req.query),
        )

        filtered_milvus_docs = filter_docs_by_score(
            docs=milvus_docs,
            min_score=req.min_score,
        )
        filtered_es_docs = filter_docs_by_score(
            docs=es_docs,
            min_score=req.min_score,
        )

        filtered_docs = merge_docs_by_id(
            doc_lists=[filtered_milvus_docs, filtered_es_docs],
            top_k=req.top_k,
        )

    if len(filtered_docs) == 0:
        raise NoSearchResultError(
            f"没有找到满足 min_score={req.min_score} 的文档"
        )

    return SearchResponse(
        query=req.query,
        mode=req.mode,
        documents=filtered_docs[: req.top_k],
    )


async def get_document(doc_id: str) -> RetrievedDocument:
    # 模拟数据库 / 向量库查询延迟
    await asyncio.sleep(0.3)

    mock_docs = {
        "doc_001": RetrievedDocument(
            id="doc_001",
            content="Milvus vector result",
            score=0.91,
            source="milvus",
        ),
        "doc_002": RetrievedDocument(
            id="doc_002",
            content="ElasticSearch keyword result",
            score=0.88,
            source="elasticsearch",
        ),
    }

    doc = mock_docs.get(doc_id)

    if doc is None:
        raise DocumentNotFoundError(f"文档不存在: {doc_id}")

    return doc


async def stream_search(req: SearchRequest) -> AsyncGenerator[str, None]:
    response = await search(req)

    context_parts: list[str] = []

    for doc in response.documents:
        context_parts.append(
            f"[{doc.source}] {doc.content}"
        )

    context = "\n".join(context_parts)

    answer = (
        f"根据检索结果回答问题：{req.query}\n"
        f"检索模式：{req.mode}\n"
        f"上下文：\n{context}\n"
        f"结论：混合检索可以结合向量召回和关键词召回，提高结果稳定性。"
    )

    for char in answer:
        await asyncio.sleep(0.03)
        yield char