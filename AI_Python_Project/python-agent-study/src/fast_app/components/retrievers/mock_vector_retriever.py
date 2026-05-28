import asyncio

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.domain.rag_models import RetrievedDoc


class MockVectorRetriever(BaseRetriever):
    async def retrieve(self, query: str) -> list[RetrievedDoc]:
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