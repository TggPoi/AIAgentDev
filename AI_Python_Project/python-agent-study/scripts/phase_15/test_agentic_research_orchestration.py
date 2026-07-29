from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskSubQuestion,
    AgentTaskSubQuestionResult,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.research.agentic_research_graph import validate_research_dependencies
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagRetrievalFilters
from fast_app.services.agent_tasks.agent_task_executor import (
    AgentTaskExecutor,
    AgentTaskPlanStore,
    _build_public_web_query,
)
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import ResearchAttemptOutcome, ResearchToolLoop
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent
from fast_app.api.agent_task_plan_routes import _task_plan_progress_events
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner


class UnusedRetriever(BaseRetriever):
    async def retrieve(self, query: str, options: RetrievalOptions):
        return []


class FakeLLM(BaseLLMClient):
    async def generate(self, query: str, context: RagContext, **kwargs) -> str:
        return f"综合回答: {query}"

    async def stream(self, query: str, context: RagContext):
        yield await self.generate(query, context)


class ControlledResearchToolLoop(ResearchToolLoop):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_ids: set[str] = set()
        self.started: list[tuple[str, float]] = []
        self.finished: list[tuple[str, float]] = []
        self.received: list[dict[str, object]] = []

    async def run_attempt(self, *args, **kwargs):
        item = kwargs["sub_question"]
        self.received.append(
            {
                "id": item.sub_question_id,
                "mode": kwargs["mode"],
                "top_k": kwargs["top_k"],
                "filters": kwargs["filters"],
                "allow_web_search": kwargs["allow_web_search"],
            }
        )
        self.started.append((item.sub_question_id, perf_counter()))
        await asyncio.sleep(0.08)
        self.finished.append((item.sub_question_id, perf_counter()))
        if item.sub_question_id in self.fail_ids:
            return ResearchAttemptOutcome(
                result=AgentTaskSubQuestionResult(
                    sub_question_id=item.sub_question_id,
                    question=item.question,
                    selected_tool="knowledge_retrieval",
                    status="failed",
                    error="simulated retrieval failure",
                ),
                context_doc_groups=[],
            )
        return ResearchAttemptOutcome(
            result=AgentTaskSubQuestionResult(
                sub_question_id=item.sub_question_id,
                question=item.question,
                selected_tool="knowledge_retrieval",
                answer=f"answer:{item.sub_question_id}",
                evidence=[
                    {
                        "id": f"doc:{item.sub_question_id}",
                        "source": "knowledge_retrieval",
                        "content_preview": item.question,
                    }
                ],
                status="completed",
            ),
            context_doc_groups=[],
        )


class ControlledResearchExecutor:
    """以组合方式注入可控 Tool Loop，不再继承统一入口覆盖私有方法。"""

    def __init__(self, **kwargs) -> None:
        settings = kwargs["settings"]
        evaluator = kwargs.pop("evidence_evaluator", None) or ResearchEvidenceEvaluator(
            settings
        )
        self.tool_loop = ControlledResearchToolLoop(
            settings=settings,
            vector_retriever=kwargs["vector_retriever"],
            keyword_retriever=kwargs["keyword_retriever"],
            llm_client=kwargs["llm_client"],
        )
        worker = ResearchWorkerAgent(settings, self.tool_loop, evaluator)
        research = AgenticResearchExecutor(
            settings,
            kwargs["llm_client"],
            kwargs["task_plan_store"],
            worker,
        )
        self._executor = AgentTaskExecutor(
            **kwargs,
            research_executor=research,
        )

    def __getattr__(self, name):
        return getattr(self._executor, name)

    @property
    def fail_ids(self):
        return self.tool_loop.fail_ids

    @fail_ids.setter
    def fail_ids(self, value):
        self.tool_loop.fail_ids = value

    @property
    def started(self):
        return self.tool_loop.started

    @property
    def finished(self):
        return self.tool_loop.finished

    @property
    def received(self):
        return self.tool_loop.received


class SearchWebThenAcceptEvaluator:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def evaluate(self, *, sub_question, answer, evidence, langchain_config=None):
        count = self.counts.get(sub_question.sub_question_id, 0) + 1
        self.counts[sub_question.sub_question_id] = count
        if count == 1:
            return ResearchEvidenceEvaluation(
                verdict="insufficient",
                confidence=0.9,
                relevance=0.8,
                coverage=0.4,
                authority=0.6,
                missing_points=["公开资料"],
                recommended_action="search_web",
                reason="需要公开资料补充。",
            )
        return ResearchEvidenceEvaluation(
            verdict="sufficient",
            confidence=0.9,
            relevance=0.9,
            coverage=0.9,
            authority=0.8,
            recommended_action="accept",
            reason="证据已补齐。",
        )


class FailingEvaluator:
    async def evaluate(self, **kwargs):
        raise RuntimeError("simulated evaluator outage")


def question(item_id: str, order: int, depends_on: list[str] | None = None):
    return AgentTaskSubQuestion(
        sub_question_id=item_id,
        order=order,
        question=f"question:{item_id}",
        purpose="test",
        depends_on=depends_on or [],
        information_source_hint="knowledge_retrieval",
        reason="test",
        expected_evidence="document",
    )


