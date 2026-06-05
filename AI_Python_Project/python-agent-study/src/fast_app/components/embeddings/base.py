from abc import ABC, abstractmethod


class BaseEmbeddingClient(ABC):
    #向量化Query
    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        pass

    #向量化Documents
    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        pass