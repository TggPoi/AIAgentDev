from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

import fast_app.services.research.research_tool_loop as tool_loop_module
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskSubQuestion,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import (
    ResearchToolLoop,
    ToolExecutionResult,
)
from fast_app.services.research.research_worker_agent import (
    ResearchWorkerAgent,
    ResearchWorkerRequest,
)


class FakeRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                id=f"doc_{query[:8]}",
                content=f"fake evidence: {query}",
                score=0.9,
                source="fake",
                title="fake doc",
            )
        ]


class FakeLLM(BaseLLMClient):
    def __init__(self) -> None:
        self.generate_calls: list[tuple[str, RagContext]] = []

    async def generate(self, query: str, context: RagContext) -> str:
        self.generate_calls.append((query, context))
        return f"answer: {query} | {context.context_text[:120]}"

    async def stream(self, query: str, context: RagContext):
        yield await self.generate(query, context)


class LoopResearchToolLoop(ResearchToolLoop):
    async def _select_tool_for_sub_question(self, *args, **kwargs) -> dict[str, Any]:
        sub_question = kwargs["sub_question"]
        tool_calls = kwargs.get("current_tool_calls") or []
        if sub_question.sub_question_id == "sq_loop":
            if len(tool_calls) == 0:
                return {
                    "selected_tool": "knowledge_retrieval",
                    "tool_input": {"query": "内部 RAG 设计", "top_k": 2},
                    "reason": "先查内部知识库",
                }
            if len(tool_calls) == 1:
                return {
                    "selected_tool": "web_search",
                    "tool_input": {"query": "RAG evaluation practice", "count": 1},
                    "reason": "再补公开资料",
                }
            return {"selected_tool": "none", "tool_input": {}, "reason": "证据足够"}
        if sub_question.sub_question_id == "sq_limit":
            return {
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "循环上限测试", "top_k": 1},
                "reason": "故意超过上限",
            }
        return {
            "selected_tool": "unknown_tool",
            "tool_input": {},
            "reason": "测试未知工具不能执行",
        }

    async def _run_knowledge_retrieval_for_sub_question(self, *args, **kwargs):
        doc = RetrievedDoc(
            id="doc_1",
            content="完整的内部 RAG 设计证据",
            score=0.9,
            source="knowledge_retrieval",
        )
        return ToolExecutionResult(
            tool_output={"doc_count": 1, "top_doc_ids": ["doc_1"]},
            evidence=[{"id": "doc_1", "source": "knowledge_retrieval"}],
            context_docs=[doc],
        )

    async def _run_web_search_for_sub_question(self, *args, **kwargs):
        doc = RetrievedDoc(
            id="web_1",
            content="完整的公开 RAG 评估实践",
            score=1.0,
            source="web_search",
            metadata={"url": "https://example.com/rag"},
        )
        return ToolExecutionResult(
            tool_output={"result_count": 1, "top_urls": ["https://example.com/rag"]},
            evidence=[{"id": "web_1", "source": "web_search"}],
            context_docs=[doc],
        )


class ParallelResearchToolLoop(LoopResearchToolLoop):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started = 0
        self.both_started = asyncio.Event()
        self.web_finished = asyncio.Event()

    async def _select_tool_for_sub_question(self, *args, **kwargs):
        if kwargs.get("current_tool_calls"):
            return []
        return [
            {
                "call_id": "parallel_knowledge",
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "internal"},
            },
            {
                "call_id": "parallel_web",
                "selected_tool": "web_search",
                "tool_input": {"query": "external"},
            },
        ]

    async def _run_task_tool_for_sub_question(self, *args, **kwargs):
        self.started += 1
        if self.started == 2:
            self.both_started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=1)
        if kwargs["selected_tool"] == "web_search":
            self.web_finished.set()
            raise RuntimeError("parallel web failed")
        await asyncio.wait_for(self.web_finished.wait(), timeout=1)
        doc = RetrievedDoc(
            id="parallel_doc",
            content="parallel full context",
            score=0.9,
            source="knowledge_retrieval",
        )
        return ToolExecutionResult(
            tool_output={"doc_count": 1},
            evidence=[{"id": "parallel_doc", "source": "knowledge_retrieval"}],
            context_docs=[doc],
        )