def plan(item_id: str, sub_questions: list[AgentTaskSubQuestion]) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=item_id,
        task_kind="question_decomposition",
        user_id="u1",
        original_query="complex question",
        objective="research",
        task_type="analysis",
        goal="research",
        sub_questions=sub_questions,
        research_policy=AgentResearchPolicy(
            mode="keyword",
            top_k=3,
            source_path="docs/only.md",
        ),
        final_synthesis_instruction="synthesize",
        source_query="complex",
        steps=[],
        created_at=now,
        updated_at=now,
    )


def assert_invalid_dependencies() -> None:
    invalid_cases = [
        [question("a", 1), question("a", 2)],
        [question("a", 1, ["missing"])],
        [question("a", 1, ["a"])],
        [question("a", 1, ["b"]), question("b", 2, ["a"])],
    ]
    for case in invalid_cases:
        try:
            validate_research_dependencies(case)
        except ValueError:
            continue
        raise AssertionError(f"非法依赖图未被拒绝: {case}")


async def main() -> None:
    assert_invalid_dependencies()
    public_query = _build_public_web_query(
        r"查询 AST-0002 和 D:\knowledge\secret.md user_id=u1",
        "公开方案是什么？",
        ["allowed_departments=game"],
    )
    assert "AST-0002" not in public_query
    assert "secret.md" not in public_query
    assert "user_id" not in public_query
    assert "allowed_departments" not in public_query
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_RESEARCH_MAX_PARALLEL_WORKERS=4,
            AGENT_RESEARCH_MAX_CORRECTION_ROUNDS=0,
        )
        store = AgentTaskPlanStore(settings)
        request = RagChatRequest(
            query="complex",
            mode="keyword",
            top_k=3,
            filters=RagRetrievalFilters(source_path="docs/only.md"),
            allow_web_fallback=True,
        )
        initial_state = build_rag_agent_initial_state(request, operation="run")
        assert initial_state["allow_web_fallback"] is True
        frozen_policy = AgentResearchPolicy(
            mode="keyword",
            top_k=3,
            source_path="docs/only.md",
            web_policy="fallback",
        )
        planned = await AgentTaskPlanner(settings).plan_question_decomposition(
            query="A 与 B 有什么差异？",
            user_id="u1",
            research_policy=frozen_policy,
        )
        assert planned.research_policy == frozen_policy
        executor = ControlledResearchExecutor(
            settings=settings,
            vector_retriever=UnusedRetriever(),
            keyword_retriever=UnusedRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
        )
        user = CurrentUserContext(
            user_id="u1",
            is_authenticated=True,
            auth_source="jwt",
            department_codes=["game"],
        )

        parallel_plan = plan(
            "task_plan_202607160001_parallel",
            [question("a", 1), question("b", 2), question("c", 3, ["a", "b"])],
        )
        started = perf_counter()
        parallel_result = await executor.execute_question_decomposition_plan(
            plan=parallel_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        elapsed = perf_counter() - started
        assert parallel_result.status == AgentTaskPlanStatus.COMPLETED
        assert elapsed < 0.32, elapsed
        starts = dict(executor.started)
        finishes = dict(executor.finished)
        assert starts["b"] < finishes["a"] and starts["a"] < finishes["b"]
        assert [item["sub_question_id"] for item in parallel_result.final_output["sub_question_results"]] == ["a", "b", "c"]

        warning_plan = plan(
            "task_plan_202607160002_warning",
            [
                question("ok", 1),
                question("bad", 2),
                question("after_ok", 3, ["ok"]),
                question("after_bad", 4, ["bad"]),
            ],
        )
        executor.fail_ids = {"bad"}
        warning_result = await executor.execute_question_decomposition_plan(
            plan=warning_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert warning_result.status == AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
        statuses = {
            item["sub_question_id"]: item["status"]
            for item in warning_result.final_output["sub_question_results"]
        }
        assert statuses == {
            "ok": "completed",
            "bad": "failed",
            "after_ok": "completed",
            "after_bad": "skipped",
        }
        assert warning_result.final_output["failed_sub_questions"] == ["bad"]
        assert warning_result.final_output["skipped_sub_questions"] == ["after_bad"]

        executor.fail_ids.clear()
        retry_result = await executor.resume(warning_result.task_plan_id, user=user)
        assert retry_result.status == AgentTaskPlanStatus.COMPLETED
        # completed 的 ok/after_ok 被保留，只重新执行 bad 和原先 skipped 的 after_bad。
        retry_ids = [item["id"] for item in executor.received[-2:]]
        assert retry_ids == ["bad", "after_bad"], retry_ids

        confirm_plan = plan(
            "task_plan_202607160003_policy",
            [question("policy", 1)],
        )
        confirm_plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
        store.save(confirm_plan)
        confirmed = await executor.confirm(confirm_plan.task_plan_id, user=user)
        assert confirmed.status == AgentTaskPlanStatus.COMPLETED
        received = executor.received[-1]
        assert received["mode"] == "keyword" and received["top_k"] == 3
        received_filters = received["filters"]
        assert received_filters.source_path == "docs/only.md"
        assert received_filters.department_codes == ["game"]

        saved = store.load(confirm_plan.task_plan_id)
        assert saved.research_policy is not None
        assert saved.research_policy.web_policy == "disabled"
        assert not list(Path(temp_dir).glob("*.tmp"))

        correction_settings = Settings(
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_RESEARCH_MAX_CORRECTION_ROUNDS=2,
        )
        correction_executor = ControlledResearchExecutor(
            settings=correction_settings,
            vector_retriever=UnusedRetriever(),
            keyword_retriever=UnusedRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
            evidence_evaluator=SearchWebThenAcceptEvaluator(),
        )
        fallback_plan = plan(
            "task_plan_202607160004_fallback",
            [question("fallback", 1)],
        )
        fallback_plan.research_policy = fallback_plan.research_policy.model_copy(
            update={"web_policy": "fallback"}
        )
        fallback_result = await correction_executor.execute_question_decomposition_plan(
            plan=fallback_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert fallback_result.status == AgentTaskPlanStatus.COMPLETED
        assert [item["allow_web_search"] for item in correction_executor.received] == [
            False,
            True,
        ]
        fallback_worker = fallback_result.final_output["sub_question_results"][0]
        assert fallback_worker["attempt_count"] == 2
        progress_names = [
            item["event"]
            for item in fallback_result.final_output["research_progress"]["events"]
        ]
        assert "agent_task_evidence_evaluated" in progress_names
        assert "agent_task_sub_question_retrying" in progress_names
        progress_events = _task_plan_progress_events(
            fallback_result, set(), set(), set()
        )
        progress_text = "".join(progress_events)
        assert "agent_task_research_wave_started" in progress_text
        assert "agent_task_evidence_evaluated" in progress_text
        assert "agent_task_sub_question_retrying" in progress_text

        disabled_plan = plan(
            "task_plan_202607160005_disabled",
            [question("disabled", 1)],
        )
        disabled_executor = ControlledResearchExecutor(
            settings=correction_settings,
            vector_retriever=UnusedRetriever(),
            keyword_retriever=UnusedRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
            evidence_evaluator=SearchWebThenAcceptEvaluator(),
        )
        disabled_result = await disabled_executor.execute_question_decomposition_plan(
            plan=disabled_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert disabled_result.status == AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
        assert len(disabled_executor.received) == 1
        assert disabled_result.final_output["warnings"] == [
            "证据不足，但本次请求未授权 WebSearch。"
        ]

        all_failed_plan = plan(
            "task_plan_202607160006_all_failed",
            [question("all_bad", 1)],
        )
        disabled_executor.fail_ids = {"all_bad"}
        all_failed = await disabled_executor.execute_question_decomposition_plan(
            plan=all_failed_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert all_failed.status == AgentTaskPlanStatus.FAILED
        assert "final_answer" not in all_failed.final_output

        evaluator_failure_executor = ControlledResearchExecutor(
            settings=correction_settings,
            vector_retriever=UnusedRetriever(),
            keyword_retriever=UnusedRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
            evidence_evaluator=FailingEvaluator(),
        )
        evaluator_partial = await evaluator_failure_executor.execute_question_decomposition_plan(
            plan=plan("task_plan_202607160006_evaluator_partial", [question("has_evidence", 1)]),
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        partial_result = evaluator_partial.final_output["sub_question_results"][0]
        assert evaluator_partial.status == AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
        assert partial_result["status"] == "partial"
        assert partial_result["warnings"] == ["Evaluator 不可用: RuntimeError"]

        evaluator_failure_executor.fail_ids = {"no_evidence"}
        evaluator_failed = await evaluator_failure_executor.execute_question_decomposition_plan(
            plan=plan("task_plan_202607160006_evaluator_failed", [question("no_evidence", 1)]),
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        failed_result = evaluator_failed.final_output["sub_question_results"][0]
        assert evaluator_failed.status == AgentTaskPlanStatus.FAILED
        assert failed_result["status"] == "failed"
        assert failed_result["warnings"] == ["Evaluator 不可用: RuntimeError"]

        timeout_settings = Settings(
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_RESEARCH_MAX_CORRECTION_ROUNDS=0,
            AGENT_RESEARCH_WORKER_TIMEOUT_SECONDS=0.02,
        )
        timeout_executor = ControlledResearchExecutor(
            settings=timeout_settings,
            vector_retriever=UnusedRetriever(),
            keyword_retriever=UnusedRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
        )
        timeout_result = await timeout_executor.execute_question_decomposition_plan(
            plan=plan("task_plan_202607160007_timeout", [question("slow", 1)]),
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert timeout_result.status == AgentTaskPlanStatus.FAILED
        assert timeout_result.final_output["sub_question_results"][0]["error"] == "WORKER_TIMEOUT"

    print("agentic_research_orchestration=passed")


if __name__ == "__main__":
    asyncio.run(main())
