import asyncio
import time

from dataclasses import dataclass


@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str


async def milvus_retrieve(query: str) -> list[RetrievedDoc]:
    print("milvus retrieve start")

    await asyncio.sleep(2)

    print("milvus retrieve end")

    return [
        RetrievedDoc(
            id="doc_001",
            content=f"Milvus vector result for: {query}",
            score=0.91,
            source="milvus",
        )
    ]


async def es_retrieve(query: str) -> list[RetrievedDoc]:
    print("es retrieve start")

    await asyncio.sleep(2)

    print("es retrieve end")

    return [
        RetrievedDoc(
            id="doc_002",
            content=f"ElasticSearch keyword result for: {query}",
            score=0.88,
            source="elasticsearch",
        )
    ]


def merge_docs(
    milvus_docs: list[RetrievedDoc],
    es_docs: list[RetrievedDoc],
) -> list[RetrievedDoc]:
    return milvus_docs + es_docs


async def hybrid_retrieve(query: str) -> list[RetrievedDoc]:
    milvus_docs, es_docs = await asyncio.gather(
        milvus_retrieve(query),
        es_retrieve(query),
    )

    return merge_docs(milvus_docs, es_docs)


async def main() -> None:
    start = time.perf_counter()

    docs = await hybrid_retrieve("什么是 Hybrid Retrieval？")

    for doc in docs:
        print(doc)

    end = time.perf_counter()
    print(f"cost: {end - start:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())

# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.async_rag_demo
# milvus retrieve start
# es retrieve start
# milvus retrieve end
# es retrieve end
# RetrievedDoc(id='doc_001', content='Milvus vector result for: 什么是 Hybrid Retrieval？', score=0.91, source='milvus')
# RetrievedDoc(id='doc_002', content='ElasticSearch keyword result for: 什么是 Hybrid Retrieval？', score=0.88, source='elasticsearch')
# cost: 2.01s