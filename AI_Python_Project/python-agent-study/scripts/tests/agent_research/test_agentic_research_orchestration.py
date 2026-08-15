"""ResearchTaskPlan v2 的波次并发、Registry 单写者和确认回归。"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "tests"))
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from agent_task_plan_test_support import (
    InMemoryAgentTaskLeaseManager,
    InMemoryAgentTaskPlanStore,
)

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentTaskPlanStatus,
    AgentTaskSubQuestionResult,
    AgentTaskToolCallTrace,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters
from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskExpectedEvidence,
    AgentTaskPlanQualityChecks,
    AgentTaskPlanQualityReview,
    AgentTaskRequirement,
    RequirementSourcePolicy,
    ResearchTaskPlan,
    ResearchTaskPolicy,
    ResearchTaskProgress,
    ResearchTaskSubQuestion,
    ResearchWorkerCheckpointUpdate,
    ResearchWorkerProgress,
    build_research_task_plan_public_view,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor


class FakeLLM(BaseLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, query: str, context: RagContext, **_: object) -> str:
        self.calls += 1
        return "最终综合：" + context.context_text

    async def stream(self, query: str, context: RagContext):
        yield await self.generate(query, context)


class SlowDerivedLLM(FakeLLM):
    async def generate(
        self,
        query: str,
        context: RagContext,
        **kwargs: object,
    ) -> str:
        if query.startswith("只基于依赖子问题结果完成综合"):
            await asyncio.Event().wait()
        return await super().generate(query, context, **kwargs)


class ControlledWorker:
    def __init__(self) -> None:
        self.fail_ids: set[str] = set()
        self.partial_ids: set[str] = set()
        self.started: dict[str, float] = {}
        self.finished: dict[str, float] = {}

    async def run(self, request) -> AgentTaskSubQuestionResult:
        item = request.sub_question
        self.started[item.sub_question_id] = perf_counter()
        await asyncio.sleep(0.06)
        self.finished[item.sub_question_id] = perf_counter()
        if item.sub_question_id in self.fail_ids:
            return AgentTaskSubQuestionResult(
                sub_question_id=item.sub_question_id,
                question=item.question,
                selected_tool="none",
                status="failed",
                answer="",
                error="SIMULATED_FAILURE",
            )
        if item.information_source_hint == "none":
            return AgentTaskSubQuestionResult(
                sub_question_id=item.sub_question_id,
                question=item.question,
                selected_tool="none",
                status="completed",
                answer="derived answer",
            )
        tool_name = item.information_source_hint
        call_id = f"{item.sub_question_id}_call"
        status = (
            "partial"
            if item.sub_question_id in self.partial_ids
            else "completed"
        )
        metadata = (
            {"url": "https://example.com/source"}
            if tool_name == "web_search"
            else {}
        )
        return AgentTaskSubQuestionResult(
            sub_question_id=item.sub_question_id,
            question=item.question,
            selected_tool=tool_name,
            status=status,
            answer=f"answer:{item.sub_question_id}",
            evaluation=(
                ResearchEvidenceEvaluation(
                    verdict="partial",
                    confidence=0.9,
                    relevance=0.9,
                    coverage=0.5,
                    authority=0.8,
                    missing_points=["缺少完整证据"],
                    recommended_action="stop_with_limitation",
                    reason="测试 partial 依赖传播。",
                )
                if status == "partial"
                else None
            ),
            tool_calls=[
                AgentTaskToolCallTrace(
                    call_id=call_id,
                    round=1,
                    tool_name=tool_name,
                    status="completed",
                    reason="test",
                )
            ],
            evidence=[
                {
                    "id": f"doc:{item.sub_question_id}",
                    "source": tool_name,
                    "metadata": metadata,
                    "content_preview": item.question,
                    "tool_call_id": call_id,
                }
            ],
        )


class CheckpointingTimeoutWorker:
    async def run(self, request) -> AgentTaskSubQuestionResult:
        call = AgentTaskToolCallTrace(
            call_id="sq_timeout_attempt_1_fetch_a",
            round=1,
            tool_name="knowledge_retrieval",
            status="completed",
            reason="timeout checkpoint test",
        )
        await request.on_checkpoint(
            ResearchWorkerCheckpointUpdate(
                stage="tool_execution",
                attempt=1,
                operation="knowledge_retrieval",
                operation_status="finished",
                tool_call=call,
                evidence=[
                    {
                        "id": "checkpoint_evidence",
                        "source": "knowledge_retrieval",
                        "tool_call_id": call.call_id,
                    }
                ],
            )
        )
        await request.on_checkpoint(
            ResearchWorkerCheckpointUpdate(
                stage="evidence_evaluation",
                attempt=1,
                operation="evidence_evaluator",
                operation_status="started",
            )
        )
        await asyncio.Event().wait()
        raise AssertionError("timeout worker should have been cancelled")


class FakeCapabilityService:
    def __init__(self, capability: AgentTaskCapabilitySnapshot) -> None:
        self.capability = capability
        self.calls = 0

    async def resolve_research(self, **_: object) -> AgentTaskCapabilitySnapshot:
        self.calls += 1
        return self.capability


def requirement(item_id: str, source: str, *, mode: str = "all_of", completion: str = "strict"):
    evidence_type = {
        "knowledge_retrieval": "knowledge_chunk",
        "web_search": "web_citation",
        "none": "derived_synthesis",
    }[source]
    return AgentTaskRequirement(
        requirement_id=item_id,
        description=item_id,
        source_policy=RequirementSourcePolicy(
            mode="none" if source == "none" else mode,
            source_types=[] if source == "none" else [source],
        ),
        expected_evidence=[
            AgentTaskExpectedEvidence(
                evidence_type=evidence_type,
                minimum_count=1,
                requires_query_id=False,
            )
        ],
        completion_policy=completion,
    )


def question(item_id: str, order: int, hint: str, covers: list[str], depends_on=None):
    return ResearchTaskSubQuestion(
        sub_question_id=item_id,
        order=order,
        question=f"question:{item_id}",
        purpose="test",
        depends_on=depends_on or [],
        information_source_hint=hint,
        covers_requirement_ids=covers,
        reason="test",
        web_usage="direct" if hint == "web_search" else "not_used",
    )


def plan(item_id: str, requirements, sub_questions) -> ResearchTaskPlan:
    now = datetime.now(UTC)
    capability = AgentTaskCapabilitySnapshot(
        available_source_types=["knowledge_retrieval", "web_search"],
        web_direct_allowed=True,
        web_fallback_allowed=False,
        knowledge_retrieval_available=True,
        nl2sql_query_available=False,
        max_requirements=10,
        max_sub_questions=8,
    )
    return ResearchTaskPlan(
        task_plan_id=item_id,
        user_id="u1",
        original_query="complex question",
        source_query="complex question",
        objective="complex question",
        final_synthesis_instruction="evidence only",
        requirements=requirements,
        sub_questions=sub_questions,
        quality_review=AgentTaskPlanQualityReview(
            verdict="accepted",
            checks=AgentTaskPlanQualityChecks(
                requirement_coverage="pass",
                source_alignment="pass",
                semantic_alignment="pass",
                dependency_quality="pass",
                executability="pass",
                completion_policy_alignment="pass",
            ),
            revision_count=0,
        ),
        capability_snapshot=capability,
        research_policy=ResearchTaskPolicy(
            mode="keyword",
            top_k=3,
            min_score=0.0,
            allow_direct_web=True,
            allow_web_fallback=False,
        ),
        progress=ResearchTaskProgress(
            workers={item.sub_question_id: ResearchWorkerProgress() for item in sub_questions}
        ),
        status="waiting_confirmation",
        created_at=now,
        updated_at=now,
    )


async def main() -> None:
    with TemporaryDirectory() as directory:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=directory,
            AGENT_RESEARCH_MAX_PARALLEL_WORKERS=4,
        )
        store = InMemoryAgentTaskPlanStore()
        worker = ControlledWorker()
        llm = FakeLLM()
        research = AgenticResearchExecutor(settings, llm, store, worker)
        capability = AgentTaskCapabilitySnapshot(
            available_source_types=["knowledge_retrieval", "web_search"],
            web_direct_allowed=True,
            web_fallback_allowed=False,
            knowledge_retrieval_available=True,
            nl2sql_query_available=False,
            max_requirements=10,
            max_sub_questions=8,
        )
        capability_service = FakeCapabilityService(capability)
        executor = AgentTaskExecutor(
            settings=settings,
            vector_retriever=object(),
            keyword_retriever=object(),
            llm_client=llm,
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
            lease_manager=InMemoryAgentTaskLeaseManager(),
            research_executor=research,
            document_executor=object(),
            capability_service=capability_service,
        )
        user = CurrentUserContext(
            user_id="u1",
            is_authenticated=True,
            auth_source="jwt",
        )

        parallel = plan(
            "task_plan_202608020001_parallel",
            [
                requirement("req_a", "knowledge_retrieval"),
                requirement("req_b", "knowledge_retrieval"),
                requirement("req_c", "none"),
            ],
            [
                question("sq_1", 1, "knowledge_retrieval", ["req_a"]),
                question("sq_2", 2, "knowledge_retrieval", ["req_b"]),
                question("sq_3", 3, "none", ["req_c"], ["sq_1", "sq_2"]),
            ],
        )
        started = perf_counter()
        completed = await executor.execute_question_decomposition_plan(
            plan=parallel,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert completed.status == AgentTaskPlanStatus.COMPLETED
        assert perf_counter() - started < 1.0
        assert worker.started["sq_2"] < worker.finished["sq_1"]
        assert all(item.status == "satisfied" for item in completed.requirement_evidence_statuses)
        assert len(completed.evidence_registry.evidence_by_id) == 3
        assert completed.final_output is not None

        # strict Requirement 失败时不调用 Final Synthesis。
        strict_failure = plan(
            "task_plan_202608020002_strict",
            [requirement("req_a", "knowledge_retrieval")],
            [question("sq_1", 1, "knowledge_retrieval", ["req_a"])],
        )
        worker.fail_ids = {"sq_1"}
        failed = await executor.execute_question_decomposition_plan(
            plan=strict_failure,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert failed.status == AgentTaskPlanStatus.FAILED
        assert failed.final_output is None

        worker.fail_ids.clear()
        worker.partial_ids = {"sq_1"}
        partial_dependency_plan = plan(
            "task_plan_202608020002_partial_dependency",
            [
                requirement(
                    "req_a",
                    "knowledge_retrieval",
                    completion="allow_partial",
                ),
                requirement("req_b", "none"),
            ],
            [
                question(
                    "sq_1",
                    1,
                    "knowledge_retrieval",
                    ["req_a"],
                ),
                question(
                    "sq_2",
                    2,
                    "none",
                    ["req_b"],
                    ["sq_1"],
                ),
            ],
        )
        partial_dependency_result = (
            await executor.execute_question_decomposition_plan(
                plan=partial_dependency_plan,
                user=user,
                mode="keyword",
                top_k=3,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(),
            )
        )
        result_by_id = {
            item.sub_question_id: item
            for item in partial_dependency_result.sub_question_results
        }
        requirement_by_id = {
            item.requirement_id: item
            for item in partial_dependency_result.requirement_evidence_statuses
        }

        assert partial_dependency_result.status == AgentTaskPlanStatus.FAILED
        assert result_by_id["sq_1"].status == "partial"
        assert result_by_id["sq_1"].evaluation is not None
        assert result_by_id["sq_1"].evaluation.verdict == "partial"
        assert result_by_id["sq_2"].status == "partial"
        assert requirement_by_id["req_a"].status == "partially_satisfied"
        assert requirement_by_id["req_b"].status == "failed"
        assert partial_dependency_result.final_output is None
        worker.partial_ids.clear()

        # allow_partial 只有“已有合法部分证据”时才成立；failed 仍禁止最终综合。
        worker.fail_ids = {"sq_1"}
        synthesis_calls = llm.calls
        partial_without_evidence = plan(
            "task_plan_202608020002_partial_failed",
            [requirement("req_a", "knowledge_retrieval", completion="allow_partial")],
            [question("sq_1", 1, "knowledge_retrieval", ["req_a"])],
        )
        partial_failed = await executor.execute_question_decomposition_plan(
            plan=partial_without_evidence,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert partial_failed.status == AgentTaskPlanStatus.FAILED
        assert partial_failed.final_output is None
        assert llm.calls == synthesis_calls

        timeout_settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=directory,
            AGENT_RESEARCH_MAX_PARALLEL_WORKERS=2,
            AGENT_RESEARCH_WORKER_TIMEOUT_SECONDS=0.2,
        )
        timeout_store = InMemoryAgentTaskPlanStore()
        timeout_executor = AgenticResearchExecutor(
            timeout_settings,
            FakeLLM(),
            timeout_store,
            CheckpointingTimeoutWorker(),
        )
        timeout_plan = plan(
            "task_plan_202608100001_worker_timeout",
            [requirement("req_timeout", "knowledge_retrieval")],
            [question("sq_timeout", 1, "knowledge_retrieval", ["req_timeout"])],
        )
        timeout_result = await timeout_executor.execute_question_decomposition_plan(
            plan=timeout_plan,
            user=user,
            mode="keyword",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        timeout_sub_result = timeout_result.sub_question_results[0]
        timeout_checkpoint = timeout_result.worker_checkpoints["sq_timeout"]
        assert timeout_sub_result.error_code == "WORKER_TIMEOUT"
        assert timeout_sub_result.attempt_count == 1
        assert [item.call_id for item in timeout_sub_result.tool_calls] == [
            "sq_timeout_attempt_1_fetch_a"
        ]
        assert timeout_checkpoint.stage == "evidence_evaluation"
        assert timeout_checkpoint.active_operations == ["evidence_evaluator"]
        assert len(timeout_checkpoint.tool_calls) == 1
        assert len(timeout_checkpoint.evidence) == 1
        assert timeout_result.evidence_registry.evidence_by_id == {}
        timeout_public = build_research_task_plan_public_view(timeout_result).model_dump(
            mode="json"
        )
        assert "worker_checkpoints" not in timeout_public
        timeout_worker_progress = timeout_result.progress.workers["sq_timeout"]
        assert timeout_worker_progress.stage == "evidence_evaluation"
        assert timeout_worker_progress.active_operations == ["evidence_evaluator"]
        assert timeout_worker_progress.tool_call_count == 1
        assert timeout_worker_progress.evidence_count == 1
        assert any(
            event.event == "agent_task_research_worker_timed_out"
            and event.sub_question_id == "sq_timeout"
            and event.stage == "evidence_evaluation"
            for event in timeout_result.progress.events
        )

        derived_timeout_settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="",
            LANGSMITH_TRACING=False,
            AGENT_TASK_PLAN_DIR=directory,
            AGENT_RESEARCH_MAX_PARALLEL_WORKERS=2,
            AGENT_RESEARCH_WORKER_TIMEOUT_SECONDS=0.2,
        )
        derived_timeout_store = InMemoryAgentTaskPlanStore()
        derived_timeout_executor = AgenticResearchExecutor(
            derived_timeout_settings,
            SlowDerivedLLM(),
            derived_timeout_store,
            ControlledWorker(),
        )
        derived_timeout_plan = plan(
            "task_plan_202608100001_derived_timeout",
            [
                requirement("req_source", "knowledge_retrieval"),
                requirement("req_derived", "none"),
            ],
            [
                question("sq_source", 1, "knowledge_retrieval", ["req_source"]),
                question(
                    "sq_derived",
                    2,
                    "none",
                    ["req_derived"],
                    ["sq_source"],
                ),
            ],
        )
        derived_timeout_result = (
            await derived_timeout_executor.execute_question_decomposition_plan(
                plan=derived_timeout_plan,
                user=user,
                mode="keyword",
                top_k=3,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(),
            )
        )
        derived_result_by_id = {
            item.sub_question_id: item
            for item in derived_timeout_result.sub_question_results
        }
        assert derived_result_by_id["sq_source"].status == "completed"
        assert derived_result_by_id["sq_derived"].status == "failed"
        assert derived_result_by_id["sq_derived"].error_code == "WORKER_TIMEOUT"
        assert derived_result_by_id["sq_derived"].attempt_count == 1
        derived_checkpoint = derived_timeout_result.worker_checkpoints["sq_derived"]
        assert derived_checkpoint.stage == "answer_generation"
        assert derived_checkpoint.active_operations == ["derived_synthesis"]
        assert any(
            event.event == "agent_task_research_worker_timed_out"
            and event.sub_question_id == "sq_derived"
            and event.stage == "answer_generation"
            for event in derived_timeout_result.progress.events
        )
        assert derived_timeout_result.status == AgentTaskPlanStatus.FAILED
        assert derived_timeout_result.final_output is None

        # waiting_confirmation 在锁内重载后重新解析当前能力，再启动 Worker。
        worker.fail_ids.clear()
        confirmable = plan(
            "task_plan_202608020003_confirm",
            [requirement("req_a", "knowledge_retrieval")],
            [question("sq_1", 1, "knowledge_retrieval", ["req_a"])],
        )
        await store.create(confirmable)
        confirmed = await executor.confirm(
            confirmable.task_plan_id,
            user=user,
            idempotency_key="confirm-research-orchestration",
        )
        assert confirmed.status == AgentTaskPlanStatus.COMPLETED
        assert capability_service.calls == 1

    print("agentic_research_orchestration=passed")


if __name__ == "__main__":
    asyncio.run(main())
