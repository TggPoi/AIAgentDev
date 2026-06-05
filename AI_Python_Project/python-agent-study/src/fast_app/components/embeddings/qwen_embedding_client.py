from langchain_openai import OpenAIEmbeddings

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings


class QwenEmbeddingClient(BaseEmbeddingClient):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 为空，无法调用 embedding 模型")

        self.settings = settings

        self.embeddings = OpenAIEmbeddings(
            model=settings.embedding_model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            dimensions=settings.embedding_dim,
            check_embedding_ctx_length=False,
        )

    async def embed_query(self, text: str) -> list[float]:
        return await self.embeddings.aembed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.embeddings.aembed_documents(texts)