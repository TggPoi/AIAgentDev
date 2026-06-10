from fast_app.components.rerankers.base import BaseReranker
from fast_app.domain.rag_models import RetrievedDoc


class MockReranker(BaseReranker):
    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        return docs[:top_k]