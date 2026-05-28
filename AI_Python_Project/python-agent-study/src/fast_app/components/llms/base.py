from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from fast_app.domain.rag_models import RagContext


class BaseLLMClient(ABC):
    @abstractmethod
    async def generate(self, query: str, context: RagContext) -> str:
        pass

    @abstractmethod
    async def stream(
        self,
        query: str,
        context: RagContext,
    ) -> AsyncGenerator[str, None]:
        pass