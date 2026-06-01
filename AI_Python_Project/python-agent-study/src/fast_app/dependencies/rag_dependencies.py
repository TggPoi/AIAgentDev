from fastapi import Depends

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings, get_settings
from fast_app.services.exceptions import AppServiceError
from fast_app.services.langgraph_rag_pipeline_service import LangGraphRagPipeline
from fast_app.services.rag_pipeline_service import RagPipeline


def get_vector_retriever() -> BaseRetriever:
    return MockVectorRetriever()


def get_keyword_retriever() -> BaseRetriever:
    return MockKeywordRetriever()


def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> BaseLLMClient:
    provider = settings.llm_provider.lower().strip()

    if provider == "mock":
        return MockLLMClient()

    if provider == "qwen":
        return QwenLangChainLLMClient(settings=settings)

    raise AppServiceError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")


# 这里先不写返回类型，因为RagPipeline LangGraphRagPipeline这两个类目前没有共同的显式基类。
def get_rag_pipeline(
    settings: Settings = Depends(get_settings),
    vector_retriever: BaseRetriever = Depends(get_vector_retriever),
    keyword_retriever: BaseRetriever = Depends(get_keyword_retriever),
    llm_client: BaseLLMClient = Depends(get_llm_client),
):
    provider = settings.rag_pipeline_provider.lower().strip()

    if provider == "classic":
        return RagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
        )

    if provider == "langgraph":
        return LangGraphRagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
        )

    raise AppServiceError(
        f"不支持的 RAG_PIPELINE_PROVIDER: {settings.rag_pipeline_provider}"
    )