class ParallelMcpFetchResearchToolLoop(LoopResearchToolLoop):
    """模拟模型同轮读取两个独立 URL，验证 Fetch 进入并行安全白名单。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started = 0
        self.both_started = asyncio.Event()

    async def _build_available_task_tools(self, *args, **kwargs):
        async def fetch(url: str) -> str:
            return url

        return [
            StructuredTool.from_function(
                coroutine=fetch,
                name=tool_loop_module.MCP_FETCH_TOOL_NAME,
                description="读取公开网页正文。",
            )
        ]

    async def _select_tool_for_sub_question(self, *args, **kwargs):
        if kwargs.get("current_tool_calls"):
            return []
        return [
            {
                "call_id": "fetch_a",
                "selected_tool": tool_loop_module.MCP_FETCH_TOOL_NAME,
                "tool_input": {"url": "https://example.com/a"},
            },
            {
                "call_id": "fetch_b",
                "selected_tool": tool_loop_module.MCP_FETCH_TOOL_NAME,
                "tool_input": {"url": "https://example.com/b"},
            },
        ]

    async def _run_task_tool_for_sub_question(self, *args, **kwargs):
        self.started += 1
        call_number = self.started
        if self.started == 2:
            self.both_started.set()
        await asyncio.wait_for(self.both_started.wait(), timeout=1)

        url = str(kwargs["tool_input"]["url"])
        doc = RetrievedDoc(
            id=f"fetch_{call_number}",
            content=f"fetched content: {url}",
            score=1.0,
            source=tool_loop_module.MCP_FETCH_TOOL_NAME,
            metadata={"url": url},
        )
        return ToolExecutionResult(
            tool_output={
                "content_length": len(doc.content),
                "content_preview": doc.content,
            },
            evidence=[
                {
                    "id": doc.id,
                    "source": tool_loop_module.MCP_FETCH_TOOL_NAME,
                    "metadata": {"url": url},
                }
            ],
            context_docs=[doc],
        )


class BudgetTrimmingResearchToolLoop(LoopResearchToolLoop):
    """模拟 LLM 在仅剩一次预算时仍返回两个候选 ToolCall。"""

    async def _select_tool_for_sub_question(self, *args, **kwargs):
        return [
            {
                "call_id": "within_budget",
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "first"},
            },
            {
                "call_id": "over_budget",
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "second"},
            },
        ]


class CorrectionResearchToolLoop(ResearchToolLoop):
    """让 Worker 连续执行两次本地检索，记录第二次收到的纠正上下文。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.attempt_starts: list[dict[str, Any]] = []

    async def _select_tool_for_sub_question(self, *args, **kwargs):
        if kwargs.get("current_tool_calls"):
            return {"selected_tool": "none", "tool_input": {}}
        missing = list(kwargs.get("retry_missing_points") or [])
        self.attempt_starts.append(
            {
                "prior_call_count": len(kwargs.get("prior_tool_calls") or []),
                "prior_evidence_count": len(kwargs.get("prior_evidence") or []),
                "missing_points": missing,
            }
        )
        return {
            "selected_tool": "knowledge_retrieval",
            "tool_input": {
                "query": "补充边界条件的纠正检索" if missing else "初始本地检索"
            },
        }

    async def _run_knowledge_retrieval_for_sub_question(self, *args, **kwargs):
        query = str(kwargs["tool_input"]["query"])
        doc_id = "corrected_doc" if "纠正" in query else "initial_doc"
        doc = RetrievedDoc(
            id=doc_id,
            content=f"完整证据：{query}",
            score=0.9,
            source="knowledge_retrieval",
        )
        return ToolExecutionResult(
            tool_output={"doc_count": 1, "top_doc_ids": [doc_id]},
            evidence=[{"id": doc_id, "source": "knowledge_retrieval"}],
            context_docs=[doc],
        )


class RetryLocalOnceEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ResearchEvidenceEvaluation(
                verdict="insufficient",
                confidence=0.9,
                relevance=0.8,
                coverage=0.4,
                authority=0.8,
                missing_points=["补充边界条件"],
                recommended_action="rewrite_local_query",
                reason="需要补充本地证据。",
            )
        return ResearchEvidenceEvaluation(
            verdict="sufficient",
            confidence=0.9,
            relevance=0.9,
            coverage=0.9,
            authority=0.9,
            recommended_action="accept",
            reason="累计证据已经充分。",
        )


