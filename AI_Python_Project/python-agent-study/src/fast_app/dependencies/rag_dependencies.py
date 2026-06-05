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

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.components.retrievers.milvus_vector_retriever import MilvusVectorRetriever



def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> BaseLLMClient:
    provider = settings.llm_provider.lower().strip()

    if provider == "mock":
        return MockLLMClient()

    if provider == "qwen":
        return QwenLangChainLLMClient(settings=settings)

    raise AppServiceError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")


def get_embedding_client(
    settings: Settings = Depends(get_settings),
) -> BaseEmbeddingClient:
    provider = settings.embedding_provider.lower().strip()

    if provider == "qwen":
        return QwenEmbeddingClient(settings=settings)

    raise AppServiceError(
        f"不支持的 EMBEDDING_PROVIDER: {settings.embedding_provider}"
    )



def get_vector_retriever(
    settings: Settings = Depends(get_settings),
) -> BaseRetriever:
    provider = settings.vector_retriever_provider.lower().strip()

    if provider == "mock":
        return MockVectorRetriever()

    if provider == "milvus":
        # Depends(get_embedding_client) 不使用这种写法,因为即使 VECTOR_RETRIEVER_PROVIDER=mock，FastAPI 执行get_vector_retriever 时 也会先创建 embedding_client。mock 测试并不需要这些内容
        embedding_client = get_embedding_client(settings=settings)

        return MilvusVectorRetriever(
            settings=settings,
            embedding_client=embedding_client,
        )

    raise AppServiceError(
        f"不支持的 VECTOR_RETRIEVER_PROVIDER: {settings.vector_retriever_provider}"
    )


def get_keyword_retriever(
    settings: Settings = Depends(get_settings),
) -> BaseRetriever:
    provider = settings.keyword_retriever_provider.lower().strip()

    if provider == "mock":
        return MockKeywordRetriever()

    if provider == "elasticsearch":
        return ElasticsearchKeywordRetriever(settings=settings)

    raise AppServiceError(
        f"不支持的 KEYWORD_RETRIEVER_PROVIDER: {settings.keyword_retriever_provider}"
    )



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