from typing import Literal

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.graph.rag.rag_graph_builder import build_rag_graph
from fast_app.services.rag.prompt_guard_service import PromptGuardService


RagAgentAssemblyMode = Literal["explicit_graph", "create_agent"]


def build_explicit_rag_agent(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
    prompt_guard: PromptGuardService | None = None,
):
    return build_rag_graph(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
        reranker=reranker,
        rerank_top_k=settings.rerank_top_k,
        prompt_guard=prompt_guard,
    )


def build_rag_agent(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
    mode: RagAgentAssemblyMode = "explicit_graph",
    prompt_guard: PromptGuardService | None = None,
):
    if mode == "explicit_graph":
        return build_explicit_rag_agent(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            prompt_guard=prompt_guard,
        )

    raise ValueError("create_agent assembly is planned for a later phase.")
