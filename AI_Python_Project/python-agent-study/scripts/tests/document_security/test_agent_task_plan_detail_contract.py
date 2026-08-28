"""验证 TaskPlan detail 的安全判别式公开契约。"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fast_app.api.agent_task_plan_routes import router
from fast_app.dependencies.rag_dependencies import get_agent_task_plan_store
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentToolStep
from fast_app.domain.research_task_plan import ResearchTaskPlan
from fast_app.domain.user_context import CurrentUserContext


FORBIDDEN_DOCUMENT_FIELDS = {
    "user_id",
    "original_query",
    "goal",
    "source_query",
    "target_path",
    "report_title",
    "research_policy",
    "sub_questions",
    "final_synthesis_instruction",
    "failure_phase",
    "input",
    "output",
    "error",
    "final_output",
    "tool_input",
    "tool_output",
    "tool_calls",
    "acl",
    "scope",
    "trace_id",
}


def main() -> None:
    assert_document_runtime_is_allowlisted()
    assert_research_runtime_keeps_existing_safe_view()
    assert_openapi_declares_discriminated_detail_union()
    print("agent_task_plan_detail_contract=passed")


def assert_document_runtime_is_allowlisted() -> None:
    marker = "must-not-appear-in-document-task-plan-detail"
    plan = _document_plan(marker)

    with _client(plan) as client:
        response = client.get(f"/agent/task-plans/{plan.task_plan_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "task_plan_id": plan.task_plan_id,
        "task_kind": "knowledge_document_management",
        "session_id": "session-detail-contract",
        "objective": "整理公开知识文档",
        "task_type": "analysis",
        "status": "waiting_confirmation",
        "requires_confirmation": True,
        "steps": [
            {
                "step_id": "step_public_1",
                "tool_name": "document_create",
                "status": "waiting_confirmation",
                "risk_level": "high",
                "requires_confirmation": True,
                "error_code": None,
            },
            {
                "step_id": "step_public_2",
                "tool_name": "document_preview",
                "status": "completed",
                "risk_level": "unknown",
                "requires_confirmation": False,
                "error_code": None,
            },
        ],
        "result_summary": {
            "total_steps": 2,
            "completed_steps": 1,
            "failed_steps": 0,
            "skipped_steps": 0,
        },
        "created_at": plan.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": plan.updated_at.isoformat().replace("+00:00", "Z"),
        "error_code": None,
    }
    assert marker not in response.text
    _assert_forbidden_keys_absent(payload)


def assert_research_runtime_keeps_existing_safe_view() -> None:
    marker = "must-not-appear-in-research-task-plan-detail"
    plan = _research_plan(marker)

    with _client(plan) as client:
        response = client.get(f"/agent/task-plans/{plan.task_plan_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task_kind"] == "question_decomposition"
    assert payload["task_plan_id"] == plan.task_plan_id
    assert payload["objective"] == "比较两种公开检索方案"
    assert "original_query" not in payload
    assert "research_policy" not in payload
    assert "worker_checkpoints" not in payload
    assert "evidence_registry" not in payload
    assert marker not in response.text


def assert_openapi_declares_discriminated_detail_union() -> None:
    app = _app(_document_plan("schema-only-secret"))
    schema = app.openapi()
    detail_schema = schema["paths"]["/agent/task-plans/{task_plan_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert detail_schema["discriminator"]["propertyName"] == "task_kind"
    mapping = detail_schema["discriminator"]["mapping"]
    assert mapping == {
        "knowledge_document_management": (
            "#/components/schemas/DocumentTaskPlanPublicView"
        ),
        "question_decomposition": (
            "#/components/schemas/ResearchTaskPlanPublicView"
        ),
    }
    refs = {item["$ref"] for item in detail_schema["oneOf"]}
    assert refs == set(mapping.values())

    components = schema["components"]["schemas"]
    document_properties = components["DocumentTaskPlanPublicView"]["properties"]
    assert set(document_properties) == {
        "task_plan_id",
        "task_kind",
        "session_id",
        "objective",
        "task_type",
        "status",
        "requires_confirmation",
        "steps",
        "result_summary",
        "created_at",
        "updated_at",
        "error_code",
    }
    step_properties = components["DocumentTaskPlanStepPublicView"]["properties"]
    assert set(step_properties) == {
        "step_id",
        "tool_name",
        "status",
        "risk_level",
        "requires_confirmation",
        "error_code",
    }
    assert FORBIDDEN_DOCUMENT_FIELDS.isdisjoint(document_properties)
    assert FORBIDDEN_DOCUMENT_FIELDS.isdisjoint(step_properties)


def _assert_forbidden_keys_absent(value: object) -> None:
    if isinstance(value, dict):
        assert FORBIDDEN_DOCUMENT_FIELDS.isdisjoint(value)
        for item in value.values():
            _assert_forbidden_keys_absent(item)
    elif isinstance(value, list):
        for item in value:
            _assert_forbidden_keys_absent(item)


def _client(plan: AgentTaskPlan | ResearchTaskPlan) -> TestClient:
    return TestClient(_app(plan), raise_server_exceptions=False)


def _app(plan: AgentTaskPlan | ResearchTaskPlan) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _owner()
    app.dependency_overrides[get_agent_task_plan_store] = lambda: _Store(plan)
    return app


class _Store:
    def __init__(self, plan: AgentTaskPlan | ResearchTaskPlan) -> None:
        self._plan = plan

    async def load(self, _task_plan_id: str) -> AgentTaskPlan | ResearchTaskPlan:
        return self._plan


def _owner() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="owner",
        username="owner",
        is_authenticated=True,
        auth_source="jwt",
    )


def _document_plan(marker: str) -> AgentTaskPlan:
    now = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
    return AgentTaskPlan(
        task_plan_id="task_plan_document_detail_contract",
        task_kind="knowledge_document_management",
        user_id="owner",
        session_id="session-detail-contract",
        original_query=marker,
        objective="整理公开知识文档",
        task_type="analysis",
        goal=marker,
        sub_questions=[],
        research_policy=None,
        final_synthesis_instruction=marker,
        source_query=marker,
        target_path=f"private/{marker}.md",
        report_title=marker,
        status="waiting_confirmation",
        steps=[
            AgentToolStep(
                step_id="step_public_1",
                tool_name="document_create",
                status="waiting_confirmation",
                input={"secret": marker},
                output={"secret": marker},
                risk_level="high",
                requires_confirmation=True,
                error=marker,
            ),
            AgentToolStep(
                step_id="step_public_2",
                tool_name="document_preview",
                status="completed",
                input={"secret": marker},
                output={"secret": marker},
                risk_level=marker,
            ),
        ],
        final_output={"secret": marker},
        created_at=now,
        updated_at=now,
        error=marker,
    )


def _research_plan(marker: str) -> ResearchTaskPlan:
    now = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
    return ResearchTaskPlan(
        task_plan_id="task_plan_research_detail_contract",
        user_id="owner",
        session_id="session-detail-contract",
        original_query=marker,
        source_query="比较公开检索方案",
        objective="比较两种公开检索方案",
        final_synthesis_instruction="仅依据公开证据综合",
        requirements=[],
        sub_questions=[],
        quality_review={
            "verdict": "accepted",
            "checks": {
                "requirement_coverage": "pass",
                "source_alignment": "pass",
                "semantic_alignment": "pass",
                "dependency_quality": "pass",
                "executability": "pass",
                "completion_policy_alignment": "pass",
            },
            "revision_count": 0,
        },
        capability_snapshot={
            "available_source_types": [],
            "web_direct_allowed": False,
            "web_fallback_allowed": False,
            "knowledge_retrieval_available": True,
            "nl2sql_query_available": False,
            "dataset_id": marker,
            "allowed_dataset_views": [marker],
            "allowed_dataset_fields": [marker],
            "dataset_field_synonyms": {marker: [marker]},
            "dataset_schema_context": marker,
            "max_requirements": 10,
            "max_sub_questions": 8,
        },
        research_policy={
            "mode": "hybrid",
            "top_k": 5,
            "min_score": 0.0,
            "source_path": marker,
            "dataset_id": marker,
            "allow_direct_web": False,
            "allow_web_fallback": False,
        },
        status="waiting_confirmation",
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    main()
