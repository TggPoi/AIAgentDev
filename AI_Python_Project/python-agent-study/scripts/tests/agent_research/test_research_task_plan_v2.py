"""ResearchTaskPlan v2 的契约、证据聚合和公开视图回归。"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "tests"))

from agent_task_plan_test_support import InMemoryAgentTaskPlanStore

from pydantic import ValidationError

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import PermissionCode
from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskDatasetScope,
    AgentTaskEvidenceRef,
    AgentTaskEvidenceRegistry,
    AgentTaskExpectedEvidence,
    AgentTaskPlanningTurn,
    AgentTaskPlannerCandidate,
    AgentTaskPlanReviewDecision,
    AgentTaskPlanQualityChecks,
    AgentTaskPlanQualityReview,
    AgentTaskRequirement,
    AgentTaskSubQuestionEvidenceValidation,
    RequirementSourcePolicy,
    ResolvedPlanningRequest,
    ResearchTaskPlan,
    ResearchTaskPolicy,
    ResearchTaskProgress,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionCandidate,
    ResearchTaskSubQuestionResult,
    ResearchWorkerCheckpoint,
    ResearchWorkerProgress,
    build_research_task_plan_public_view,
)
from fast_app.services.agent_tasks.agent_task_capability_service import AgentTaskCapabilityService
from fast_app.services.agent_tasks.agent_task_dataset_scope_policy import (
    resolve_dataset_field_scope,
)
from fast_app.services.agent_tasks.agent_task_plan_validator import AgentTaskPlanValidator
from fast_app.services.agent_tasks.agent_task_source_policy import (
    resolve_required_source_types,
)
from fast_app.services.exceptions import AgentTaskSourceUnavailableError, ToolPermissionDeniedError
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.rag_agent.rag_agent_nodes import build_task_plan_answer
from fast_app.services.research.requirement_evidence_service import (
    AgentTaskRequirementEvidenceService,
)
from fast_app.services.research.agentic_research_executor import (
    _to_legacy_result,
    _to_research_result,
)
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.domain.agent_task_plan import (
    AgentTaskSubQuestionResult,
    ResearchEvidenceEvaluation,
)


def expected(kind: str, *, attributes: list[str] | None = None):
    return AgentTaskExpectedEvidence(
        evidence_type=kind,
        minimum_count=1,
        requires_query_id=kind == "sql_query_result",
        required_attributes=attributes or [],
    )


def requirement(
    item_id: str,
    mode: str,
    sources: list[str],
    evidence,
    *,
    completion: str = "strict",
):
    return AgentTaskRequirement(
        requirement_id=item_id,
        description=item_id,
        source_policy=RequirementSourcePolicy(mode=mode, source_types=sources),
        expected_evidence=evidence,
        completion_policy=completion,
    )


def sub_question(
    item_id: str,
    hint: str,
    covers: list[str],
    *,
    depends_on: list[str] | None = None,
    web_usage: str = "not_used",
):
    return ResearchTaskSubQuestion(
        sub_question_id=item_id,
        order=int(item_id.rsplit("_", 1)[-1]),
        question=item_id,
        purpose="test",
        depends_on=depends_on or [],
        information_source_hint=hint,
        covers_requirement_ids=covers,
        reason="test",
        web_usage=web_usage,
    )


def result(item_id: str, status: str, evidence_ids: list[str] | None = None):
    return ResearchTaskSubQuestionResult(
        sub_question_id=item_id,
        status=status,
        answer=f"answer:{item_id}",
        attempt_count=1,
        evidence_ids=evidence_ids or [],
    )


def evidence(
    evidence_id: str,
    kind: str,
    sub_question_id: str,
    **kwargs,
):
    source = {
        "knowledge_chunk": "knowledge_retrieval",
        "web_citation": "web_search",
        "sql_query_result": "nl2sql_query",
        "derived_synthesis": None,
    }[kind]
    defaults = {
        "reference_id": evidence_id,
        "url": None,
        "query_id": None,
        "dependency_sub_question_ids": [],
        "provided_attributes": [],
    }
    defaults.update(kwargs)
    return AgentTaskEvidenceRef(
        evidence_id=evidence_id,
        evidence_type=kind,
        source_type=source,
        sub_question_id=sub_question_id,
        **defaults,
    )


def quality_review():
    return AgentTaskPlanQualityReview(
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
    )


def main() -> None:
    service = AgentTaskRequirementEvidenceService()

    assert resolve_required_source_types(
        ResolvedPlanningRequest(
            current_query="请联网比较 RLS 与 security_invoker。",
            resolved_query="请联网比较 RLS 与 security_invoker。",
        )
    ) == ["web_search"]

    assert resolve_required_source_types(
        ResolvedPlanningRequest(
            current_query="不要联网，只根据当前知识库回答。",
            resolved_query="不要联网，只根据当前知识库回答。",
        )
    ) == []

    dataset_capability = AgentTaskCapabilitySnapshot(
        available_source_types=["nl2sql_query"],
        web_direct_allowed=False,
        web_fallback_allowed=False,
        knowledge_retrieval_available=False,
        nl2sql_query_available=True,
        dataset_id="game_test",
        allowed_dataset_fields=[
            "asset_name",
            "average_cost_yuan",
            "cost_yuan",
            "polygon_count",
        ],
        dataset_field_synonyms={
            "cost_yuan": ["费用"],
            "polygon_count": ["模型面数"],
        },
        max_requirements=10,
        max_sub_questions=8,
    )
    explicit_scope = resolve_dataset_field_scope(
        ResolvedPlanningRequest(
            current_query="比较角色资产01和角色资产06的费用、模型面数。",
            resolved_query="比较角色资产01和角色资产06的费用、模型面数。",
        ),
        dataset_capability,
    )
    assert explicit_scope is not None
    assert explicit_scope.explicit_fields == ["cost_yuan", "polygon_count"]
    assert explicit_scope.aggregation_operations == []

    assistant_ignored_scope = resolve_dataset_field_scope(
        ResolvedPlanningRequest(
            current_query="比较两个角色资产。",
            relevant_history=[
                AgentTaskPlanningTurn(role="assistant", content="建议比较费用和模型面数。")
            ],
            resolved_query="比较两个角色资产。",
        ),
        dataset_capability,
    )
    assert assistant_ignored_scope is not None
    assert assistant_ignored_scope.explicit_fields == []

    negated_scope = resolve_dataset_field_scope(
        ResolvedPlanningRequest(
            current_query="不要比较费用。只比较模型面数。",
            resolved_query="不要比较费用。只比较模型面数。",
        ),
        dataset_capability,
    )
    assert negated_scope is not None
    assert negated_scope.explicit_fields == ["polygon_count"]

    aggregation_scope = resolve_dataset_field_scope(
        ResolvedPlanningRequest(
            current_query="计算费用的平均值和总和，并统计数量。",
            resolved_query="计算费用的平均值和总和，并统计数量。",
        ),
        dataset_capability,
    )
    assert aggregation_scope is not None
    assert aggregation_scope.aggregation_operations == ["average", "sum", "count"]

    assert resolve_required_source_types(
        ResolvedPlanningRequest(
            current_query="继续比较这些方案。",
            relevant_history=[
                AgentTaskPlanningTurn(
                    role="user",
                    content="请联网查询两种方案的官方网页证据。",
                ),
                AgentTaskPlanningTurn(
                    role="assistant",
                    content="已完成第一轮比较。",
                ),
            ],
            resolved_query="继续联网比较两种方案。",
        )
    ) == ["web_search"]

    assert resolve_required_source_types(
        ResolvedPlanningRequest(
            current_query="比较当前知识库中的检索方案。",
            relevant_history=[
                AgentTaskPlanningTurn(
                    role="assistant",
                    content="建议联网补充网页资料。",
                )
            ],
            resolved_query="比较当前知识库中的检索方案。",
        )
    ) == []

    # Planner/Reviewer Candidate 明确不拥有服务端 web_usage。
    candidate = ResearchTaskSubQuestionCandidate(
        sub_question_id="sq_1",
        order=1,
        question="查知识库",
        purpose="事实",
        depends_on=[],
        information_source_hint="knowledge_retrieval",
        covers_requirement_ids=["req_1"],
        reason="需要文档证据",
    )
    try:
        ResearchTaskSubQuestionCandidate.model_validate(
            {**candidate.model_dump(), "web_usage": "direct"}
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Planner Candidate 不应接受 web_usage")

    # all_of 跨两个 SubQuestion；未完成贡献者使状态 pending，全部证据到齐后 satisfied。
    req_all = requirement(
        "req_1",
        "all_of",
        ["knowledge_retrieval", "web_search"],
        [expected("knowledge_chunk"), expected("web_citation")],
    )

    # Reviewer 不能一边声称 revised，一边保留失败的最终质量检查。
    try:
        AgentTaskPlanReviewDecision(
            verdict="revised",
            checks=AgentTaskPlanQualityChecks(
                requirement_coverage="pass",
                source_alignment="pass",
                semantic_alignment="fail",
                dependency_quality="pass",
                executability="pass",
                completion_policy_alignment="pass",
            ),
            revision_summary="已修订",
            revised_requirements=[req_all],
            revised_sub_questions=[candidate],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("revised 不应接受失败的最终质量检查")
    try:
        AgentTaskPlanQualityReview(
            verdict="accepted",
            checks=AgentTaskPlanQualityChecks(
                requirement_coverage="pass",
                source_alignment="pass",
                semantic_alignment="fail",
                dependency_quality="pass",
                executability="pass",
                completion_policy_alignment="pass",
            ),
            revision_count=0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("有效 TaskPlan 不应接受失败的最终质量检查")

    sq_k = sub_question("sq_1", "knowledge_retrieval", ["req_1"])
    sq_w = sub_question("sq_2", "web_search", ["req_1"], web_usage="direct")
    ev_k = evidence("ev_k", "knowledge_chunk", "sq_1")
    semantic_evaluation = ResearchEvidenceEvaluation(
        verdict="partial",
        confidence=0.9,
        relevance=0.9,
        coverage=0.5,
        authority=0.8,
        missing_points=["仍缺少官方完整说明"],
        recommended_action="stop_with_limitation",
        reason="现有证据只能覆盖一部分问题。",
    )
    legacy_result = AgentTaskSubQuestionResult(
        sub_question_id="sq_1",
        question=sq_k.question,
        selected_tool="knowledge_retrieval",
        status="partial",
        answer="部分回答",
        evaluation=semantic_evaluation,
    )
    validation = AgentTaskSubQuestionEvidenceValidation(
        sub_question_id="sq_1",
        valid_evidence_refs=["ev_k"],
    )
    converted_result = _to_research_result(legacy_result, validation)
    assert converted_result.evaluation == semantic_evaluation
    assert (
        _to_legacy_result(converted_result, sq_k).evaluation
        == semantic_evaluation
    )
    pending = service.aggregate(
        requirements=[req_all],
        sub_questions=[sq_k, sq_w],
        results=[result("sq_1", "completed", ["ev_k"]), result("sq_2", "running")],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_k": ev_k}),
    )[0]
    assert pending.status == "pending"
    ev_w = evidence(
        "ev_w",
        "web_citation",
        "sq_2",
        url="https://www.postgresql.org/docs/16/ddl-rowsecurity.html",
    )
    satisfied = service.aggregate(
        requirements=[req_all],
        sub_questions=[sq_k, sq_w],
        results=[
            result("sq_1", "completed", ["ev_k"]),
            result("sq_2", "completed", ["ev_w"]),
        ],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_k": ev_k, "ev_w": ev_w}),
    )[0]
    assert satisfied.status == "satisfied"

    req_web_strict = requirement(
        "req_web_strict",
        "all_of",
        ["web_search"],
        [expected("web_citation")],
    )
    sq_web_strict = sq_w.model_copy(
        update={"covers_requirement_ids": ["req_web_strict"]}
    )
    partial_strict = service.aggregate(
        requirements=[req_web_strict],
        sub_questions=[sq_web_strict],
        results=[result("sq_2", "partial", ["ev_w"])],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_w": ev_w}),
    )[0]
    assert partial_strict.status == "failed"
    assert partial_strict.evidence_refs == ["ev_w"]

    req_stale = requirement(
        "req_stale",
        "all_of",
        ["knowledge_retrieval"],
        [expected("knowledge_chunk")],
    )
    sq_stale = sq_k.model_copy(
        update={"covers_requirement_ids": ["req_stale"]}
    )
    stale_registry_status = service.aggregate(
        requirements=[req_stale],
        sub_questions=[sq_stale],
        results=[result("sq_1", "failed")],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_k": ev_k}),
    )[0]
    assert stale_registry_status.status == "failed"
    assert stale_registry_status.evidence_refs == []

    # any_of 已由 A 满足时，B 仍运行也不能把 Requirement 降级为 pending。
    req_any = requirement(
        "req_2",
        "any_of",
        ["knowledge_retrieval", "web_search"],
        [expected("knowledge_chunk"), expected("web_citation")],
    )
    any_status = service.aggregate(
        requirements=[req_any],
        sub_questions=[
            sub_question("sq_1", "knowledge_retrieval", ["req_2"]),
            sub_question("sq_2", "web_search", ["req_2"], web_usage="direct"),
        ],
        results=[result("sq_1", "completed", ["ev_k"]), result("sq_2", "running")],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_k": ev_k}),
    )[0]
    assert any_status.status == "satisfied"

    # 同一个 SQL Evidence 对费用和模型面数按 required_attributes 独立判断。
    req_cost = requirement(
        "req_3",
        "all_of",
        ["nl2sql_query"],
        [expected("sql_query_result", attributes=["cost_yuan"])],
    )
    req_polygon = requirement(
        "req_4",
        "all_of",
        ["nl2sql_query"],
        [expected("sql_query_result", attributes=["polygon_count"])],
    )
    sq_sql = sub_question("sq_3", "nl2sql_query", ["req_3", "req_4"])
    ev_sql = evidence(
        "ev_sql",
        "sql_query_result",
        "sq_3",
        reference_id="query-1",
        query_id="query-1",
        provided_attributes=["cost_yuan"],
    )
    sql_statuses = service.aggregate(
        requirements=[req_cost, req_polygon],
        sub_questions=[sq_sql],
        results=[result("sq_3", "completed", ["ev_sql"])],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_sql": ev_sql}),
    )
    assert [item.status for item in sql_statuses] == ["satisfied", "failed"]

    # strict 缺证据失败；allow_partial 有合法证据时才允许部分完成。
    req_partial = req_all.model_copy(update={"completion_policy": "allow_partial"})
    partial = service.aggregate(
        requirements=[req_partial],
        sub_questions=[sq_k, sq_w],
        results=[result("sq_1", "completed", ["ev_k"]), result("sq_2", "failed")],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_k": ev_k}),
    )[0]
    assert partial.status == "partially_satisfied"

    # Derived Evidence 必须带完整依赖，合法时 mode=none 可立即 satisfied。
    req_derived = requirement(
        "req_5",
        "none",
        [],
        [expected("derived_synthesis")],
    )
    sq_derived = sub_question(
        "sq_4",
        "none",
        ["req_5"],
        depends_on=["sq_1", "sq_2"],
    )
    ev_derived = evidence(
        "ev_derived",
        "derived_synthesis",
        "sq_4",
        reference_id="sq_4",
        dependency_sub_question_ids=["sq_1", "sq_2"],
    )
    derived_status = service.aggregate(
        requirements=[req_derived],
        sub_questions=[sq_derived],
        results=[result("sq_4", "completed", ["ev_derived"])],
        registry=AgentTaskEvidenceRegistry(evidence_by_id={"ev_derived": ev_derived}),
    )[0]
    assert derived_status.status == "satisfied"

    # Validator 在保存前拒绝不存在的 Dataset 逻辑字段。
    capability = AgentTaskCapabilitySnapshot(
        available_source_types=["knowledge_retrieval", "nl2sql_query"],
        web_direct_allowed=False,
        web_fallback_allowed=False,
        knowledge_retrieval_available=True,
        nl2sql_query_available=True,
        dataset_id="game_test",
        dataset_name="游戏资产",
        dataset_domain="game",
        allowed_dataset_fields=[
            "asset_name",
            "average_cost_yuan",
            "cost_yuan",
            "polygon_count",
        ],
        dataset_field_synonyms={
            "cost_yuan": ["费用"],
            "polygon_count": ["模型面数"],
        },
        max_requirements=10,
        max_sub_questions=5,
    )
    invalid_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_3",
                "all_of",
                ["nl2sql_query"],
                [expected("sql_query_result", attributes=["asset_price"])],
            )
        ],
        sub_questions=[sq_sql.model_copy(update={"covers_requirement_ids": ["req_3"]})],
    )
    issue_codes = {
        item.code
        for item in AgentTaskPlanValidator().validate_candidate(
            invalid_candidate,
            capability,
        )
    }
    assert "PLAN_DATASET_FIELD_UNAVAILABLE" in issue_codes

    dataset_scope = AgentTaskDatasetScope(
        explicit_fields=["cost_yuan", "polygon_count"],
        aggregation_operations=[],
    )
    unrequested_aggregation_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_3",
                "all_of",
                ["nl2sql_query"],
                [expected("sql_query_result", attributes=["average_cost_yuan"])],
            )
        ],
        sub_questions=[sq_sql.model_copy(update={"covers_requirement_ids": ["req_3"]})],
    )
    aggregation_issues = AgentTaskPlanValidator().validate_candidate(
        unrequested_aggregation_candidate,
        capability,
        dataset_scope=dataset_scope,
    )
    assert any(
        item.code == "PLAN_DATASET_AGGREGATION_NOT_REQUESTED"
        and item.severity == "error"
        for item in aggregation_issues
    )

    inferred_field_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_3",
                "all_of",
                ["nl2sql_query"],
                [expected("sql_query_result", attributes=["asset_name"])],
            )
        ],
        sub_questions=[sq_sql.model_copy(update={"covers_requirement_ids": ["req_3"]})],
    )
    inferred_issues = AgentTaskPlanValidator().validate_candidate(
        inferred_field_candidate,
        capability,
        dataset_scope=dataset_scope,
    )
    assert any(
        item.code == "PLAN_DATASET_FIELD_SCOPE_INFERRED"
        and item.severity == "warning"
        for item in inferred_issues
    )
    legacy_scope_issue_codes = {
        item.code
        for item in AgentTaskPlanValidator().validate_candidate(
            inferred_field_candidate,
            capability,
            dataset_scope=None,
        )
    }
    assert "PLAN_DATASET_FIELD_SCOPE_INFERRED" not in legacy_scope_issue_codes

    empty_attributes_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_3",
                "all_of",
                ["nl2sql_query"],
                [expected("sql_query_result")],
            )
        ],
        sub_questions=[sq_sql.model_copy(update={"covers_requirement_ids": ["req_3"]})],
    )
    empty_attribute_codes = {
        item.code
        for item in AgentTaskPlanValidator().validate_candidate(
            empty_attributes_candidate,
            capability,
            dataset_scope=dataset_scope,
        )
    }
    assert "PLAN_DATASET_REQUIRED_ATTRIBUTES_EMPTY" in empty_attribute_codes

    web_capability = capability.model_copy(
        update={
            "available_source_types": [
                "knowledge_retrieval",
                "web_search",
                "nl2sql_query",
            ],
            "web_direct_allowed": True,
        }
    )
    knowledge_only_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_source_guard",
                "all_of",
                ["knowledge_retrieval"],
                [expected("knowledge_chunk")],
            )
        ],
        sub_questions=[
            sub_question(
                "sq_6",
                "knowledge_retrieval",
                ["req_source_guard"],
            )
        ],
    )
    required_source_issue_codes = {
        item.code
        for item in AgentTaskPlanValidator().validate_candidate(
            knowledge_only_candidate,
            web_capability,
            required_source_types=["web_search"],
        )
    }
    assert "PLAN_REQUIRED_SOURCE_DROPPED" in required_source_issue_codes

    web_candidate = AgentTaskPlannerCandidate(
        requirements=[
            requirement(
                "req_required_web",
                "all_of",
                ["web_search"],
                [expected("web_citation")],
            )
        ],
        sub_questions=[
            sub_question(
                "sq_7",
                "web_search",
                ["req_required_web"],
                web_usage="direct",
            )
        ],
    )
    preserved_source_issue_codes = {
        item.code
        for item in AgentTaskPlanValidator().validate_candidate(
            web_candidate,
            web_capability,
            required_source_types=["web_search"],
        )
    }
    assert "PLAN_REQUIRED_SOURCE_DROPPED" not in preserved_source_issue_codes

    now = datetime.now(UTC)
    plan = ResearchTaskPlan(
        task_plan_id="task_plan_20260802000000_public",
        user_id="employee",
        original_query="internal raw query",
        source_query="resolved query",
        objective="resolved query",
        final_synthesis_instruction="evidence only",
        requirements=[req_cost],
        sub_questions=[sq_sql.model_copy(update={"covers_requirement_ids": ["req_3"]})],
        quality_review=quality_review(),
        capability_snapshot=capability,
        research_policy=ResearchTaskPolicy(
            mode="hybrid",
            top_k=5,
            min_score=0.0,
            dataset_id="game_test",
            nl2sql_action="query",
            required_source_types=["nl2sql_query"],
            dataset_scope=dataset_scope,
            allow_direct_web=False,
            allow_web_fallback=False,
        ),
        progress=ResearchTaskProgress(
            workers={"sq_3": ResearchWorkerProgress()}
        ),
        status="waiting_confirmation",
        created_at=now,
        updated_at=now,
        worker_checkpoints={
            "sq_3": ResearchWorkerCheckpoint(
                stage="evidence_evaluation",
                evidence=[{"id": "internal-only"}],
            )
        },
    )
    public = build_research_task_plan_public_view(plan).model_dump(mode="json")
    assert "original_query" not in public
    assert "dataset_id" not in public["capability_snapshot"]
    assert "evidence_registry" not in public
    assert "worker_checkpoints" not in public
    assert "dataset_field_synonyms" not in public["capability_snapshot"]
    assert "等待人工确认" in build_task_plan_answer(plan)

    store = InMemoryAgentTaskPlanStore()

    async def roundtrip_plan() -> ResearchTaskPlan:
        await store.create(plan)
        loaded_plan = await store.load(plan.task_plan_id)
        assert isinstance(loaded_plan, ResearchTaskPlan)
        return loaded_plan

    loaded = asyncio.run(roundtrip_plan())
    assert isinstance(loaded, ResearchTaskPlan)
    assert loaded.schema_version == 2
    assert loaded.research_policy.required_source_types == [
        "nl2sql_query"
    ]
    assert loaded.research_policy.dataset_scope == dataset_scope
    assert loaded.worker_checkpoints["sq_3"].evidence == [
        {"id": "internal-only"}
    ]

    legacy_payload = plan.model_dump(mode="json")
    legacy_payload["research_policy"].pop("required_source_types")
    legacy_payload["research_policy"].pop("dataset_scope")
    legacy_payload["capability_snapshot"].pop("dataset_field_synonyms")
    legacy_payload.pop("worker_checkpoints")
    legacy_plan = ResearchTaskPlan.model_validate(legacy_payload)
    assert legacy_plan.research_policy.required_source_types == []
    assert legacy_plan.research_policy.dataset_scope is None
    assert legacy_plan.capability_snapshot.dataset_field_synonyms == {}
    assert legacy_plan.worker_checkpoints == {}

    # Typed Evidence 的排他约束在 Schema 层拒绝非法字段组合。
    try:
        evidence(
            "bad",
            "knowledge_chunk",
            "sq_1",
            query_id="query-should-not-exist",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("knowledge_chunk 不应接受 query_id")

    capability_service = AgentTaskCapabilityService(
        settings=Settings(_env_file=None, BOCHA_API_KEY="configured"),
        dataset_registry=None,
        nl2sql_authorization=object(),
    )
    web_user = CurrentUserContext(
        user_id="web-user",
        is_authenticated=True,
        global_permission_codes=[PermissionCode.AGENT_TOOL_WEB_SEARCH.value],
    )
    capability_service.resolve_direct_web(user=web_user, allow_direct_web=True)
    try:
        capability_service.resolve_direct_web(
            user=CurrentUserContext(user_id="reader", is_authenticated=True),
            allow_direct_web=True,
        )
    except ToolPermissionDeniedError:
        pass
    else:
        raise AssertionError("无 Web Tool 权限必须返回 403 权限错误")
    try:
        capability_service.resolve_direct_web(user=web_user, allow_direct_web=False)
    except AgentTaskSourceUnavailableError:
        pass
    else:
        raise AssertionError("请求策略禁止 direct Web 时必须返回来源不可用")

    evaluator = ResearchEvidenceEvaluator(
        Settings(_env_file=None, OPENAI_API_KEY="test-key")
    )

    async def sufficient(*_args, **_kwargs):
        return ResearchEvidenceEvaluation(
            verdict="sufficient",
            confidence=0.9,
            relevance=0.9,
            coverage=0.9,
            authority=0.9,
            recommended_action="accept",
            reason="test",
        )

    evaluator._try_structured = sufficient
    evaluation = asyncio.run(
        evaluator.evaluate(
            sub_question=sq_sql,
            requirements=[req_cost],
            answer="asset_1 costs 100 yuan",
            evidence_refs=[
                {
                    "id": "query-1",
                    "source": "nl2sql_query",
                    "metadata": {"query_id": "query-1"},
                }
            ],
            answer_context=RagContext(
                query=sq_sql.question,
                docs=[
                    RetrievedDoc(
                        id="query-1",
                        content='{"asset_id":"asset_1","cost":100}',
                        score=1.0,
                        source="nl2sql_query",
                    )
                ],
                context_text='{"asset_id":"asset_1","cost":100}',
            ),
        )
    )
    assert evaluation.verdict == "sufficient"

    print("research_task_plan_v2=passed")


if __name__ == "__main__":
    main()
