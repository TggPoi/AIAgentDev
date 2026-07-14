import asyncio
from typing import Any, cast

from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.rerankers.mock_reranker import MockReranker
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings
from fast_app.domain.conversation_models import (
    ConversationMessage,
    ConversationRole,
    ConversationSummary,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.rag_agent_nodes import (
    build_rag_agent_answer_query,
    create_next_action_decision_node,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.conversation_history import build_conversation_memory_context
from fast_app.services.conversation_memory import InMemoryConversationMemoryStore
from fast_app.services.conversation_scope import scope_rag_chat_request
from fast_app.services.query_rewrite import QueryRewriteResult
from fast_app.services.rag_agent_pipeline_service import RagAgentPipeline
from fast_app.services.agent_task_router import (
    AgentRouteDecision,
    AgentTaskRouteResult,
)


class RecordingRewriter:
    def __init__(self) -> None:
        self.memory_context = None

    async def rewrite(self, query: str, memory_context=None, **_kwargs) -> QueryRewriteResult:
        self.memory_context = memory_context
        return QueryRewriteResult(
            original_query=query,
            rewritten_query=query,
            used_history=True,
            used_summary=memory_context.summary_text is not None,
            summary_version=memory_context.summary_version,
            reason="test_context",
        )


class FixedSummaryService:
    def __init__(self, summary: ConversationSummary) -> None:
        self.summary = summary

    async def maybe_update_summary(self, **_kwargs) -> ConversationSummary:
        return self.summary

    def build_memory_context(self, conversation_id: str, recent_window, summary):
        return build_conversation_memory_context(
            conversation_id=conversation_id,
            recent_window=recent_window,
            summary=summary,
        )


class RecordingPlanner:
    def __init__(self) -> None:
        self.query = None
        self.history = None

    async def plan_question_decomposition(self, query: str, history=None, **_kwargs):
        self.query = query
        self.history = history
        return None


class QuestionRouter:
    async def route(self, **_kwargs):
        return AgentTaskRouteResult(
            decision=AgentRouteDecision(
                intent="question_decomposition",
                confidence=0.99,
                reason="test",
            ),
            source="model",
            latency_ms=1.0,
        )


class RecordingPromptGuard:
    def __init__(self) -> None:
        self.inputs: list[tuple[str, str]] = []

    async def ensure_user_input_allowed(self, text: str, *, source: str):
        self.inputs.append((text, source))


async def main() -> None:
    settings = Settings(
        LANGSMITH_TRACING=False,
        MEMORY_HISTORY_MAX_TURNS=3,
    )
    store = InMemoryConversationMemoryStore()
    conversation_id = "agent-context-test"
    for role, content in (
        (ConversationRole.USER, "查找 RAG 部署规范"),
        (ConversationRole.ASSISTANT, "已经找到部署规范文档"),
    ):
        await store.append_message(
            ConversationMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
        )

    summary = ConversationSummary(
        conversation_id=conversation_id,
        summary_text="用户正在整理 RAG 部署资料。",
        version=2,
        source_message_ids=["old-1", "old-2"],
        source_message_count=2,
    )
    rewriter = RecordingRewriter()
    prompt_guard = RecordingPromptGuard()
    pipeline = RagAgentPipeline(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(settings=settings),
        reranker=MockReranker(),
        conversation_memory_store=store,
        query_rewriter=cast(Any, rewriter),
        conversation_summary_service=cast(Any, FixedSummaryService(summary)),
        prompt_guard=cast(Any, prompt_guard),
        task_router=cast(Any, QuestionRouter()),
    )

    state = await pipeline._prepare_initial_state(
        RagChatRequest(
            session_id=conversation_id,
            query="根据刚才的资料创建清单",
            mode="hybrid",
            top_k=3,
        ),
        operation="run",
    )
    assert "查找 RAG 部署规范" in (state["history_window_text"] or "")
    assert state["summary_text"] == summary.summary_text
    assert state["summary_used"] is True
    assert state["summary_version"] == 2
    assert state["summary_source_message_count"] == 2
    assert state["summary_source_message_ids"] == ["old-1", "old-2"]
    assert rewriter.memory_context is not None
    assert summary.summary_text in rewriter.memory_context.formatted_text
    assert "已经找到部署规范文档" in rewriter.memory_context.formatted_text
    assert prompt_guard.inputs == [
        ("根据刚才的资料创建清单", "rag_agent.query_rewrite.raw_input"),
        ("根据刚才的资料创建清单", "rag_agent.query_rewrite.rewritten_query"),
    ]
    assert all("已经找到部署规范文档" not in text for text, _source in prompt_guard.inputs)

    planner = RecordingPlanner()
    await create_next_action_decision_node(
        settings,
        task_router=cast(Any, QuestionRouter()),
        task_planner=cast(Any, planner),
    )(state)
    assert planner.query == state["query"]
    assert planner.history == [
        "【会话摘要】\n用户正在整理 RAG 部署资料。",
        "【最近对话】\n" + state["history_window_text"],
    ]
    answer_query = build_rag_agent_answer_query(state)
    assert answer_query.startswith(state["query"])
    assert "<conversation_context>" in answer_query
    assert summary.summary_text in answer_query
    assert "已经找到部署规范文档" in answer_query

    legacy_state = dict(state)
    legacy_state["operation"] = "stream"
    assert build_rag_agent_answer_query(cast(Any, legacy_state)) == state["query"]

    empty_state = await pipeline._prepare_initial_state(
        RagChatRequest(query="单轮问题", mode="hybrid", top_k=3),
        operation="run",
    )
    assert empty_state["history_window_text"] is None
    assert empty_state["summary_text"] is None
    assert empty_state["summary_used"] is False

    empty_planner = RecordingPlanner()
    await create_next_action_decision_node(
        settings,
        task_router=cast(Any, QuestionRouter()),
        task_planner=cast(Any, empty_planner),
    )(empty_state)
    assert empty_planner.history == []
    assert build_rag_agent_answer_query(empty_state) == empty_state["query"]

    external_req = RagChatRequest(
        session_id="same-session",
        query="隔离测试",
        mode="hybrid",
        top_k=3,
    )
    alice_req = scope_rag_chat_request(
        external_req,
        CurrentUserContext(user_id="alice", auth_source="demo_header"),
    )
    bob_req = scope_rag_chat_request(
        external_req,
        CurrentUserContext(user_id="bob", auth_source="demo_header"),
    )
    assert alice_req.session_id != bob_req.session_id
    print("agent_conversation_context=passed")


if __name__ == "__main__":
    asyncio.run(main())
