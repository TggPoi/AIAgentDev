"""11.7/11.9 的真实 HTTP、SSE、TaskPlan 和外部模型验收。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests


def post_sse(
    *,
    base_url: str,
    path: str,
    payload: dict[str, Any],
    label: str,
    timeout: float,
) -> tuple[str, list[dict[str, Any]]]:
    request_id = uuid4().hex
    events: list[dict[str, Any]] = []
    current_event = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal data_lines
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        item = {"event": current_event, "data": data}
        events.append(item)
        print(json.dumps({"label": label, **item}, ensure_ascii=False), flush=True)
        data_lines = []

    with requests.post(
        f"{base_url.rstrip('/')}{path}",
        json=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Request-ID": request_id,
        },
        stream=True,
        timeout=(15, timeout),
    ) as response:
        print(
            json.dumps(
                {
                    "label": label,
                    "request_id": request_id,
                    "status_code": response.status_code,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if line == "":
                flush()
                current_event = "message"
                continue
            if line.startswith("event:"):
                current_event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        flush()
    return request_id, events


def task_plan_id_from(events: list[dict[str, Any]]) -> str:
    for item in events:
        data = item.get("data")
        if isinstance(data, dict):
            task_plan_id = data.get("task_plan_id") or data.get("agent_task_plan_id")
            if isinstance(task_plan_id, str) and task_plan_id.startswith("task_plan_"):
                return task_plan_id
    raise AssertionError("结构化 SSE 未返回 task_plan_id")


def load_internal_plan(task_plan_dir: Path, task_plan_id: str) -> dict[str, Any]:
    matches = sorted(task_plan_dir.glob(f"*_{task_plan_id}.json"))
    if not matches:
        raise AssertionError(f"未找到内部 TaskPlan JSON: {task_plan_id}")
    return json.loads(matches[-1].read_text(encoding="utf-8"))


def get_public_plan(base_url: str, task_plan_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{base_url.rstrip('/')}/agent/task-plans/{task_plan_id}",
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("公开 TaskPlan 响应必须是 JSON object")
    return payload


def confirm(
    *,
    base_url: str,
    task_plan_id: str,
    label: str,
    timeout: float,
) -> tuple[str, list[dict[str, Any]]]:
    return post_sse(
        base_url=base_url,
        path=f"/agent/task-plans/{task_plan_id}/confirm/stream",
        payload={"confirmed": True},
        label=label,
        timeout=timeout,
    )


def assert_no_sse_error(events: list[dict[str, Any]], label: str) -> None:
    errors = [item for item in events if item.get("event") == "error"]
    if errors:
        raise AssertionError(f"{label} 出现 SSE error: {errors}")


def accept_117(base_url: str, task_plan_dir: Path, timeout: float) -> None:
    query_request_id, query_events = post_sse(
        base_url=base_url,
        path="/rag/chat/stream/events",
        payload={
            "session_id": f"accept-117-{uuid4().hex}",
            "query": (
                "根据当前知识库，分别说明混合检索、Rerank 和 Prompt Guard 的职责，"
                "并分析它们在一次 RAG 请求中的先后关系与协作边界。"
            ),
            "mode": "hybrid",
            "top_k": 5,
            "min_score": 0,
            "allow_direct_web": False,
            "allow_web_fallback": False,
            "filters": {"source_path": None, "section_path": []},
        },
        label="11.7-query",
        timeout=timeout,
    )
    assert_no_sse_error(query_events, "11.7-query")
    task_plan_id = task_plan_id_from(query_events)
    confirm_request_id, confirm_events = confirm(
        base_url=base_url,
        task_plan_id=task_plan_id,
        label="11.7-confirm",
        timeout=timeout,
    )
    assert_no_sse_error(confirm_events, "11.7-confirm")

    timed_out_events = [
        item
        for item in confirm_events
        if item.get("event") == "agent_task_research_worker_timed_out"
    ]
    if not timed_out_events:
        raise AssertionError("11.7 未产生 Worker timeout SSE，无法验收超时现场")
    for item in timed_out_events:
        data = item["data"]
        assert isinstance(data, dict)
        assert data.get("stage") not in {None, "starting"}
        assert int(data.get("attempt") or 0) >= 1
        for forbidden in ("tool_calls", "evidence", "tool_input", "tool_output"):
            assert forbidden not in data

    internal = load_internal_plan(task_plan_dir, task_plan_id)
    timeout_results = [
        item
        for item in internal.get("sub_question_results", [])
        if item.get("error_code") == "WORKER_TIMEOUT"
    ]
    if not timeout_results:
        raise AssertionError("11.7 内部 TaskPlan 没有 WORKER_TIMEOUT Result")
    for result in timeout_results:
        assert int(result.get("attempt_count") or 0) >= 1
        checkpoint = internal.get("worker_checkpoints", {}).get(
            result["sub_question_id"]
        )
        assert isinstance(checkpoint, dict)
        assert checkpoint.get("stage") not in {None, "starting"}

    public = get_public_plan(base_url, task_plan_id)
    assert "worker_checkpoints" not in public
    print(
        json.dumps(
            {
                "acceptance": "11.7",
                "result": "passed",
                "task_plan_id": task_plan_id,
                "query_request_id": query_request_id,
                "confirm_request_id": confirm_request_id,
                "timeout_worker_count": len(timeout_results),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _sql_required_attributes(plan: dict[str, Any]) -> list[str]:
    return [
        str(attribute)
        for requirement in plan.get("requirements", [])
        for expected in requirement.get("expected_evidence", [])
        if expected.get("evidence_type") == "sql_query_result"
        for attribute in expected.get("required_attributes", [])
    ]


def accept_119(base_url: str, task_plan_dir: Path, timeout: float) -> None:
    session_id = f"accept-119-{uuid4().hex}"
    prerequisite_request_id, prerequisite_events = post_sse(
        base_url=base_url,
        path="/rag/chat/stream/events",
        payload={
            "session_id": session_id,
            "query": (
                "本轮分析对象是《星港远征》中已授权的 3D 模型资产，"
                "重点关注费用、模型面数和移动端适配。"
            ),
            "mode": "hybrid",
            "top_k": 5,
            "min_score": 0,
            "allow_direct_web": False,
            "allow_web_fallback": False,
            "filters": {"source_path": None, "section_path": []},
        },
        label="11.9-prerequisite",
        timeout=timeout,
    )
    assert_no_sse_error(prerequisite_events, "11.9-prerequisite")

    query_request_id, query_events = post_sse(
        base_url=base_url,
        path="/rag/chat/stream/events",
        payload={
            "session_id": session_id,
            "query": "结合知识库继续比较这些资产，并说明哪些内容还需要公开资料验证。",
            "mode": "hybrid",
            "top_k": 5,
            "min_score": 0,
            "dataset_id": "game_test",
            "nl2sql_action": "query",
            "allow_direct_web": True,
            "allow_web_fallback": False,
            "filters": {"source_path": None, "section_path": []},
        },
        label="11.9-query",
        timeout=timeout,
    )
    assert_no_sse_error(query_events, "11.9-query")
    task_plan_id = task_plan_id_from(query_events)
    before_confirm = load_internal_plan(task_plan_dir, task_plan_id)
    scope = before_confirm.get("research_policy", {}).get("dataset_scope")
    assert isinstance(scope, dict)
    explicit_fields = set(scope.get("explicit_fields", []))
    assert {"cost_yuan", "polygon_count"}.issubset(explicit_fields)
    assert scope.get("aggregation_operations") == []

    attributes = _sql_required_attributes(before_confirm)
    forbidden_aggregations = [
        field
        for field in attributes
        if field.startswith(("average_", "avg_", "total_", "sum_", "count_"))
        or field.endswith(("_average", "_avg", "_total", "_sum"))
    ]
    assert not forbidden_aggregations, (
        "11.9 计划仍包含用户未要求的聚合字段: " + ", ".join(forbidden_aggregations)
    )

    confirm_request_id, confirm_events = confirm(
        base_url=base_url,
        task_plan_id=task_plan_id,
        label="11.9-confirm",
        timeout=timeout,
    )
    assert_no_sse_error(confirm_events, "11.9-confirm")
    done_events = [item for item in confirm_events if item.get("event") == "done"]
    if not done_events:
        raise AssertionError("11.9 confirm/stream 未收敛到 done")
    after_confirm = load_internal_plan(task_plan_dir, task_plan_id)
    assert not [
        issue
        for issue in after_confirm.get("validation_issues", [])
        if issue.get("code") == "PLAN_DATASET_AGGREGATION_NOT_REQUESTED"
    ]
    print(
        json.dumps(
            {
                "acceptance": "11.9",
                "result": "passed",
                "task_plan_id": task_plan_id,
                "prerequisite_request_id": prerequisite_request_id,
                "query_request_id": query_request_id,
                "confirm_request_id": confirm_request_id,
                "dataset_scope": scope,
                "sql_required_attributes": attributes,
                "terminal_status": after_confirm.get("status"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("11.7", "11.9"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--task-plan-dir",
        type=Path,
        default=Path("runtime/agent-task-plans"),
    )
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    if args.scenario == "11.7":
        accept_117(args.base_url, args.task_plan_dir, args.timeout)
    else:
        accept_119(args.base_url, args.task_plan_dir, args.timeout)


if __name__ == "__main__":
    main()
