from collections.abc import AsyncGenerator
from typing import Any

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.graph.rag_graph_builder import build_rag_graph
from fast_app.graph.rag_graph_state import GraphRagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse

from fast_app.services.rag_pipeline_service import docs_to_sources

from fast_app.graph.rag_graph_nodes import (
    create_build_context_node,
    create_retrieve_node,
    create_rerank_node,
)
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)

# FastAPI 请求模型和LangGraph final_state之间的适配层。
class LangGraphRagPipeline:

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker
    ):
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client
        self.reranker = reranker
        self.rerank_node = create_rerank_node(
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )
        
        # `build_rag_graph(...)` 不在每次 `run()` 里调用，而是在构造 pipeline 时调用。因为 graph 结构是固定的。每次请求变化的是 initial_state。
        self.graph = build_rag_graph(
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            rerank_top_k=settings.rerank_top_k,
        )

        self.retrieve_node = create_retrieve_node(
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        )
        self.build_context_node = create_build_context_node()



    async def run(self, req: RagChatRequest) -> RagChatResponse:
        logger.info(
            "开始执行 LangGraph RAG Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )

        initial_state = self._build_initial_state(req)

        final_state = await self.graph.ainvoke(initial_state)

        answer = final_state.get("answer") or ""
        docs = final_state.get("docs") or []

        logger.info(
            "LangGraph RAG Pipeline 执行完成: docs_count=%s, answer_length=%s",
            len(docs),
            len(answer),
        )

        return RagChatResponse(
            query=final_state["query"],
            answer=answer,
            sources=docs_to_sources(docs),
        )
    

    def _build_initial_state(self, req: RagChatRequest) -> GraphRagState:
        return {
            "query": req.query,
            "mode": req.mode,
            "top_k": req.top_k,
            "candidate_k": req.candidate_k,
            "min_score": req.min_score,
            "filters": req.filters.model_dump(),
            "docs": [],
            "context": None,
            "answer": None,
        }
    

    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        logger.info(
            "开始执行 LangGraph RAG Stream Pipeline: query=%s, mode=%s, top_k=%s, min_score=%s",
            req.query,
            req.mode,
            req.top_k,
            req.min_score,
        )

        state = self._build_initial_state(req)

        rerank_update = await self.rerank_node(state)
        state.update(rerank_update)

        build_context_update = await self.build_context_node(state)
        state.update(build_context_update)

        retrieve_update = await self.retrieve_node(state)
        state.update(retrieve_update)

        context = state["context"]

        if context is None:
            raise ExternalServiceError("LangGraph RAG Stream 上下文为空，无法流式生成回答")

        token_count = 0

        async for token in self.llm_client.stream(
            query=req.query,
            context=context,
        ):
            token_count += 1
            yield token

        logger.info(
            "LangGraph RAG Stream Pipeline 执行完成: token_count=%s",
            token_count,
        )
