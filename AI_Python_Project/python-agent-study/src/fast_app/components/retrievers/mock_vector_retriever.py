import asyncio

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.domain.rag_models import RetrievalOptions, RetrievedDoc


class MockVectorRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        await asyncio.sleep(1)

        docs = [
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
        
        return docs[: options.candidate_k]