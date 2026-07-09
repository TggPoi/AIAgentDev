from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from langchain_core.runnables import RunnableConfig

from fast_app.domain.rag_models import RagContext


class BaseLLMClient(ABC):
    @abstractmethod
    async def generate(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> str:
        pass

    @abstractmethod
    async def stream(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> AsyncGenerator[str, None]:
        pass
