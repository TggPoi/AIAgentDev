"""验证 TaskPlan confirm-stream 的安全业务事件契约。"""

from __future__ import annotations

import json

from fastapi import FastAPI

from fast_app.api import agent_task_plan_routes
from fast_app.core.request_context import reset_request_context, set_request_context


def main() -> None:
    assert_step_event_drops_raw_output_and_error()
    assert_research_progress_is_projected_to_stable_facts()
    assert_document_progress_is_projected_to_stable_facts()
    assert_sub_question_answer_and_payload_request_id_are_not_trusted()
    assert_terminal_events_use_safe_stable_shapes()
    assert_unknown_task_plan_event_is_discarded()
    assert_openapi_declares_task_plan_event_union()
    print("agent_task_plan_stream_public_contract=passed")


def assert_step_event_drops_raw_output_and_error() -> None:
    marker = "must-not-appear-in-task-plan-step-event"
    frame = agent_task_plan_routes._format_sse_event(
        "agent_task_step_completed",
        {
            "task_plan_id": "task_plan_stream_contract",
            "step_id": "step_1",
            "tool_name": "knowledge_document_create",
            "status": "completed",
            "output": {"secret": marker},
            "error": marker,
            "tool_calls": [{"arguments": marker}],
            "acl": marker,
            "scope": marker,
        },
    )
    event, payload = _parse_frame(frame)
    assert event == "agent_task_step_completed"
    assert payload == {
        "contract_version": "1.0",
        "request_id": None,
        "task_plan_id": "task_plan_stream_contract",
        "step_id": "step_1",
        "tool_name": "knowledge_document_create",
        "status": "completed",
        "error_code": None,
    }
    assert marker not in frame


def assert_research_progress_is_projected_to_stable_facts() -> None:
    marker = "must-not-appear-in-task-plan-research-event"
    frame = agent_task_plan_routes._format_sse_event(
        "agent_task_research_worker_progress",
        {
            "task_plan_id": "task_plan_stream_contract",
            "sub_question_id": "sq_1",
            "wave": 2,
            "attempt": 3,
            "status": "running",
            "stage": "tool_execution",
            "active_operations": ["knowledge_retrieval", marker],
            "tool_call_count": 4,
            "evidence_count": 5,
            "last_tool_name": marker,
            "evaluation": {"reason": marker},
            "dataset_rows": [{"secret": marker}],
            "internal_url": f"https://internal.invalid/{marker}",
        },
    )
    event, payload = _parse_frame(frame)
    assert event == "agent_task_research_worker_progress"
    assert payload == {
        "contract_version": "1.0",
        "request_id": None,
        "task_plan_id": "task_plan_stream_contract",
        "sub_question_id": "sq_1",
        "wave": 2,
        "status": "running",
        "reason_code": None,
        "attempt": 3,
        "stage": "tool_execution",
        "active_operation_count": 2,
        "tool_call_count": 4,
        "evidence_count": 5,
    }
    assert marker not in frame


def assert_document_progress_is_projected_to_stable_facts() -> None:
    marker = "must-not-appear-in-task-plan-document-event"
    frame = agent_task_plan_routes._format_sse_event(
        "agent_task_document_review_completed",
        {
            "task_plan_id": "task_plan_stream_contract",
            "deliverable_id": "deliverable_1",
            "verdict": "approved",
            "confidence": 0.9,
            "draft": marker,
            "tool_arguments": {"secret": marker},
            "error": marker,
            "trace_id": marker,
        },
    )
    event, payload = _parse_frame(frame)
    assert event == "agent_task_document_review_completed"
    assert payload == {
        "contract_version": "1.0",
        "request_id": None,
        "task_plan_id": "task_plan_stream_contract",
        "deliverable_id": "deliverable_1",
        "step_id": None,
        "operation": None,
        "status": None,
        "verdict": "approved",
        "confidence": 0.9,
        "error_code": None,
        "deliverable_count": None,
    }
    assert marker not in frame


