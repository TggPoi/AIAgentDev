from collections.abc import AsyncGenerator
from typing import Any

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.graph.rag_graph_builder import build_rag_graph
from fast_app.graph.rag_graph_state import GraphRagState
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse


logger = get_logger(__name__)

# FastAPI 请求模型和LangGraph final_state之间的适配层。
class LangGraphRagPipeline:

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
    ):
        self.settings = settings
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.llm_client = llm_client

        # `build_rag_graph(...)` 不在每次 `run()` 里调用，而是在构造 pipeline 时调用。因为 graph 结构是固定的。每次请求变化的是 initial_state。
        self.graph = build_rag_graph(
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
        )

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
            sources=[doc.id for doc in docs],
        )

    async def stream(
        self,
        req: RagChatRequest,
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError("LangGraphRagPipeline.stream 将在阶段 6-7 实现")

    def _build_initial_state(self, req: RagChatRequest) -> GraphRagState:
        return {
            "query": req.query,
            "mode": req.mode,
            "top_k": req.top_k,
            "min_score": req.min_score,
            "docs": [],
            "context": None,
            "answer": None,
        }