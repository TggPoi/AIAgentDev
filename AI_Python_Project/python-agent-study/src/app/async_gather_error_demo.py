import asyncio
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
            content=f"Milvus result for {query}",
            score=0.91,
            source="milvus",
        )
    ]


async def es_retrieve(query: str) -> list[RetrievedDoc]:
    await asyncio.sleep(1)

    raise RuntimeError("ElasticSearch connection failed")


async def hybrid_retrieve(query: str) -> list[RetrievedDoc]:
    results = await asyncio.gather(
        milvus_retrieve(query),
        es_retrieve(query),
        return_exceptions=True,
    )

    merged_docs: list[RetrievedDoc] = []

    for result in results:

        #判断result对象是否是Exception的实例，如果是，说明这个结果是一个异常对象，说明对应的召回源发生了错误
        if isinstance(result, Exception):
            print(f"召回源失败: {result}")
            continue

        merged_docs.extend(result)

    if len(merged_docs) == 0:
        raise RuntimeError("所有召回源都失败")

    return merged_docs


async def main() -> None:
    docs = await hybrid_retrieve("什么是 RAG？")

    for doc in docs:
        print(doc)


if __name__ == "__main__":
    asyncio.run(main())


# 召回源失败: ElasticSearch connection failed
# RetrievedDoc(id='doc_001', content='Milvus result for 什么是 RAG？', score=0.91, source='milvus')