def build_plan(task_plan_id: str) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="question_decomposition",
        user_id="tool_manager",
        original_query="分析 RAG 系统质量改进路径",
        objective="按子问题收集证据并综合回答",
        task_type="analysis",
        goal="按子问题收集证据并综合回答",
        sub_questions=[
            AgentTaskSubQuestion(
                sub_question_id="sq_loop",
                order=1,
                question="RAG 质量改进需要哪些内部证据和外部实践？",
                purpose="验证一个子问题多轮调用不同工具。",
                depends_on=[],
                information_source_hint="knowledge_retrieval",
                reason="复杂问题需要多来源证据。",
                expected_evidence="内部文档和公开资料。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_limit",
                order=2,
                question="工具循环达到上限后应如何停止？",
                purpose="验证 AGENT_MAX_TOOL_CALLS 生效。",
                depends_on=[],
                information_source_hint="knowledge_retrieval",
                reason="避免无限工具调用。",
                expected_evidence="工具调用轨迹。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_unknown",
                order=3,
                question="未知工具是否会被执行？",
                purpose="验证工具白名单。",
                depends_on=[],
                information_source_hint="none",
                reason="LLM 不能凭空调用工具。",
                expected_evidence="失败轨迹。",
            ),
        ],
        research_policy=AgentResearchPolicy(web_policy="required"),
        final_synthesis_instruction="综合所有成功子问题答案。",
        source_query="RAG 质量 改进",
        target_path=None,
        steps=[],
        created_at=now,
        updated_at=now,
    )


def build_user() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="tool_manager",
        is_authenticated=True,
        auth_source="jwt",
    )


class ResearchHarness:
    """测试组合根：私有 Tool Loop 测试不再穿过统一 Executor。"""

    def __init__(self, *, tool_loop_class=LoopResearchToolLoop, **kwargs) -> None:
        settings = kwargs["settings"]
        self.tool_loop = tool_loop_class(
            settings=settings,
            vector_retriever=kwargs["vector_retriever"],
            keyword_retriever=kwargs["keyword_retriever"],
            llm_client=kwargs["llm_client"],
        )
        worker = ResearchWorkerAgent(
            settings,
            self.tool_loop,
            ResearchEvidenceEvaluator(settings),
        )
        research = AgenticResearchExecutor(
            settings,
            kwargs["llm_client"],
            kwargs["task_plan_store"],
            worker,
        )
        self.executor = AgentTaskExecutor(**kwargs, research_executor=research)

    def __getattr__(self, name):
        if hasattr(self.tool_loop, name):
            return getattr(self.tool_loop, name)
        return getattr(self.executor, name)


def build_executor(settings: Settings, store: AgentTaskPlanStore) -> ResearchHarness:
    return ResearchHarness(
        settings=settings,
        vector_retriever=FakeRetriever(),
        keyword_retriever=FakeRetriever(),
        llm_client=FakeLLM(),
        document_management_service=object(),
        tool_permission_service=object(),
        tool_audit_service=object(),
        task_plan_store=store,
    )


