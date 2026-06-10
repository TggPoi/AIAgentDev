from abc import ABC, abstractmethod

from fast_app.domain.rag_models import RetrievedDoc


class BaseReranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        pass