from langchain_openai import OpenAIEmbeddings

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings

from fast_app.core.logging import get_logger
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)


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
        try:
            return await self.embeddings.aembed_query(text)
        except Exception as exc:
            logger.exception("Embedding query 调用失败")
            # Embedding 失败会被归类为外部服务失败 Pipeline 层可以继续用统一的 ExternalServiceError 处理召回失败
            raise ExternalServiceError(f"Embedding query 调用失败: {exc}") from exc

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self.embeddings.aembed_documents(texts)
        except Exception as exc:
            logger.exception("Embedding documents 调用失败")
            raise ExternalServiceError(f"Embedding documents 调用失败: {exc}") from exc