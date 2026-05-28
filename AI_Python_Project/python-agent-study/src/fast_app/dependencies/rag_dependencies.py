from fastapi import Depends

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings, get_settings
from fast_app.services.rag_pipeline_service import RagPipeline


def get_vector_retriever() -> BaseRetriever:
    return MockVectorRetriever()


def get_keyword_retriever() -> BaseRetriever:
    return MockKeywordRetriever()


def get_llm_client() -> BaseLLMClient:
    return MockLLMClient()


def get_rag_pipeline(
    settings: Settings = Depends(get_settings),
    vector_retriever: BaseRetriever = Depends(get_vector_retriever),
    keyword_retriever: BaseRetriever = Depends(get_keyword_retriever),
    llm_client: BaseLLMClient = Depends(get_llm_client),
) -> RagPipeline:
    return RagPipeline(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
    )