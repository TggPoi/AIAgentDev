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
from fast_app.domain.prompt_guard_models import PromptGuardResult
from fast_app.graph.rag_agent.rag_agent_nodes import (
    build_rag_agent_answer_query,
    create_next_action_decision_node,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.conversation.conversation_history import build_conversation_memory_context
from fast_app.services.conversation.conversation_memory import InMemoryConversationMemoryStore
from fast_app.services.conversation.conversation_scope import scope_rag_chat_request
from fast_app.services.conversation.query_rewrite import QueryRewriteResult
from fast_app.services.rag.rag_agent_pipeline_service import RagAgentPipeline
from fast_app.services.agent_tasks.agent_task_router import (
    AgentRouteDecision,
    AgentTaskRouteResult,
)
from fast_app.services.exceptions import ExternalServiceError


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
            relevant_message_ids=[memory_context.recent_window.messages[-1].id],
        )


class WrongUnresolvedRewriter:
    async def rewrite(
        self,
        query: str,
        **_kwargs,
    ) -> QueryRewriteResult:
        return QueryRewriteResult(
            original_query=query,
            rewritten_query=query,
            used_history=False,
            reason="model_misclassified_complete_query",
            resolution_status="unresolved",
            relevant_message_ids=[],
            clarification_question="请说明你指的是哪个知识库。",
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

    async def plan_question_decomposition(self, request, **_kwargs):
        self.query = request.resolved_query
        self.history = request.relevant_history
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


class ClarificationRouter:
    async def route(self, **_kwargs):
        return AgentTaskRouteResult(
            decision=AgentRouteDecision(
                intent="clarification_required",
                confidence=0.95,
                reason="current_query_still_incomplete",
                clarification_question="请说明需要继续处理哪个对象。",
            ),
            source="model",
            latency_ms=1.0,
            clarification_code="ambiguous_intent",
        )


class RecordingPromptGuard:
    def __init__(self) -> None:
        self.inputs: list[tuple[str, str]] = []

    async def ensure_user_input_allowed(self, text: str, *, source: str, **_kwargs):
        self.inputs.append((text, source))

    def scan_user_input(self, text: str, *, source: str):
        return PromptGuardResult(reason=f"{source}_allowed")

    def audit_guard_result(self, **_kwargs):
        return None


class RecordingCapabilityService:
    async def resolve_research(self, **_kwargs):
        from fast_app.domain.research_task_plan import AgentTaskCapabilitySnapshot

        return AgentTaskCapabilitySnapshot(
            available_source_types=["knowledge_retrieval"],
            web_direct_allowed=False,
            web_fallback_allowed=False,
            knowledge_retrieval_available=True,
            nl2sql_query_available=False,
            max_requirements=8,
            max_sub_questions=4,
        )


class FailingPromptGuard:
    async def ensure_user_input_allowed(self, *_args, **_kwargs):
        raise ExternalServiceError("guard unavailable")


class CountingRouter:
    def __init__(self, intent: str) -> None:
        self.intent = intent
        self.calls = 0

    async def route(self, **_kwargs):
        self.calls += 1
        return AgentTaskRouteResult(
            decision=AgentRouteDecision(
                intent=self.intent,
                confidence=0.99,
                reason="must not be reached",
            ),
            source="model",
            latency_ms=1.0,
        )


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
        current_user=CurrentUserContext(
            user_id="u1",
            is_authenticated=True,
            auth_source="jwt",
        ),
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
    ]
    assert all("已经找到部署规范文档" not in text for text, _source in prompt_guard.inputs)

    planner = RecordingPlanner()
    await create_next_action_decision_node(
        settings,
        task_router=cast(Any, QuestionRouter()),
        task_planner=cast(Any, planner),
        capability_service=cast(Any, RecordingCapabilityService()),
    )(state)
    assert planner.query == state["query"]
    assert len(planner.history) == 1
    assert planner.history[0].content == "已经找到部署规范文档"
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
        capability_service=cast(Any, RecordingCapabilityService()),
    )(empty_state)
    assert empty_planner.history == []
    assert build_rag_agent_answer_query(empty_state) == empty_state["query"]

    independent_pipeline = RagAgentPipeline(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(settings=settings),
        reranker=MockReranker(),
        conversation_memory_store=store,
        query_rewriter=cast(Any, WrongUnresolvedRewriter()),
        current_user=CurrentUserContext(
            user_id="u1",
            is_authenticated=True,
            auth_source="jwt",
        ),
    )
    independent_query = "请分析当前知识库中混合检索与 rerank 的职责差异。"
    independent_state = await independent_pipeline._prepare_initial_state(
        RagChatRequest(
            session_id=conversation_id,
            query=independent_query,
            mode="hybrid",
            top_k=3,
        ),
        operation="stream_events",
    )
    assert independent_state["query"] == independent_query
    assert independent_state["rewritten_query"] == independent_query
    assert (
        independent_state["query_rewrite_reason"]
        == "rewriter_unresolved_current_query_preserved"
    )
    assert independent_state["planning_history"] == []

    independent_planner = RecordingPlanner()
    independent_update = await create_next_action_decision_node(
        settings,
        task_router=cast(Any, QuestionRouter()),
        task_planner=cast(Any, independent_planner),
        capability_service=cast(Any, RecordingCapabilityService()),
    )(independent_state)
    assert independent_planner.query == independent_query
    assert independent_update["route_intent"] == "question_decomposition"

    ambiguous_state = await independent_pipeline._prepare_initial_state(
        RagChatRequest(
            session_id=conversation_id,
            query="继续处理它",
            mode="hybrid",
            top_k=3,
        ),
        operation="stream_events",
    )
    clarification_update = await create_next_action_decision_node(
        settings,
        task_router=cast(Any, ClarificationRouter()),
    )(ambiguous_state)
    assert clarification_update["route"] == "clarification_required"
    assert clarification_update["clarification_required"] is True
    assert clarification_update["clarification_code"] == "ambiguous_intent"

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

    # rag_agent 的所有非敏感路由共享同一个 Guard 前置边界；分类服务技术失败时
    # 必须 fail closed，不能让任意 Router 或下游节点继续运行。
    for intent in (
        "simple_rag",
        "structured_data_query",
        "web_research",
        "question_decomposition",
        "knowledge_document_management",
    ):
        router = CountingRouter(intent)
        guarded_pipeline = RagAgentPipeline(
            settings=settings,
            vector_retriever=MockVectorRetriever(),
            keyword_retriever=MockKeywordRetriever(),
            llm_client=MockLLMClient(settings=settings),
            reranker=MockReranker(),
            prompt_guard=cast(Any, FailingPromptGuard()),
            task_router=cast(Any, router),
        )
        try:
            await guarded_pipeline.run(RagChatRequest(query="安全边界测试"))
        except ExternalServiceError:
            pass
        else:
            raise AssertionError(f"{intent} 必须在 Guard 技术失败时 fail closed")
        assert router.calls == 0
    print("agent_conversation_context=passed")


if __name__ == "__main__":
    asyncio.run(main())
