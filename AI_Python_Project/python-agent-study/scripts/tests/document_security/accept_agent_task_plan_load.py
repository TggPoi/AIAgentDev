from __future__ import annotations

"""15 人结构化 SSE 与 Agent TaskPlan 混合压力测试脚本。

所有 RAG 请求只调用 ``POST /rag/chat/stream/events`` 并完整消费结构化 SSE；
脚本不会调用开发调试接口 ``POST /rag/chat`` 或 deprecated token stream。
固定次数模式用于 P0，时长模式必须同时给出最大请求数作为费用保险丝。
control 是否重放由配置显式决定，容量碰撞场景必须关闭重放。
报告使用全局在途请求峰值验证 10 个 RAG + 3 个 Research + 2 个 Document。

配置示例见修订版方案附录 F.1（.tmp/agent-load-users.json）。
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import math
import os
import random
import statistics
import time
from collections.abc import Awaitable, Callable
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class User:
    name: str
    token: str


@dataclass(frozen=True)
class Sample:
    operation: str
    user: str
    status_code: int
    elapsed_ms: float
    error_code: str | None
    task_plan_id: str | None
    task_status: str | None
    outcome: str = "success"
    first_event_ms: float | None = None
    first_answer_ms: float | None = None
    source_count: int = 0
    answer_event_count: int = 0
    terminal_event: str | None = None
    event_names: tuple[str, ...] = ()
    protocol_error: str | None = None


class ActiveRequestTracker:
    """统计本次压测所有 HTTP/SSE 请求的全局在途峰值。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.active = 0
        self.peak = 0

    @asynccontextmanager
    async def track(self):
        async with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            yield
        finally:
            async with self._lock:
                self.active -= 1


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def load_config(
    path: Path,
) -> tuple[list[User], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    users = []
    for item in payload.get("users", []):
        token_env = str(item["token_env"])
        token = os.environ.get(token_env, "").strip()
        if not token:
            raise RuntimeError(f"missing token env: {token_env}")
        users.append(User(name=str(item["name"]), token=token))
    if not 10 <= len(users) <= 15:
        raise RuntimeError("10–15 人验收必须提供 10 到 15 个真实认证身份")
    names = {user.name for user in users}
    controls = [dict(item) for item in payload.get("controls", [])]
    for item in controls:
        if item.get("user") not in names:
            raise RuntimeError(f"control user 不存在: {item}")
        if item.get("operation") not in {"confirm", "retry", "cancel", "get"}:
            raise RuntimeError(f"control operation 非法: {item}")
    sse_scenarios = [dict(item) for item in payload.get("sse_scenarios", [])]
    scenario_names: set[str] = set()
    for item in sse_scenarios:
        name = str(item.get("name") or "").strip()
        if not name or name in scenario_names:
            raise RuntimeError(f"sse_scenario name 缺失或重复: {item}")
        scenario_names.add(name)
        if item.get("user") not in names:
            raise RuntimeError(f"sse_scenario user 不存在: {item}")
        if not str(item.get("query") or "").strip():
            raise RuntimeError(f"sse_scenario query 不能为空: {item}")
        workload = item.get("wait_for_capacity_workload")
        if workload not in {None, "research", "document"}:
            raise RuntimeError(f"sse_scenario capacity workload 非法: {item}")
    return users, controls, sse_scenarios


def error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    value = body.get("code") if isinstance(body, dict) else None
    return value if isinstance(value, str) else None


async def _request_json_impl(
    client: httpx.AsyncClient,
    *,
    operation: str,
    user: User,
    method: str,
    url: str,
    json_body: dict[str, Any] | None,
    idempotency_key: str | None = None,
    task_plan_id: str | None = None,
    expected_error_codes: frozenset[str] = frozenset(),
) -> Sample:
    headers = {"Authorization": f"Bearer {user.token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    started = time.perf_counter()
    try:
        response = await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
        )
        elapsed = (time.perf_counter() - started) * 1000
        try:
            response_body = response.json()
        except ValueError:
            response_body = None
        task_status = (
            response_body.get("status")
            if isinstance(response_body, dict)
            and isinstance(response_body.get("status"), str)
            else None
        )
        response_error_code = error_code(response)
        if 200 <= response.status_code < 300:
            outcome = "success"
        elif response_error_code in expected_error_codes:
            outcome = "expected_rejection"
        elif response.status_code >= 500:
            outcome = "unexpected_5xx"
        else:
            outcome = "http_error"
        return Sample(
            operation=operation,
            user=user.name,
            status_code=response.status_code,
            elapsed_ms=elapsed,
            error_code=response_error_code,
            task_plan_id=task_plan_id,
            task_status=task_status,
            outcome=outcome,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return Sample(
            operation=operation,
            user=user.name,
            status_code=0,
            elapsed_ms=elapsed,
            error_code=type(exc).__name__,
            task_plan_id=task_plan_id,
            task_status=None,
            outcome="network_error",
        )


async def request_json(
    client: httpx.AsyncClient,
    *,
    operation: str,
    user: User,
    method: str,
    url: str,
    json_body: dict[str, Any] | None,
    idempotency_key: str | None = None,
    task_plan_id: str | None = None,
    expected_error_codes: frozenset[str] = frozenset(),
    request_tracker: ActiveRequestTracker | None = None,
) -> Sample:
    call = _request_json_impl(
        client,
        operation=operation,
        user=user,
        method=method,
        url=url,
        json_body=json_body,
        idempotency_key=idempotency_key,
        task_plan_id=task_plan_id,
        expected_error_codes=expected_error_codes,
    )
    if request_tracker is None:
        return await call
    async with request_tracker.track():
        return await call


async def _request_structured_sse_impl(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    operation: str,
    user: User,
    query: str,
    session_id: str,
    expected_error_codes: frozenset[str],
    require_answer: bool,
    allow_guard_blocked: bool = False,
) -> Sample:
    """完整消费结构化 SSE，并把协议终态和容量拒绝分开记录。"""

    started = time.perf_counter()
    first_event_ms: float | None = None
    first_answer_ms: float | None = None
    event_names: list[str] = []
    source_count = 0
    answer_event_count = 0
    task_plan_id: str | None = None
    task_status: str | None = None
    terminal_event: str | None = None
    stream_error_code: str | None = None
    protocol_error: str | None = None
    guard_blocked_seen = False
    headers = {
        "Authorization": f"Bearer {user.token}",
        "Accept": "text/event-stream",
    }
    payload = {
        "session_id": session_id,
        "query": query,
        "mode": "hybrid",
        "top_k": 5,
        "min_score": 0.0,
        "allow_web_fallback": False,
        "allow_direct_web": False,
    }
    try:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/rag/chat/stream/events",
            headers=headers,
            json=payload,
        ) as response:
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code < 200 or response.status_code >= 300:
                body = await response.aread()
                error_code = _http_error_code(body)
                elapsed = (time.perf_counter() - started) * 1000
                return Sample(
                    operation=operation,
                    user=user.name,
                    status_code=response.status_code,
                    elapsed_ms=elapsed,
                    error_code=error_code,
                    task_plan_id=None,
                    task_status=None,
                    outcome=(
                        "expected_rejection"
                        if error_code in expected_error_codes
                        else (
                            "unexpected_5xx"
                            if response.status_code >= 500
                            else "http_error"
                        )
                    ),
                )
            if "text/event-stream" not in content_type:
                protocol_error = (
                    "结构化流 Content-Type 必须是 text/event-stream，"
                    f"实际为 {content_type or '<missing>'}"
                )
            else:
                current_event = "message"
                data_lines: list[str] = []

                async def consume_event() -> None:
                    nonlocal first_event_ms
                    nonlocal first_answer_ms
                    nonlocal source_count
                    nonlocal answer_event_count
                    nonlocal task_plan_id
                    nonlocal task_status
                    nonlocal terminal_event
                    nonlocal stream_error_code
                    nonlocal protocol_error
                    nonlocal guard_blocked_seen
                    nonlocal data_lines
                    if not data_lines:
                        return
                    raw_data = "\n".join(data_lines)
                    data_lines = []
                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError as exc:
                        protocol_error = f"SSE data 不是 JSON object: {exc}"
                        return
                    if not isinstance(data, dict):
                        protocol_error = "SSE data 必须是 JSON object"
                        return
                    now_ms = (time.perf_counter() - started) * 1000
                    if first_event_ms is None:
                        first_event_ms = now_ms
                    if terminal_event is not None:
                        protocol_error = "done/error 终态后不能继续发送事件"
                        return
                    event_names.append(current_event)
                    if current_event == "sources":
                        sources = data.get("sources")
                        if not isinstance(sources, list):
                            protocol_error = "sources 事件必须携带 list"
                            return
                        source_count = len(sources)
                    elif current_event in {
                        "answer_delta",
                        "guard_sanitized",
                        "guard_blocked",
                    }:
                        if "sources" not in event_names:
                            protocol_error = "回答事件不能早于 sources"
                            return
                        answer_event_count += 1
                        if current_event == "guard_blocked":
                            guard_blocked_seen = True
                        if first_answer_ms is None:
                            first_answer_ms = now_ms
                    elif current_event == "agent_task_plan_created":
                        raw_task_plan_id = data.get("task_plan_id")
                        if isinstance(raw_task_plan_id, str):
                            task_plan_id = raw_task_plan_id
                        raw_status = data.get("status")
                        if isinstance(raw_status, str):
                            task_status = raw_status
                    elif current_event == "done":
                        if data.get("status") != "done":
                            protocol_error = "done 事件缺少 status=done"
                            return
                        terminal_event = "done"
                    elif current_event == "error":
                        terminal_event = "error"
                        raw_code = data.get("code")
                        stream_error_code = (
                            str(raw_code) if raw_code is not None else "RAG_STREAM_ERROR"
                        )

                async for line in response.aiter_lines():
                    if line == "":
                        await consume_event()
                        current_event = "message"
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        current_event = line.removeprefix("event:").strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line.removeprefix("data:").lstrip())
                await consume_event()

                if protocol_error is None and terminal_event is None:
                    protocol_error = "结构化流缺少 done/error 终态"
                if (
                    protocol_error is None
                    and terminal_event == "done"
                    and "sources" not in event_names
                ):
                    protocol_error = "成功流缺少 sources 事件"
                if (
                    protocol_error is None
                    and terminal_event == "done"
                    and require_answer
                    and answer_event_count == 0
                ):
                    protocol_error = "成功流缺少回答事件"
                if (
                    protocol_error is None
                    and terminal_event == "done"
                    and guard_blocked_seen
                    and not allow_guard_blocked
                ):
                    protocol_error = "普通 RAG 场景出现未声明的 guard_blocked"

            elapsed = (time.perf_counter() - started) * 1000
            if protocol_error is not None:
                outcome = "protocol_error"
                error_code = "SSE_PROTOCOL_ERROR"
            elif terminal_event == "error":
                error_code = stream_error_code
                outcome = (
                    "expected_rejection"
                    if error_code in expected_error_codes
                    else "sse_error"
                )
            else:
                error_code = None
                outcome = "success"
            return Sample(
                operation=operation,
                user=user.name,
                status_code=response.status_code,
                elapsed_ms=elapsed,
                error_code=error_code,
                task_plan_id=task_plan_id,
                task_status=task_status,
                outcome=outcome,
                first_event_ms=first_event_ms,
                first_answer_ms=first_answer_ms,
                source_count=source_count,
                answer_event_count=answer_event_count,
                terminal_event=terminal_event,
                event_names=tuple(event_names),
                protocol_error=protocol_error,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return Sample(
            operation=operation,
            user=user.name,
            status_code=0,
            elapsed_ms=elapsed,
            error_code=type(exc).__name__,
            task_plan_id=None,
            task_status=None,
            outcome="network_error",
        )


def _http_error_code(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("code")
    return str(value) if value is not None else None


async def request_structured_sse(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    operation: str,
    user: User,
    query: str,
    session_id: str,
    expected_error_codes: frozenset[str],
    require_answer: bool,
    allow_guard_blocked: bool = False,
    request_tracker: ActiveRequestTracker | None = None,
) -> Sample:
    call = _request_structured_sse_impl(
        client,
        base_url=base_url,
        operation=operation,
        user=user,
        query=query,
        session_id=session_id,
        expected_error_codes=expected_error_codes,
        require_answer=require_answer,
        allow_guard_blocked=allow_guard_blocked,
    )
    if request_tracker is None:
        return await call
    async with request_tracker.track():
        return await call


async def run_rag_requests(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    users: list[User],
    query: str,
    concurrency: int,
    request_count: int | None,
    duration_seconds: float | None,
    max_request_count: int | None,
    think_min: float,
    think_max: float,
    stop_event: asyncio.Event | None = None,
    request_tracker: ActiveRequestTracker | None = None,
) -> list[Sample]:
    """按固定次数或“时长 + 最大次数”驱动结构化 SSE 请求。"""

    if not users:
        raise ValueError("至少需要一个压测身份")
    if concurrency < 1:
        raise ValueError("concurrency 必须至少为 1")
    if request_count is None and duration_seconds is None:
        raise ValueError("request_count 和 duration_seconds 至少提供一个")
    started = time.monotonic()
    deadline = (
        started + duration_seconds if duration_seconds is not None else None
    )
    reservation_lock = asyncio.Lock()
    next_request = 0
    samples: list[Sample] = []

    async def reserve() -> tuple[int, User] | None:
        nonlocal next_request
        async with reservation_lock:
            if stop_event is not None and stop_event.is_set():
                return None
            if request_count is not None and next_request >= request_count:
                return None
            if max_request_count is not None and next_request >= max_request_count:
                return None
            if deadline is not None and time.monotonic() >= deadline:
                return None
            index = next_request
            next_request += 1
            return index, users[index % len(users)]

    async def worker() -> None:
        nonlocal next_request
        while True:
            reserved = await reserve()
            if reserved is None:
                return
            index, user = reserved
            sample = await request_structured_sse(
                client,
                base_url=base_url,
                operation="rag_stream",
                user=user,
                query=query,
                session_id=f"load-{user.name}-{index}-{uuid4().hex[:8]}",
                expected_error_codes=frozenset(),
                require_answer=True,
                request_tracker=request_tracker,
            )
            samples.append(sample)
            if (
                sample.outcome in {"unexpected_5xx", "protocol_error"}
                or sample.outcome == "sse_error"
            ):
                if stop_event is not None:
                    stop_event.set()
                # 已经领取的并发请求会安全收尾；此处只阻止该 worker 继续派发。
                async with reservation_lock:
                    if request_count is not None:
                        next_request = request_count
                    elif max_request_count is not None:
                        next_request = max_request_count
                return
            if think_max > 0:
                await asyncio.sleep(random.uniform(think_min, think_max))

    await asyncio.gather(
        *(asyncio.create_task(worker()) for _ in range(concurrency))
    )
    return samples


async def run_control(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    users: dict[str, User],
    item: dict[str, Any],
    samples: list[Sample],
    stop_event: asyncio.Event | None = None,
    request_tracker: ActiveRequestTracker | None = None,
) -> None:
    operation = item["operation"]
    task_plan_id = item["task_plan_id"]
    body = {"confirmed": True} if operation == "confirm" else None
    key = str(item.get("idempotency_key") or uuid4())
    expected_error_codes = frozenset(
        str(code) for code in item.get("expected_error_codes", [])
    )
    attempts = int(item.get("attempts", 1))
    if attempts < 1:
        raise RuntimeError(f"control attempts 必须至少为 1: {item}")
    method = "GET" if operation == "get" else "POST"
    url = (
        f"{base_url}/agent/task-plans/{task_plan_id}"
        if operation == "get"
        else f"{base_url}/agent/task-plans/{task_plan_id}/{operation}"
    )
    for attempt_index in range(attempts):
        sample = await request_json(
            client,
            operation=(
                f"task_{operation}"
                if attempt_index == 0
                else f"task_{operation}_repeat"
            ),
            user=users[item["user"]],
            method=method,
            url=url,
            json_body=body,
            idempotency_key=key if operation != "get" else None,
            task_plan_id=task_plan_id,
            expected_error_codes=expected_error_codes,
            request_tracker=request_tracker,
        )
        samples.append(sample)
        if sample.outcome not in {"success", "expected_rejection"}:
            if stop_event is not None:
                stop_event.set()

    if operation != "get" and attempts == 1 and bool(item.get("replay", True)):
        # 幂等重放是独立断言；容量碰撞场景必须在配置中设 replay=false，
        # 否则一个预期拒绝会被统计两次。
        replay = await request_json(
            client,
            operation=f"task_{operation}_replay",
            user=users[item["user"]],
            method="POST",
            url=f"{base_url}/agent/task-plans/{task_plan_id}/{operation}",
            json_body=body,
            idempotency_key=key,
            task_plan_id=task_plan_id,
            expected_error_codes=expected_error_codes,
            request_tracker=request_tracker,
        )
        samples.append(replay)
        if replay.outcome not in {"success", "expected_rejection"}:
            if stop_event is not None:
                stop_event.set()

    if operation != "get" and bool(item.get("get_state", True)):
        state = await request_json(
            client,
            operation=f"task_{operation}_state",
            user=users[item["user"]],
            method="GET",
            url=f"{base_url}/agent/task-plans/{task_plan_id}",
            json_body=None,
            task_plan_id=task_plan_id,
            request_tracker=request_tracker,
        )
        samples.append(state)
        if state.outcome not in {"success", "expected_rejection"}:
            if stop_event is not None:
                stop_event.set()


async def run_sse_scenario(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    users: dict[str, User],
    item: dict[str, Any],
    capacity_waiter: Callable[[str, float], Awaitable[None]] | None = None,
    stop_event: asyncio.Event | None = None,
    request_tracker: ActiveRequestTracker | None = None,
) -> Sample:
    """执行一个命名 SSE 场景；可等待数据库容量槽已被前序请求持有。"""

    delay_seconds = float(item.get("start_delay_seconds", 0.0))
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    workload = item.get("wait_for_capacity_workload")
    if isinstance(workload, str):
        waiter = capacity_waiter or wait_for_active_capacity_slot
        try:
            await waiter(
                workload,
                float(item.get("capacity_wait_timeout_seconds", 120.0)),
            )
        except Exception as exc:
            if stop_event is not None:
                stop_event.set()
            return Sample(
                operation=str(item["name"]),
                user=str(item["user"]),
                status_code=0,
                elapsed_ms=0.0,
                error_code="CAPACITY_WAIT_FAILED",
                task_plan_id=None,
                task_status=None,
                outcome="protocol_error",
                protocol_error=f"{type(exc).__name__}: {exc}",
            )
    expected_error_codes = frozenset(
        str(code) for code in item.get("expected_error_codes", [])
    )
    user = users[str(item["user"])]
    sample = await request_structured_sse(
        client,
        base_url=base_url,
        operation=str(item["name"]),
        user=user,
        query=str(item["query"]),
        session_id=str(
            item.get("session_id")
            or f"load-{item['name']}-{user.name}-{uuid4().hex[:8]}"
        ),
        expected_error_codes=expected_error_codes,
        require_answer=bool(item.get("require_answer", False)),
        allow_guard_blocked=bool(item.get("allow_guard_blocked", False)),
        request_tracker=request_tracker,
    )
    expected_statuses = {
        str(status) for status in item.get("expected_task_statuses", [])
    }
    if (
        sample.outcome == "success"
        and expected_statuses
        and sample.task_status not in expected_statuses
    ):
        expected_text = ",".join(sorted(expected_statuses))
        sample = replace(
            sample,
            outcome="protocol_error",
            error_code="TASK_PLAN_STATUS_MISMATCH",
            protocol_error=(
                f"SSE scenario TaskPlan 状态为 {sample.task_status!r}，"
                f"期望 {expected_text}"
            ),
        )
    required_events = {
        str(event) for event in item.get("required_events", [])
    }
    missing_events = sorted(required_events - set(sample.event_names))
    if sample.outcome == "success" and missing_events:
        sample = replace(
            sample,
            outcome="protocol_error",
            error_code="SSE_REQUIRED_EVENT_MISSING",
            protocol_error=(
                "SSE scenario 缺少必需业务事件: " + ",".join(missing_events)
            ),
        )
    if sample.outcome not in {"success", "expected_rejection"}:
        if stop_event is not None:
            stop_event.set()
    return sample


async def wait_for_active_capacity_slot(
    workload_type: str,
    timeout_seconds: float,
) -> None:
    """只读轮询容量槽，用于确定性启动第二个 Document SSE 请求。"""

    from sqlalchemy import func, select

    from fast_app.core.config import get_settings
    from fast_app.db.agent_task_plan_tables import AgentTaskCapacitySlotTable
    from fast_app.db.session import create_database_engine, create_session_factory

    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            async with factory() as session:
                occupied = await session.scalar(
                    select(AgentTaskCapacitySlotTable.slot_no)
                    .where(
                        AgentTaskCapacitySlotTable.workload_type == workload_type,
                        AgentTaskCapacitySlotTable.lease_owner.is_not(None),
                        AgentTaskCapacitySlotTable.lease_until > func.now(),
                    )
                    .limit(1)
                )
            if occupied is not None:
                return
            await asyncio.sleep(0.2)
    finally:
        await engine.dispose()
    raise TimeoutError(
        f"等待 {workload_type} capacity slot 被占用超时: {timeout_seconds}s"
    )


def summarize(samples: list[Sample], duration_seconds: float) -> dict[str, Any]:
    elapsed = [sample.elapsed_ms for sample in samples]
    status_counts = Counter(str(sample.status_code) for sample in samples)
    error_counts = Counter(
        sample.error_code for sample in samples if sample.error_code is not None
    )
    successes = sum(1 for sample in samples if sample.outcome == "success")
    expected_rejections = sum(
        1 for sample in samples if sample.outcome == "expected_rejection"
    )
    unexpected_failures = len(samples) - successes - expected_rejections
    business_attempts = successes + unexpected_failures
    by_operation = {}
    for operation in sorted({sample.operation for sample in samples}):
        operation_samples = [
            sample for sample in samples if sample.operation == operation
        ]
        operation_elapsed = [sample.elapsed_ms for sample in operation_samples]
        operation_successes = sum(
            1 for sample in operation_samples if sample.outcome == "success"
        )
        operation_expected_rejections = sum(
            1
            for sample in operation_samples
            if sample.outcome == "expected_rejection"
        )
        operation_business_attempts = (
            len(operation_samples) - operation_expected_rejections
        )
        by_operation[operation] = {
            "count": len(operation_samples),
            "success_rate": (
                operation_successes / operation_business_attempts
                if operation_business_attempts
                else 1.0
            ),
            "expected_rejection_count": operation_expected_rejections,
            "p95_ms": percentile(operation_elapsed, 0.95),
            "max_ms": max(operation_elapsed, default=0.0),
        }
    first_event_values = [
        sample.first_event_ms
        for sample in samples
        if sample.first_event_ms is not None
    ]
    first_answer_values = [
        sample.first_answer_ms
        for sample in samples
        if sample.first_answer_ms is not None
    ]
    outcome_counts = Counter(sample.outcome for sample in samples)
    return {
        "request_count": len(samples),
        "success_count": successes,
        "expected_rejection_count": expected_rejections,
        "unexpected_failure_count": unexpected_failures,
        "business_success_rate": (
            successes / business_attempts if business_attempts else 1.0
        ),
        # 兼容旧报告消费者；语义已经改为排除预期拒绝后的业务成功率。
        "success_rate": successes / business_attempts if business_attempts else 1.0,
        "requests_per_second": len(samples) / duration_seconds,
        "latency_ms": {
            "mean": statistics.fmean(elapsed) if elapsed else 0.0,
            "p50": percentile(elapsed, 0.50),
            "p95": percentile(elapsed, 0.95),
            "p99": percentile(elapsed, 0.99),
            "max": max(elapsed, default=0.0),
        },
        "status_counts": dict(status_counts),
        "error_code_counts": dict(error_counts),
        "outcome_counts": dict(outcome_counts),
        "sse_latency_ms": {
            "first_event_p50": percentile(first_event_values, 0.50),
            "first_event_p95": percentile(first_event_values, 0.95),
            "first_answer_p50": percentile(first_answer_values, 0.50),
            "first_answer_p95": percentile(first_answer_values, 0.95),
        },
        "by_operation": by_operation,
        "samples": [asdict(sample) for sample in samples],
    }


async def run(
    args,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    configured_users, controls, sse_scenarios = load_config(Path(args.config))
    users = (
        configured_users[: args.user_limit]
        if args.user_limit > 0
        else configured_users
    )
    skip_rag = bool(getattr(args, "skip_rag", False))
    if (
        not skip_rag
        and args.request_count is not None
        and args.request_count < len(users)
    ):
        raise RuntimeError(
            "固定请求数小于参与身份数；请减小 --user-limit 或增加 --request-count"
        )
    users_by_name = {user.name: user for user in configured_users}
    samples: list[Sample] = []
    limits = httpx.Limits(
        max_connections=max(
            20,
            args.concurrency + len(controls) + len(sse_scenarios) + 5,
        ),
        max_keepalive_connections=max(10, args.concurrency),
    )
    timeout = httpx.Timeout(args.timeout_seconds)
    started = time.monotonic()
    stop_event = asyncio.Event()
    request_tracker = ActiveRequestTracker()
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        transport=transport,
    ) as client:
        rag_task = (
            None
            if skip_rag
            else asyncio.create_task(
                run_rag_requests(
                    client,
                    base_url=args.base_url.rstrip("/"),
                    users=users,
                    query=args.query,
                    concurrency=args.concurrency,
                    request_count=args.request_count,
                    duration_seconds=args.duration_seconds,
                    max_request_count=args.max_request_count,
                    think_min=args.think_min_seconds,
                    think_max=args.think_max_seconds,
                    stop_event=stop_event,
                    request_tracker=request_tracker,
                )
            )
        )
        control_tasks = [
            asyncio.create_task(
                run_control(
                    client,
                    base_url=args.base_url.rstrip("/"),
                    users=users_by_name,
                    item=item,
                    samples=samples,
                    stop_event=stop_event,
                    request_tracker=request_tracker,
                )
            )
            for item in controls
        ]
        scenario_tasks = [
            asyncio.create_task(
                run_sse_scenario(
                    client,
                    base_url=args.base_url.rstrip("/"),
                    users=users_by_name,
                    item=item,
                    stop_event=stop_event,
                    request_tracker=request_tracker,
                )
            )
            for item in sse_scenarios
        ]
        complex_tasks = [*control_tasks, *scenario_tasks]
        stop_when_complex_complete = bool(
            getattr(args, "stop_rag_when_scenarios_complete", False)
        )
        if stop_when_complex_complete and not complex_tasks:
            raise RuntimeError(
                "--stop-rag-when-scenarios-complete 需要 control 或 SSE scenario"
            )

        async def stop_after_complex_tasks() -> None:
            await asyncio.gather(*complex_tasks)
            stop_event.set()

        watcher = (
            asyncio.create_task(stop_after_complex_tasks())
            if stop_when_complex_complete
            else None
        )
        all_tasks = list(complex_tasks)
        if rag_task is not None:
            all_tasks.insert(0, rag_task)
        if watcher is not None:
            all_tasks.append(watcher)
        if not all_tasks:
            raise RuntimeError("没有可执行的 RAG、control 或 SSE scenario")
        await asyncio.gather(*all_tasks)
        if rag_task is not None:
            samples.extend(rag_task.result())
        samples.extend(task.result() for task in scenario_tasks)

    actual_duration = max(time.monotonic() - started, 0.001)
    report = summarize(samples, actual_duration)
    report["configured_user_count"] = len(configured_users)
    report["virtual_user_count"] = len(users)
    report["rag_concurrency"] = args.concurrency
    report["global_peak_active_requests"] = request_tracker.peak
    report["min_global_peak_active_requests"] = int(
        getattr(args, "min_global_peak_active_requests", 0)
    )
    report["max_global_peak_active_requests"] = int(
        getattr(args, "max_global_peak_active_requests", 0)
    )
    report["duration_seconds"] = actual_duration
    report["request_count_requested"] = args.request_count
    report["duration_seconds_requested"] = args.duration_seconds
    report["max_request_count"] = args.max_request_count
    report["skip_rag"] = skip_rag
    report["stop_rag_when_scenarios_complete"] = bool(
        getattr(args, "stop_rag_when_scenarios_complete", False)
    )
    report["control_count"] = len(controls)
    report["sse_scenario_count"] = len(sse_scenarios)
    report["participating_rag_users"] = sorted(
        {sample.user for sample in samples if sample.operation == "rag_stream"}
    )

    unexpected_5xx = sum(
        1 for sample in samples if sample.outcome == "unexpected_5xx"
    )
    protocol_errors = sum(
        1 for sample in samples if sample.outcome == "protocol_error"
    )
    capacity_rejections = report["error_code_counts"].get(
        "AGENT_CAPACITY_EXCEEDED", 0
    )
    assert unexpected_5xx == 0, report
    assert protocol_errors == 0, report
    assert request_tracker.peak >= report["min_global_peak_active_requests"], report
    if report["max_global_peak_active_requests"] > 0:
        assert request_tracker.peak <= report["max_global_peak_active_requests"], report
    assert all(
        sample.outcome in {"success", "expected_rejection"}
        for sample in samples
    ), report
    if not skip_rag:
        assert len(report["participating_rag_users"]) == len(users), report
    rag_samples = [sample for sample in samples if sample.operation == "rag_stream"]
    rag_successes = sum(
        1 for sample in rag_samples if sample.outcome == "success"
    )
    rag_success_rate = rag_successes / len(rag_samples) if rag_samples else 1.0
    report["rag_stream_success_rate"] = rag_success_rate
    rag_p95 = percentile([sample.elapsed_ms for sample in rag_samples], 0.95)
    report["rag_stream_p95_ms"] = rag_p95
    assert rag_success_rate >= args.min_success_rate, report
    assert rag_p95 <= args.max_p95_ms, report
    if not args.allow_capacity_rejections:
        assert capacity_rejections == 0, report
    assert capacity_rejections >= args.min_capacity_rejections, report
    assert capacity_rejections <= args.max_capacity_rejections, report
    accepted_control_ids = {
        sample.task_plan_id
        for sample in samples
        if sample.operation in {"task_confirm", "task_retry", "task_cancel"}
        and sample.outcome == "success"
    }
    for sample in samples:
        if (
            not sample.operation.endswith("_state")
            or sample.task_plan_id not in accepted_control_ids
        ):
            continue
        if sample.operation == "task_cancel_state":
            assert sample.task_status == "cancelled", asdict(sample)
        else:
            assert sample.task_status in {
                "completed",
                "completed_with_warnings",
            }, asdict(sample)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--request-count", type=int)
    parser.add_argument("--duration-seconds", type=int)
    parser.add_argument("--max-request-count", type=int)
    parser.add_argument(
        "--skip-rag",
        action="store_true",
        help="只运行 control/SSE scenario；P1 零模型调用场景使用。",
    )
    parser.add_argument(
        "--stop-rag-when-scenarios-complete",
        action="store_true",
        help="control 和命名 SSE 场景全部结束后停止派发背景 RAG。",
    )
    parser.add_argument(
        "--user-limit",
        type=int,
        default=0,
        help="只使用配置中的前 N 个身份；0 表示全部。P0-A 使用 1。",
    )
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--query", default="请说明当前知识库的主要内容，并给出来源。")
    parser.add_argument("--think-min-seconds", type=float, default=1.0)
    parser.add_argument("--think-max-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--min-success-rate", type=float, default=0.99)
    parser.add_argument("--max-p95-ms", type=float, default=30000.0)
    parser.add_argument("--min-global-peak-active-requests", type=int, default=0)
    parser.add_argument(
        "--max-global-peak-active-requests",
        type=int,
        default=0,
        help="0 表示不限制全局在途请求峰值上界。",
    )
    parser.add_argument("--allow-capacity-rejections", action="store_true")
    parser.add_argument("--min-capacity-rejections", type=int, default=0)
    parser.add_argument("--max-capacity-rejections", type=int, default=0)
    parser.add_argument(
        "--report",
        default="reports/agent-task-plan-load-report.json",
    )
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency 必须至少为 1")
    if (
        not args.skip_rag
        and args.request_count is None
        and args.duration_seconds is None
    ):
        parser.error("必须提供 --request-count 或 --duration-seconds")
    if args.request_count is not None and args.duration_seconds is not None:
        parser.error("固定次数与时长模式不能同时启用")
    if args.request_count is not None and args.request_count < 1:
        parser.error("--request-count 必须至少为 1")
    if args.duration_seconds is not None and args.duration_seconds < 1:
        parser.error("--duration-seconds 必须至少为 1")
    if args.duration_seconds is not None and args.max_request_count is None:
        parser.error("时长模式必须同时提供 --max-request-count 作为费用保险丝")
    if args.max_request_count is not None and args.max_request_count < 1:
        parser.error("--max-request-count 必须至少为 1")
    if args.user_limit < 0:
        parser.error("--user-limit 不能为负数")
    if args.min_global_peak_active_requests < 0:
        parser.error("--min-global-peak-active-requests 不能为负数")
    if args.max_global_peak_active_requests < 0:
        parser.error("--max-global-peak-active-requests 不能为负数")
    if (
        args.max_global_peak_active_requests > 0
        and args.min_global_peak_active_requests
        > args.max_global_peak_active_requests
    ):
        parser.error("全局在途峰值下界不能大于上界")
    if not 0 <= args.min_capacity_rejections <= args.max_capacity_rejections:
        parser.error("capacity rejection 下界必须小于等于上界")
    if not args.allow_capacity_rejections and args.max_capacity_rejections != 0:
        parser.error("允许 429 时必须显式增加 --allow-capacity-rejections")
    report = asyncio.run(run(args))
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, ensure_ascii=False, indent=2))
    print(f"report={target.resolve()}")
    print("agent_task_plan_load_acceptance=passed")


if __name__ == "__main__":
    main()
