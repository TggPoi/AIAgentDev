import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass


@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str


async def milvus_retrieve(query: str) -> list[RetrievedDoc]:
    await asyncio.sleep(1)

    return [
        RetrievedDoc(
            id="doc_001",
            content=f"Milvus vector result for: {query}",
            score=0.91,
            source="milvus",
        )
    ]


async def es_retrieve(query: str) -> list[RetrievedDoc]:
    await asyncio.sleep(1)

    return [
        RetrievedDoc(
            id="doc_002",
            content=f"ElasticSearch keyword result for: {query}",
            score=0.88,
            source="elasticsearch",
        )
    ]


async def hybrid_retrieve(query: str) -> list[RetrievedDoc]:
    milvus_docs, es_docs = await asyncio.gather(
        milvus_retrieve(query),
        es_retrieve(query),
    )

    return milvus_docs + es_docs


def build_context(docs: list[RetrievedDoc]) -> str:
    contents = [doc.content for doc in docs]
    return "\n".join(contents)


async def mock_llm_stream(
    query: str,
    context: str,
) -> AsyncGenerator[str, None]:
    answer = f"根据上下文回答问题：{query}\n上下文：{context}"

    for char in answer:
        await asyncio.sleep(0.03)
        yield char


async def rag_stream(query: str) -> AsyncGenerator[str, None]:
    docs = await hybrid_retrieve(query)
    context = build_context(docs)

    async for token in mock_llm_stream(query, context):
        yield token


async def main() -> None:
    async for token in rag_stream("什么是混合检索？"):
        print(token, end="", flush=True)

    print()


if __name__ == "__main__":
    asyncio.run(main())