def assert_sub_question_answer_and_payload_request_id_are_not_trusted() -> None:
    marker = "must-not-appear-in-task-plan-sub-question-event"
    request_tokens = set_request_context(request_id="request-task-plan-contract")
    try:
        frame = agent_task_plan_routes._format_sse_event(
            "sub_question_completed",
            {
                "task_plan_id": "task_plan_stream_contract",
                "request_id": marker,
                "sub_question_id": "sq_1",
                "status": "completed",
                "answer": marker,
                "evidence_ids": ["evidence_1"],
                "tool_calls": [{"arguments": marker}],
            },
        )
    finally:
        reset_request_context(*request_tokens)
    event, payload = _parse_frame(frame)
    assert event == "sub_question_completed"
    assert payload == {
        "contract_version": "1.0",
        "request_id": "request-task-plan-contract",
        "task_plan_id": "task_plan_stream_contract",
        "sub_question_id": "sq_1",
        "status": "completed",
        "error_code": None,
        "evidence_count": 1,
    }
    assert marker not in frame


def assert_terminal_events_use_safe_stable_shapes() -> None:
    marker = "must-not-appear-in-task-plan-terminal-event"
    error_frame = agent_task_plan_routes._format_sse_event(
        "error",
        {
            "task_plan_id": "task_plan_stream_contract",
            "error_code": "AGENT_TASK_PLAN_STREAM_FAILED",
            "message": marker,
            "retryable": False,
            "ctx": {"secret": marker},
        },
    )
    event, payload = _parse_frame(error_frame)
    assert event == "error"
    assert payload == {
        "contract_version": "1.0",
        "request_id": None,
        "task_plan_id": "task_plan_stream_contract",
        "code": "AGENT_TASK_PLAN_STREAM_FAILED",
        "message": "TaskPlan 执行失败",
        "error_category": "system_error",
        "trace_id": None,
    }
    assert marker not in error_frame

    done_frame = agent_task_plan_routes._format_sse_event(
        "done",
        {
            "task_plan_id": "task_plan_stream_contract",
            "status": "completed_with_warnings",
            "final_output": {"secret": marker},
        },
    )
    event, payload = _parse_frame(done_frame)
    assert event == "done"
    assert payload == {
        "contract_version": "1.0",
        "request_id": None,
        "task_plan_id": "task_plan_stream_contract",
        "status": "done",
        "task_status": "completed_with_warnings",
    }
    assert marker not in done_frame


def assert_unknown_task_plan_event_is_discarded() -> None:
    marker = "must-not-appear-in-unknown-task-plan-event"
    assert (
        agent_task_plan_routes._format_sse_event(
            "agent_task_internal_checkpoint",
            {"task_plan_id": "task_plan_stream_contract", "secret": marker},
        )
        == ""
    )


def assert_openapi_declares_task_plan_event_union() -> None:
    app = FastAPI()
    app.include_router(agent_task_plan_routes.router)
    openapi = app.openapi()
    response_schema = openapi["paths"][
        "/agent/task-plans/{task_plan_id}/confirm/stream"
    ]["post"]["responses"]["200"]["content"]["text/event-stream"]["schema"]
    assert response_schema == {
        "$ref": "#/components/schemas/TaskPlanPublicEventFrame"
    }
    schema = openapi["components"]["schemas"]["TaskPlanPublicEventFrame"]

    assert schema["discriminator"]["propertyName"] == "event"
    assert len(schema["oneOf"]) >= 10
    mapping = schema["discriminator"]["mapping"]
    for event_name in (
        "agent_task_execution_started",
        "agent_task_status",
        "agent_task_research_worker_progress",
        "sub_question_completed",
        "requirement_satisfied",
        "agent_task_document_review_completed",
        "agent_task_step_completed",
        "agent_task_final_synthesis_completed",
        "answer_delta",
        "done",
        "error",
    ):
        assert event_name in mapping


def _parse_frame(chunk: str) -> tuple[str, dict[str, object]]:
    lines = chunk.strip().splitlines()
    event = next(line[7:] for line in lines if line.startswith("event: "))
    payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return event, payload


if __name__ == "__main__":
    main()
