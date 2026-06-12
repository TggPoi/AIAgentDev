import asyncio

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.domain.rag_models import RetrievalOptions, RetrievedDoc


class MockKeywordRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        await asyncio.sleep(1)

        docs = [
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

        return docs[: options.candidate_k]