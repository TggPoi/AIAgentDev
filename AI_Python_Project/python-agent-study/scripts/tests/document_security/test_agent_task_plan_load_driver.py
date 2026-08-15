from __future__ import annotations

"""问题十二压测驱动的结构化 SSE 与报告分类回归。"""

import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx

from accept_agent_task_plan_load import (
    User,
    request_structured_sse,
    run,
    run_control,
    run_rag_requests,
    run_sse_scenario,
    summarize,
)


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        for event, data in events
    ).encode("utf-8")


async def test_structured_sse_success_uses_mainline_and_collects_metrics() -> None:
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream; charset=utf-8"},
            content=_sse(
                ("sources", {"sources": [{"doc_id": "doc-1"}]}),
                ("answer_delta", {"text": "安全回答"}),
                ("done", {"status": "done", "knowledge_version": 7}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await request_structured_sse(
            client,
            base_url="http://testserver",
            operation="rag_stream",
            user=User(name="user-1", token="token-1"),
            query="测试结构化流",
            session_id="session-1",
            expected_error_codes=frozenset(),
            require_answer=True,
        )

    assert seen_paths == ["/rag/chat/stream/events"]
    assert sample.outcome == "success"
    assert sample.terminal_event == "done"
    assert sample.source_count == 1
    assert sample.answer_event_count == 1
    assert sample.event_names == ("sources", "answer_delta", "done")
    assert sample.first_event_ms is not None
    assert sample.first_answer_ms is not None


async def test_expected_capacity_error_is_not_counted_as_business_failure() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                (
                    "error",
                    {
                        "code": "AGENT_CAPACITY_EXCEEDED",
                        "message": "capacity full",
                    },
                )
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await request_structured_sse(
            client,
            base_url="http://testserver",
            operation="document_capacity_collision",
            user=User(name="user-2", token="token-2"),
            query="创建测试文档",
            session_id="session-2",
            expected_error_codes=frozenset({"AGENT_CAPACITY_EXCEEDED"}),
            require_answer=False,
        )

    report = summarize([sample], duration_seconds=1.0)
    assert sample.outcome == "expected_rejection"
    assert sample.terminal_event == "error"
    assert sample.error_code == "AGENT_CAPACITY_EXCEEDED"
    assert report["expected_rejection_count"] == 1
    assert report["unexpected_failure_count"] == 0
    assert report["business_success_rate"] == 1.0


async def test_duplicate_terminal_is_protocol_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await request_structured_sse(
            client,
            base_url="http://testserver",
            operation="rag_stream",
            user=User(name="user-3", token="token-3"),
            query="重复终态",
            session_id="session-3",
            expected_error_codes=frozenset(),
            require_answer=True,
        )

    assert sample.outcome == "protocol_error"
    assert sample.error_code == "SSE_PROTOCOL_ERROR"


async def test_fixed_request_count_uses_all_selected_users_and_stops_exactly() -> None:
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
            ),
        )

    users = [User(name="user-a", token="a"), User(name="user-b", token="b")]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        samples = await run_rag_requests(
            client,
            base_url="http://testserver",
            users=users,
            query="固定次数",
            concurrency=2,
            request_count=3,
            duration_seconds=None,
            max_request_count=None,
            think_min=0.0,
            think_max=0.0,
        )

    assert len(samples) == 3
    assert {sample.user for sample in samples} == {"user-a", "user-b"}
    assert seen_paths == [
        "/rag/chat/stream/events",
        "/rag/chat/stream/events",
        "/rag/chat/stream/events",
    ]


async def test_each_rag_request_uses_an_independent_session() -> None:
    seen_session_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_session_ids.append(str(payload["session_id"]))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        samples = await run_rag_requests(
            client,
            base_url="http://testserver",
            users=[User(name="same-user", token="token")],
            query="独立会话",
            concurrency=1,
            request_count=3,
            duration_seconds=None,
            max_request_count=None,
            think_min=0.0,
            think_max=0.0,
        )

    assert len(samples) == 3
    assert len(seen_session_ids) == 3
    assert len(set(seen_session_ids)) == 3


async def test_duration_mode_uses_an_independent_session_per_request() -> None:
    seen_session_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_session_ids.append(str(payload["session_id"]))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        samples = await run_rag_requests(
            client,
            base_url="http://testserver",
            users=[User(name="same-user", token="token")],
            query="持续模式独立会话",
            concurrency=1,
            request_count=None,
            duration_seconds=10.0,
            max_request_count=3,
            think_min=0.0,
            think_max=0.0,
        )

    assert len(samples) == 3
    assert len(seen_session_ids) == 3
    assert len(set(seen_session_ids)) == 3