async def main() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            OPENAI_API_KEY="",
            BOCHA_API_KEY="fake",
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_MAX_TOOL_CALLS=2,
            AGENT_RESEARCH_MAX_TOOL_CALLS_PER_WORKER=2,
        )
        store = AgentTaskPlanStore(settings=settings)
        executor = build_executor(settings, store)

        class FakeBoundBatchModel:
            async def ainvoke(self, messages, config=None):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "native_a",
                            "name": "knowledge_retrieval",
                            "args": {"query": "a"},
                            "type": "tool_call",
                        },
                        {
                            "id": "native_b",
                            "name": "web_search",
                            "args": {"query": "b"},
                            "type": "tool_call",
                        },
                    ],
                )

        class FakeChatOpenAI:
            def __init__(self, **kwargs):
                pass

            def bind_tools(self, tools, **kwargs):
                assert kwargs["parallel_tool_calls"] is True
                return FakeBoundBatchModel()

        original_chat_openai = tool_loop_module.ChatOpenAI
        tool_loop_module.ChatOpenAI = FakeChatOpenAI
        try:
            native_calls = await executor._select_tool_with_bound_tools(
                tools=await executor._build_available_task_tools(),
                plan=build_plan("task_plan_native_batch"),
                sub_question=build_plan("task_plan_native_batch").sub_questions[0],
                dependency_results=[],
                prior_tool_calls=[],
                prior_evidence=[],
                current_tool_calls=[],
                current_evidence=[],
                retry_missing_points=[],
            )
        finally:
            tool_loop_module.ChatOpenAI = original_chat_openai
        assert native_calls is not None
        assert [call["call_id"] for call in native_calls] == ["native_a", "native_b"]

        class RequiredWebModel:
            async def ainvoke(self, messages, config=None):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "required_web",
                            "name": "web_search",
                            "args": {"query": "FastAPI deployment"},
                            "type": "tool_call",
                        }
                    ],
                )

        class RequiredWebChatOpenAI:
            def __init__(self, **kwargs):
                pass

            def bind_tools(self, tools, **kwargs):
                assert [tool.name for tool in tools] == ["web_search"]
                assert kwargs == {
                    "parallel_tool_calls": False,
                    "tool_choice": "web_search",
                }
                return RequiredWebModel()

        web_sub_question = AgentTaskSubQuestion(
            sub_question_id="sq_web",
            order=1,
            question="请联网搜索 FastAPI 部署建议",
            purpose="验证原生 Web Search ToolCall。",
            information_source_hint="web_search",
            reason="用户明确要求联网搜索。",
        )
        required_executor = ResearchToolLoop(
            settings=Settings(
                OPENAI_API_KEY="fake-key",
                BOCHA_API_KEY="fake",
                AGENT_TASK_PLAN_DIR=temp_dir,
            ),
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLM(),
        )
        tool_loop_module.ChatOpenAI = RequiredWebChatOpenAI
        try:
            required_web_calls = await required_executor._select_tool_for_sub_question(
                plan=build_plan("task_plan_required_web"),
                sub_question=web_sub_question,
                dependency_results=[],
                default_mode="hybrid",
                default_top_k=3,
                prior_tool_calls=[],
                prior_evidence=[],
                current_tool_calls=[],
                current_evidence=[],
                retry_missing_points=[],
            )
        finally:
            tool_loop_module.ChatOpenAI = original_chat_openai
        assert required_web_calls[0]["call_id"] == "required_web"
        assert required_web_calls[0]["selected_tool"] == "web_search"

        class FailingRequiredWebChatOpenAI:
            def __init__(self, **kwargs):
                pass

            def bind_tools(self, tools, **kwargs):
                raise RuntimeError("provider does not support required tool choice")

        tool_loop_module.ChatOpenAI = FailingRequiredWebChatOpenAI
        try:
            enforced_web_calls = await required_executor._select_tool_for_sub_question(
                plan=build_plan("task_plan_required_web_fallback"),
                sub_question=web_sub_question,
                dependency_results=[],
                default_mode="hybrid",
                default_top_k=3,
                prior_tool_calls=[],
                prior_evidence=[],
                current_tool_calls=[],
                current_evidence=[],
                retry_missing_points=[],
            )
        finally:
            tool_loop_module.ChatOpenAI = original_chat_openai
        assert enforced_web_calls == [
            {
                "selected_tool": "web_search",
                "tool_input": {
                    "query": web_sub_question.question,
                    "count": 3,
                },
                "reason": "server_enforced_required_web_policy",
            }
        ]

        # 同一 attempt 可以分两轮调用两个工具，但只能在所有工具结束后生成一次答案。
        sequential_llm = FakeLLM()
        sequential_loop = LoopResearchToolLoop(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=sequential_llm,
        )
        sequential_outcome = await sequential_loop.run_attempt(
            plan=build_plan("task_plan_single_answer"),
            sub_question=build_plan("task_plan_single_answer").sub_questions[0],
            dependency_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert len(sequential_outcome.result.tool_calls) == 2
        assert len(sequential_llm.generate_calls) == 1
        sequential_context = sequential_llm.generate_calls[0][1].context_text
        assert "完整的内部 RAG 设计证据" in sequential_context
        assert "完整的公开 RAG 评估实践" in sequential_context
        assert all(
            "answer" not in call.tool_output and "evidence" not in call.tool_output
            for call in sequential_outcome.result.tool_calls
        )

        # 未注册工具没有产生任何可用证据，因此不能浪费一次回答模型调用。
        calls_before_failure = len(sequential_llm.generate_calls)
        failed_outcome = await sequential_loop.run_attempt(
            plan=build_plan("task_plan_no_evidence"),
            sub_question=build_plan("task_plan_no_evidence").sub_questions[2],
            dependency_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert failed_outcome.result.status == "failed"
        assert len(sequential_llm.generate_calls) == calls_before_failure

        # Worker Graph 的纠正边必须把 attempt 1 的调用、证据、原文和缺失点传给 attempt 2。
        correction_llm = FakeLLM()
        correction_loop = CorrectionResearchToolLoop(
            settings=Settings(
                OPENAI_API_KEY="",
                AGENT_TASK_PLAN_DIR=temp_dir,
                AGENT_MAX_TOOL_CALLS=2,
                AGENT_RESEARCH_MAX_TOOL_CALLS_PER_WORKER=4,
                AGENT_RESEARCH_MAX_CORRECTION_ROUNDS=1,
            ),
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=correction_llm,
        )
        correction_worker = ResearchWorkerAgent(
            correction_loop._settings,
            correction_loop,
            RetryLocalOnceEvaluator(),
        )

        async def ignore_progress(*args, **kwargs):
            return None

        async def ignore_checkpoint(_update) -> None:
            return None

        correction_plan = build_plan("task_plan_cross_attempt")
        correction_result = await correction_worker.run(
            ResearchWorkerRequest(
                plan=correction_plan,
                sub_question=correction_plan.sub_questions[0],
                dependency_results=[],
                policy=AgentResearchPolicy(
                    mode="hybrid",
                    top_k=3,
                    min_score=0.0,
                    web_policy="disabled",
                ),
                filters=RetrievalFilters(),
                wave=1,
                on_progress=ignore_progress,
                on_checkpoint=ignore_checkpoint,
                should_stop=lambda: False,
            )
        )
        assert correction_result.status == "completed"
        assert correction_result.attempt_count == 2
        assert len(correction_llm.generate_calls) == 2
        assert correction_loop.attempt_starts == [
            {
                "prior_call_count": 0,
                "prior_evidence_count": 0,
                "missing_points": [],
            },
            {
                "prior_call_count": 1,
                "prior_evidence_count": 1,
                "missing_points": ["补充边界条件"],
            },
        ]
        second_context = correction_llm.generate_calls[1][1].context_text
        assert "完整证据：初始本地检索" in second_context
        assert "完整证据：补充边界条件的纠正检索" in second_context
        assert len({call.call_id for call in correction_result.tool_calls}) == 2
        assert "attempt_1" in correction_result.tool_calls[0].call_id
        assert "attempt_2" in correction_result.tool_calls[1].call_id

        parallel_llm = FakeLLM()
        parallel_executor = ResearchHarness(
            tool_loop_class=ParallelResearchToolLoop,
            settings=Settings(
                OPENAI_API_KEY="",
                BOCHA_API_KEY="fake",
                AGENT_TASK_PLAN_DIR=temp_dir,
                AGENT_MAX_TOOL_CALLS=12,
                AGENT_MAX_PARALLEL_TOOL_CALLS=4,
            ),
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=parallel_llm,
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
        )
        parallel_outcome = await parallel_executor.run_attempt(
            plan=build_plan("task_plan_parallel"),
            sub_question=build_plan("task_plan_parallel").sub_questions[0],
            dependency_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        parallel_result = parallel_outcome.result
        assert parallel_executor.started == 2
        assert [call.call_id for call in parallel_result.tool_calls] == [
            "sq_loop_attempt_1_parallel_knowledge",
            "sq_loop_attempt_1_parallel_web",
        ]
        assert [call.round for call in parallel_result.tool_calls] == [1, 1]
        assert [call.status for call in parallel_result.tool_calls] == [
            "completed",
            "failed",
        ]
        assert parallel_result.status == "completed"
        assert len(parallel_llm.generate_calls) == 1
        assert "parallel full context" in parallel_llm.generate_calls[0][1].context_text

        fetch_llm = FakeLLM()
        fetch_loop = ParallelMcpFetchResearchToolLoop(
            settings=Settings(
                OPENAI_API_KEY="",
                AGENT_TASK_PLAN_DIR=temp_dir,
                AGENT_MAX_TOOL_CALLS=4,
                AGENT_MAX_PARALLEL_TOOL_CALLS=4,
            ),
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=fetch_llm,
        )
        fetch_plan = build_plan("task_plan_parallel_mcp_fetch")
        checkpoint_updates = []

        async def record_checkpoint(update) -> None:
            checkpoint_updates.append(update)

        fetch_outcome = await fetch_loop.run_attempt(
            plan=fetch_plan,
            sub_question=fetch_plan.sub_questions[0],
            dependency_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
            on_checkpoint=record_checkpoint,
        )

        assert fetch_loop.started == 2
        assert [
            call.tool_name for call in fetch_outcome.result.tool_calls
        ] == ["mcp__fetch", "mcp__fetch"]
        assert [call.round for call in fetch_outcome.result.tool_calls] == [1, 1]
        assert all(
            call.status == "completed"
            for call in fetch_outcome.result.tool_calls
        )
        assert fetch_outcome.result.status == "completed"
        assert len(fetch_llm.generate_calls) == 1
        fetch_context = fetch_llm.generate_calls[0][1].context_text
        assert "https://example.com/a" in fetch_context
        assert "https://example.com/b" in fetch_context
        assert {
            item.tool_call.call_id.rsplit("_attempt_1_", 1)[-1]
            for item in checkpoint_updates
            if item.tool_call is not None
        } == {"fetch_a", "fetch_b"}

        # 只剩 1 次预算时不能因为 LLM 返回 2 个候选就整批拒绝；应稳定执行
        # 第一个合法调用，并保证实际 ToolCall 数不突破 Worker 预算。
        budget_llm = FakeLLM()
        budget_loop = BudgetTrimmingResearchToolLoop(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=budget_llm,
        )
        budget_outcome = await budget_loop.run_attempt(
            plan=build_plan("task_plan_budget_trim"),
            sub_question=build_plan("task_plan_budget_trim").sub_questions[0],
            dependency_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
            max_tool_calls_override=1,
        )
        assert budget_outcome.result.status == "completed"
        assert [call.call_id for call in budget_outcome.result.tool_calls] == [
            "sq_loop_attempt_1_within_budget"
        ]
        assert len(budget_llm.generate_calls) == 1

        server_path = ROOT / "scripts" / "mcp_demo_server.py"
        mcp_settings = Settings(
            OPENAI_API_KEY="",
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_TASK_MCP_ENABLED=True,
            AGENT_TASK_MCP_STDIO_SERVERS_JSON=json.dumps(
                [
                    {
                        "name": "demo",
                        "command": sys.executable,
                        "args": [str(server_path)],
                        "allowed_tool_names": ["add", "echo"],
                    }
                ]
            ),
        )
        mcp_store = AgentTaskPlanStore(settings=mcp_settings)
        mcp_executor = ResearchToolLoop(
            settings=mcp_settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLM(),
        )
        tools = await mcp_executor._build_available_task_tools()
        assert "mcp__add" in {tool.name for tool in tools}
        assert "mcp__echo" in {tool.name for tool in tools}
        mcp_llm = mcp_executor._llm_client
        before_mcp_llm_calls = len(mcp_llm.generate_calls)
        execution = await mcp_executor._run_task_tool_for_sub_question(
            selected_tool="mcp__add",
            tool_input={"a": 2, "b": 3},
            available_tools=tools,
            sub_question=build_plan("task_plan_202607080002_mcp").sub_questions[0],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert execution.tool_output["content_preview"] == "5"
        assert "content" not in execution.tool_output
        assert execution.context_docs[0].content == "5"
        assert execution.evidence[0]["source"] == "mcp__add"
        assert len(mcp_llm.generate_calls) == before_mcp_llm_calls

    print("agent_task_tool_loop=passed")


if __name__ == "__main__":
    asyncio.run(main())
