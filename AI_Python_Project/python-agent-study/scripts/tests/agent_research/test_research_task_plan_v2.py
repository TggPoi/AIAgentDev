"""ResearchTaskPlan v2 的契约、证据聚合和公开视图回归。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import PermissionCode
from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskEvidenceRef,
    AgentTaskEvidenceRegistry,
    AgentTaskExpectedEvidence,
    AgentTaskPlannerCandidate,
    AgentTaskPlanReviewDecision,
    AgentTaskPlanQualityChecks,
    AgentTaskPlanQualityReview,
    AgentTaskRequirement,
    AgentTaskSubQuestionEvidenceValidation,
    RequirementSourcePolicy,
    ResearchTaskPlan,
    ResearchTaskPolicy,
    ResearchTaskProgress,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionCandidate,
    ResearchTaskSubQuestionResult,
    ResearchWorkerProgress,
    build_research_task_plan_public_view,
)
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_capability_service import AgentTaskCapabilityService
from fast_app.services.agent_tasks.agent_task_plan_validator import AgentTaskPlanValidator
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
        allowed_dataset_fields=["cost_yuan", "polygon_count"],
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
            allow_direct_web=False,
            allow_web_fallback=False,
        ),
        progress=ResearchTaskProgress(
            workers={"sq_3": ResearchWorkerProgress()}
        ),
        status="waiting_confirmation",
        created_at=now,
        updated_at=now,
    )
    public = build_research_task_plan_public_view(plan).model_dump(mode="json")
    assert "original_query" not in public
    assert "dataset_id" not in public["capability_snapshot"]
    assert "evidence_registry" not in public
    assert "等待人工确认" in build_task_plan_answer(plan)

    with TemporaryDirectory() as directory:
        store = AgentTaskPlanStore(
            Settings(_env_file=None, AGENT_TASK_PLAN_DIR=directory)
        )
        store.save(plan)
        loaded = store.load(plan.task_plan_id)
        assert isinstance(loaded, ResearchTaskPlan)
        assert loaded.schema_version == 2

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
            evidence=[{"source": "nl2sql_query", "query_id": "query-1"}],
        )
    )
    assert evaluation.verdict == "sufficient"

    print("research_task_plan_v2=passed")


if __name__ == "__main__":
    main()
