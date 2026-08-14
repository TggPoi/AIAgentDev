"""RagAgent candidate_k 候选池与最终 top_k 的确定性契约测试。"""

import asyncio
from copy import deepcopy
import os


os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievedDoc, ScoreBreakdown
from fast_app.services.exceptions import ExternalServiceError
from fast_app.graph.rag_agent.rag_agent_nodes import (
    create_agent_rerank_node,
    create_call_knowledge_retrieval_node,
)
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest


class FakeRetriever:
    def __init__(self, docs: list[RetrievedDoc]) -> None:
        self.docs = docs

    async def retrieve(self, query: str, options: object) -> list[RetrievedDoc]:
        return deepcopy(self.docs)


class PromoteLastReranker:
    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        return list(reversed(docs))[:top_k]


class FailingReranker:
    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        raise ExternalServiceError("reranker unavailable")


def build_doc(index: int) -> RetrievedDoc:
    return RetrievedDoc(
        id=f"doc-{index}",
        content=f"content-{index}",
        score=1.0 - index / 100,
        source="milvus",
        metadata={
            "doc_id": f"logical-doc-{index}",
            "logical_chunk_id": f"logical-chunk-{index}",
            "source_path": f"development/doc-{index}.md",
        },
        retrieval_sources=["milvus"],
        scores=ScoreBreakdown(vector_score=1.0 - index / 100),
    )


async def candidate_pool_reaches_reranker_before_final_top_k() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="dev",
        LANGSMITH_TRACING=False,
    )
    request = RagChatRequest(
        query="candidate pool contract",
        mode="hybrid",
        top_k=2,
        candidate_k=4,
    )
    state = build_rag_agent_initial_state(request, "run")
    vector_docs = [build_doc(index) for index in range(1, 5)]

    retrieval_result = await create_call_knowledge_retrieval_node(
        settings=settings,
        vector_retriever=FakeRetriever(vector_docs),
        keyword_retriever=FakeRetriever([]),
    )(state)
    state.update(retrieval_result)

    assert [doc.id for doc in state["docs"]] == [
        "doc-1",
        "doc-2",
        "doc-3",
        "doc-4",
    ]

    rerank_result = await create_agent_rerank_node(
        settings=settings,
        reranker=PromoteLastReranker(),
        rerank_top_k=5,
    )(state)

    assert [doc.id for doc in rerank_result["docs"]] == ["doc-4", "doc-3"]


async def duplicate_and_underfilled_candidates_keep_final_limit() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="dev",
        LANGSMITH_TRACING=False,
    )
    request = RagChatRequest(
        query="candidate pool boundaries",
        mode="hybrid",
        top_k=2,
        candidate_k=5,
    )
    state = build_rag_agent_initial_state(request, "run")
    shared = build_doc(2)

    retrieval_result = await create_call_knowledge_retrieval_node(
        settings=settings,
        vector_retriever=FakeRetriever([build_doc(1), shared]),
        keyword_retriever=FakeRetriever([shared, build_doc(3)]),
    )(state)
    state.update(retrieval_result)

    # 两路只产生 3 个唯一候选，underfilled 候选池不能补伪数据，重复 ID 也不能占名额。
    assert [doc.id for doc in state["docs"]] == ["doc-2", "doc-1", "doc-3"]

    fallback_result = await create_agent_rerank_node(
        settings=settings,
        reranker=FailingReranker(),
        rerank_top_k=5,
    )(state)

    # reranker 降级时仍按请求 top_k 返回，不能把整个候选池送入最终上下文。
    assert [doc.id for doc in fallback_result["docs"]] == ["doc-2", "doc-1"]


if __name__ == "__main__":
    asyncio.run(candidate_pool_reaches_reranker_before_final_top_k())
    asyncio.run(duplicate_and_underfilled_candidates_keep_final_limit())
    print("rag_agent candidate pool tests passed")
