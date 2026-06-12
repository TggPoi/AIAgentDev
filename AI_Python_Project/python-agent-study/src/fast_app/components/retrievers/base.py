from abc import ABC, abstractmethod

from fast_app.domain.rag_models import RetrievedDoc, RetrievalOptions

# 定义一个抽象基类，所有检索器都应该继承这个类并实现 retrieve 方法
class BaseRetriever(ABC):
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        pass