async def test_run_report_tracks_structured_stream_participants() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
            ),
        )

    old_values = {
        f"LOAD_TEST_DRIVER_{index:02d}": os.environ.get(
            f"LOAD_TEST_DRIVER_{index:02d}"
        )
        for index in range(1, 11)
    }
    try:
        for index in range(1, 11):
            os.environ[f"LOAD_TEST_DRIVER_{index:02d}"] = f"token-{index}"
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "users.json"
            config_path.write_text(
                json.dumps(
                    {
                        "users": [
                            {
                                "name": f"user-{index:02d}",
                                "token_env": f"LOAD_TEST_DRIVER_{index:02d}",
                            }
                            for index in range(1, 11)
                        ],
                        "controls": [],
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                config=str(config_path),
                user_limit=2,
                request_count=2,
                duration_seconds=None,
                max_request_count=None,
                concurrency=2,
                query="报告参与者",
                base_url="http://testserver",
                think_min_seconds=0.0,
                think_max_seconds=0.0,
                timeout_seconds=5.0,
                min_success_rate=1.0,
                max_p95_ms=1000.0,
                allow_capacity_rejections=False,
                min_capacity_rejections=0,
                max_capacity_rejections=0,
            )
            report = await run(args, transport=httpx.MockTransport(handler))
    finally:
        for name, value in old_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    assert report["request_count"] == 2
    assert report["participating_rag_users"] == ["user-01", "user-02"]
    assert report["rag_stream_success_rate"] == 1.0


async def test_control_repeat_reuses_idempotency_key_without_implicit_replay() -> None:
    seen_keys: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_keys.append(request.headers.get("Idempotency-Key", ""))
        return httpx.Response(
            200,
            json={
                "task_plan_id": "task_plan_cancel",
                "status": "cancelled",
            },
        )

    samples = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await run_control(
            client,
            base_url="http://testserver",
            users={"user-1": User(name="user-1", token="token")},
            item={
                "operation": "cancel",
                "user": "user-1",
                "task_plan_id": "task_plan_cancel",
                "attempts": 3,
                "idempotency_key": "same-key",
                "replay": False,
                "get_state": False,
            },
            samples=samples,
        )

    assert len(samples) == 3
    assert seen_keys == ["same-key", "same-key", "same-key"]
    assert all(sample.outcome == "success" for sample in samples)


async def test_document_collision_waits_for_capacity_then_accepts_sse_error() -> None:
    waited: list[str] = []

    async def capacity_waiter(workload: str, _timeout: float) -> None:
        waited.append(workload)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                (
                    "error",
                    {
                        "code": "AGENT_CAPACITY_EXCEEDED",
                        "message": "document slot full",
                    },
                )
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await run_sse_scenario(
            client,
            base_url="http://testserver",
            users={"user-1": User(name="user-1", token="token")},
            item={
                "name": "document_collision",
                "user": "user-1",
                "query": "创建隔离测试文档",
                "wait_for_capacity_workload": "document",
                "expected_error_codes": ["AGENT_CAPACITY_EXCEEDED"],
                "require_answer": False,
            },
            capacity_waiter=capacity_waiter,
        )

    assert waited == ["document"]
    assert sample.outcome == "expected_rejection"
    assert sample.error_code == "AGENT_CAPACITY_EXCEEDED"


async def test_named_sse_scenario_preserves_explicit_session_id() -> None:
    seen_session_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen_session_ids.append(str(payload["session_id"]))
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await run_sse_scenario(
            client,
            base_url="http://testserver",
            users={"user-1": User(name="user-1", token="token")},
            item={
                "name": "document_explicit_session",
                "user": "user-1",
                "query": "创建隔离测试文档",
                "session_id": "explicit-session-id",
            },
        )

    assert sample.outcome == "success"
    assert seen_session_ids == ["explicit-session-id"]


async def test_shared_stop_event_prevents_new_rag_dispatch() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("stop event 已设置时不应发出 HTTP 请求")

    stop_event = asyncio.Event()
    stop_event.set()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        samples = await run_rag_requests(
            client,
            base_url="http://testserver",
            users=[User(name="user-1", token="token")],
            query="不应发送",
            concurrency=1,
            request_count=1,
            duration_seconds=None,
            max_request_count=None,
            think_min=0.0,
            think_max=0.0,
            stop_event=stop_event,
        )

    assert samples == []


async def test_named_sse_scenario_requires_declared_business_events() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "仅普通回答"}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await run_sse_scenario(
            client,
            base_url="http://testserver",
            users={"user-1": User(name="user-1", token="token")},
            item={
                "name": "document_accepted",
                "user": "user-1",
                "query": "复杂文档",
                "required_events": ["agent_task_document_supervised"],
            },
        )

    assert sample.outcome == "protocol_error"
    assert sample.error_code == "SSE_REQUIRED_EVENT_MISSING"


async def test_unexpected_guard_block_is_not_a_normal_rag_success() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("guard_blocked", {"text": "[BLOCKED]"}),
                ("done", {"status": "done"}),
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sample = await request_structured_sse(
            client,
            base_url="http://testserver",
            operation="rag_stream",
            user=User(name="user-1", token="token"),
            query="普通安全问题",
            session_id="guard-session",
            expected_error_codes=frozenset(),
            require_answer=True,
        )

    assert sample.outcome == "protocol_error"
    assert sample.error_code == "SSE_PROTOCOL_ERROR"


async def test_mixed_load_reports_fifteen_global_in_flight_requests() -> None:
    started = 0
    all_started = asyncio.Event()
    start_lock = asyncio.Lock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal started
        async with start_lock:
            started += 1
            if started == 15:
                all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1.0)
        if request.url.path.startswith("/agent/task-plans/"):
            return httpx.Response(
                200,
                json={"task_plan_id": request.url.path.split("/")[3], "status": "completed"},
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=_sse(
                ("sources", {"sources": []}),
                ("answer_delta", {"text": "回答"}),
                ("done", {"status": "done"}),
            ),
        )

    env_names = [f"LOAD_MIXED_USER_{index:02d}" for index in range(1, 16)]
    old_values = {name: os.environ.get(name) for name in env_names}
    try:
        for index, name in enumerate(env_names, start=1):
            os.environ[name] = f"token-{index}"
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mixed-users.json"
            config_path.write_text(
                json.dumps(
                    {
                        "users": [
                            {
                                "name": f"load_test_{index:02d}",
                                "token_env": env_names[index - 1],
                            }
                            for index in range(1, 16)
                        ],
                        "controls": [
                            {
                                "operation": "get",
                                "user": f"load_test_{index:02d}",
                                "task_plan_id": f"task_plan_{index:02d}",
                            }
                            for index in range(11, 14)
                        ],
                        "sse_scenarios": [
                            {
                                "name": f"document_{index:02d}",
                                "user": f"load_test_{index:02d}",
                                "query": "创建隔离测试文档",
                            }
                            for index in range(14, 16)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                config=str(config_path),
                user_limit=10,
                request_count=10,
                duration_seconds=None,
                max_request_count=None,
                concurrency=10,
                query="混合并发",
                base_url="http://testserver",
                think_min_seconds=0.0,
                think_max_seconds=0.0,
                timeout_seconds=5.0,
                min_success_rate=1.0,
                max_p95_ms=1000.0,
                min_global_peak_active_requests=15,
                max_global_peak_active_requests=15,
                allow_capacity_rejections=False,
                min_capacity_rejections=0,
                max_capacity_rejections=0,
            )
            report = await run(args, transport=httpx.MockTransport(handler))
    finally:
        for name, value in old_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    assert report["configured_user_count"] == 15
    assert report["virtual_user_count"] == 10
    assert report["global_peak_active_requests"] == 15
    assert report["participating_rag_users"] == [
        f"load_test_{index:02d}" for index in range(1, 11)
    ]


async def main() -> None:
    await test_structured_sse_success_uses_mainline_and_collects_metrics()
    await test_expected_capacity_error_is_not_counted_as_business_failure()
    await test_duplicate_terminal_is_protocol_error()
    await test_fixed_request_count_uses_all_selected_users_and_stops_exactly()
    await test_each_rag_request_uses_an_independent_session()
    await test_duration_mode_uses_an_independent_session_per_request()
    await test_run_report_tracks_structured_stream_participants()
    await test_control_repeat_reuses_idempotency_key_without_implicit_replay()
    await test_document_collision_waits_for_capacity_then_accepts_sse_error()
    await test_named_sse_scenario_preserves_explicit_session_id()
    await test_shared_stop_event_prevents_new_rag_dispatch()
    await test_named_sse_scenario_requires_declared_business_events()
    await test_unexpected_guard_block_is_not_a_normal_rag_success()
    await test_mixed_load_reports_fifteen_global_in_flight_requests()
    print("agent_task_plan_load_driver=passed")


if __name__ == "__main__":
    asyncio.run(main())
