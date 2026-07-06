from __future__ import annotations

import argparse
import getpass
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))


@dataclass(frozen=True)
class LoginResult:
    """登录成功后的凭证信息。

    access_token 用于后续 /auth/me 和 /rag/chat 请求；refresh_token 当前脚本只展示
    是否存在，不参与刷新流程，避免交互脚本职责过重。
    """

    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class ToolTestUser:
    """15-7 工具权限完整验收用的可登录用户。"""

    username: str
    password: str
    user_id: str
    department_code: str | None
    department_role_code: str | None
    global_role_code: str | None = None
    app_role: str = "user"


TOOL_TEST_USERS = {
    "reader": ToolTestUser(
        username="tool_reader",
        password="Reader123456!",
        user_id="tool_user_15_7_reader",
        department_code="development",
        department_role_code="department_reader",
    ),
    "editor": ToolTestUser(
        username="tool_editor",
        password="Editor123456!",
        user_id="tool_user_15_7_editor",
        department_code="development",
        department_role_code="department_editor",
    ),
    "manager": ToolTestUser(
        username="tool_manager",
        password="Manager123456!",
        user_id="tool_user_15_7_manager",
        department_code="development",
        department_role_code="department_document_manager",
    ),
    "admin": ToolTestUser(
        username="tool_admin",
        password="Admin123456!",
        user_id="tool_user_15_7_admin",
        department_code="development",
        department_role_code=None,
        global_role_code="system_admin",
        app_role="admin",
    ),
    "unscoped": ToolTestUser(
        username="tool_unscoped",
        password="Unscoped123456!",
        user_id="tool_user_15_7_unscoped",
        department_code="development",
        department_role_code=None,
    ),
}


def parse_args() -> argparse.Namespace:
    """解析交互式多轮 RAG Agent 测试脚本参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "Login first, then run an interactive multi-turn RAG Agent test. "
            "Type exit to stop."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="FastAPI 服务地址。",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="登录用户名或邮箱，对应 /auth/login 的 username_or_email。",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="登录密码。不传时会在终端隐藏输入。",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="多轮对话 session_id。不传时自动生成。",
    )
    parser.add_argument(
        "--mode",
        choices=["vector", "keyword", "hybrid"],
        default="hybrid",
        help="RAG 检索模式。",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回 sources 数量上限。",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=10,
        help="每个召回源候选数量。",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="最低文档分数。",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="单次 HTTP 请求超时时间。",
    )
    parser.add_argument(
        "--show-source-content",
        action="store_true",
        help="打印 sources 的 content_preview。",
    )
    parser.add_argument(
        "--stream-events",
        action="store_true",
        help=(
            "使用 /rag/chat/stream/events 结构化 SSE 流式接口。"
            "不加时仍测试非流式 /rag/chat。"
        ),
    )
    parser.add_argument(
        "--show-stream-events",
        action="store_true",
        help="流式模式下打印每个 SSE event 名称，便于观察 Prompt Guard 事件。",
    )
    parser.add_argument(
        "--manual-confirm-tool-approvals",
        action="store_true",
        help="交互模式下生成工具执行确认单 后，提示人工输入 true；输入 true 后调用确认接口执行。",
    )
    parser.add_argument(
        "--max-sources-print",
        type=int,
        default=5,
        help="每轮最多打印多少个 source 摘要。",
    )
    parser.add_argument(
        "--seed-15-7-tool-users",
        action="store_true",
        help="在 PostgreSQL 中创建/更新 15-7 工具权限测试用户和角色绑定。",
    )
    parser.add_argument(
        "--print-15-7-tool-users",
        action="store_true",
        help="打印脚本内置的 15-7 测试用户名和密码。",
    )
    parser.add_argument(
        "--run-15-7-tool-flow",
        action="store_true",
        help="自动执行登录 -> /rag/chat 生成执行确认单 -> 错误确认拒绝 -> 正确确认执行的完整流程。",
    )
    parser.add_argument(
        "--tool-flow-run-id",
        default=None,
        help="完整流程使用的 run_id。不传时自动生成，目标文件名会包含该值。",
    )
    parser.add_argument(
        "--tool-flow-department",
        default="development",
        choices=["development", "art", "product_planning"],
        help="完整流程目标部门目录。默认 development。",
    )
    parser.add_argument(
        "--tool-flow-knowledge-base-dir",
        default="docs/knowledge-base-acl-test",
        help="用于本地校验目标文件是否创建/删除的知识库根目录。",
    )
    parser.add_argument(
        "--keep-tool-flow-file",
        action="store_true",
        help="完整流程结束后保留创建的测试文件，不执行 delete 确认。",
    )
    return parser.parse_args()


def post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """发送 JSON POST 请求并解析 JSON 响应。

    这里使用 Python 标准库而不是 curl.exe，避免 Windows PowerShell 对 JSON 双引号
    的原生命令传参问题。
    """

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            **(headers or {}),
        },
    )
    return send_json_request(request=request, timeout_seconds=timeout_seconds)


def get_json(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    """发送 JSON GET 请求并解析 JSON 响应。"""

    request = Request(url=url, method="GET", headers=headers)
    return send_json_request(request=request, timeout_seconds=timeout_seconds)


def send_json_request(
    *,
    request: Request,
    timeout_seconds: float,
) -> dict[str, Any]:
    """执行 HTTP 请求并把失败响应整理成适合终端阅读的异常。"""

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP 请求失败: status={exc.code}, url={request.full_url}, body={error_body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"无法连接 FastAPI 服务: url={request.full_url}, error={exc}"
        ) from exc

    if not raw:
        return {}

    return json.loads(raw)


def login(
    *,
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: float,
) -> LoginResult:
    """调用 /auth/login，返回后续请求需要的 JWT access token。"""

    data = post_json(
        url=f"{base_url}/auth/login",
        payload={
            "username_or_email": username,
            "password": password,
        },
        timeout_seconds=timeout_seconds,
    )

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")

    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"登录响应缺少 access_token: {data}")

    if not isinstance(refresh_token, str):
        refresh_token = ""

    if not isinstance(expires_in, int):
        expires_in = 0

    return LoginResult(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


def get_current_user(
    *,
    base_url: str,
    access_token: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """调用 /auth/me，确认 access token 解析出的用户身份和部门范围。"""

    return get_json(
        url=f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout_seconds=timeout_seconds,
    )


def request_rag_chat(
    *,
    base_url: str,
    access_token: str,
    session_id: str,
    query: str,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    """调用 /rag/chat，复用同一个 session_id 形成多轮对话。"""

    return post_json(
        url=f"{base_url}/rag/chat",
        payload={
            "session_id": session_id,
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "min_score": min_score,
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout_seconds=timeout_seconds,
    )


def confirm_tool_approval(
    *,
    base_url: str,
    access_token: str,
    approval_id: str,
    confirmation_text: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """调用独立确认接口，执行已经生成的 Agent 工具计划。"""

    return post_json(
        url=f"{base_url}/agent/tool-approvals/{approval_id}/confirm",
        payload={"confirmation_text": confirmation_text},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout_seconds=timeout_seconds,
    )


def request_rag_chat_stream_events(
    *,
    base_url: str,
    access_token: str,
    session_id: str,
    query: str,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    timeout_seconds: float,
) -> Iterator[tuple[str, Any]]:
    """调用 /rag/chat/stream/events，并逐个解析结构化 SSE 事件。

    这个入口用于从登录开始验收完整流式链路，尤其是 Prompt-Injection
    输出防护中的 answer_delta / guard_sanitized / guard_blocked 事件。
    """

    payload = {
        "session_id": session_id,
        "query": query,
        "mode": mode,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "min_score": min_score,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url=f"{base_url}/rag/chat/stream/events",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {access_token}",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            yield from iter_sse_events(response)
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP 请求失败: status={exc.code}, url={request.full_url}, body={error_body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"无法连接 FastAPI 服务: url={request.full_url}, error={exc}"
        ) from exc


def iter_sse_events(response: Any) -> Iterator[tuple[str, Any]]:
    """把 text/event-stream 响应解析成 (event, data)。

    FastAPI 当前每个事件都是 event + data + 空行。这里仍按 SSE 通用格式
    解析，避免以后 data 出现多行时脚本马上失效。
    """

    event_name = "message"
    data_lines: list[str] = []

    while True:
        raw_line = response.readline()
        if raw_line == b"":
            if data_lines:
                yield event_name, parse_sse_data(data_lines)
            return

        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                yield event_name, parse_sse_data(data_lines)
            event_name = "message"
            data_lines = []
            continue

        if line.startswith(":"):
            continue

        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue

        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())


def parse_sse_data(data_lines: list[str]) -> Any:
    """解析 SSE data 字段，JSON 事件返回 dict，普通文本原样返回。"""

    data_text = "\n".join(data_lines)
    try:
        return json.loads(data_text)
    except json.JSONDecodeError:
        return data_text


def print_user_summary(user: dict[str, Any]) -> None:
    """打印登录后服务端识别出的用户上下文摘要。"""

    print("current_user:")
    print(f"  user_id={user.get('user_id')}")
    print(f"  auth_source={user.get('auth_source')}")
    print(f"  role={user.get('role')}")
    print(f"  permissions={','.join(str(item) for item in user.get('permissions', []))}")
    print(
        "  departments="
        f"{','.join(str(item) for item in user.get('department_codes', []))}"
    )
    print(f"  primary_department={user.get('primary_department_code')}")


def print_sources(
    *,
    sources: object,
    max_sources_print: int,
    show_source_content: bool,
) -> None:
    """打印 sources 摘要，重点观察部门权限 metadata 是否符合预期。"""

    if not isinstance(sources, list):
        print("sources=<invalid>")
        return

    print(f"source_count={len(sources)}")
    for index, source in enumerate(sources[:max_sources_print], start=1):
        if not isinstance(source, dict):
            continue

        metadata = source.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        allowed_departments = metadata.get("allowed_departments") or []
        allowed_users = metadata.get("allowed_users") or []
        print(
            f"  source_{index}: "
            f"id={source.get('id')} "
            f"retrieval_sources={source.get('retrieval_sources')} "
            f"title={source.get('title')} "
            f"score={source.get('score')} "
            f"visibility={metadata.get('visibility')} "
            f"allowed_departments={allowed_departments} "
            f"allowed_users={allowed_users} "
            f"permission_source={metadata.get('permission_source')}"
        )

        if show_source_content:
            print(f"    content_preview={source.get('content_preview')}")


async def seed_15_7_tool_users() -> None:
    """创建/更新 15-7 工具权限测试用户、部门绑定和角色绑定。"""

    from sqlalchemy import text

    from fast_app.core.config import get_settings
    from fast_app.db.session import create_database_engine, create_session_factory
    from fast_app.services.auth_crypto import hash_password

    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            await assert_required_tool_roles_exist(session)
            for label, user in TOOL_TEST_USERS.items():
                password_hash = hash_password(user.password)
                user_id = await upsert_tool_test_user(
                    session=session,
                    user=user,
                    password_hash=password_hash,
                )
                if user.department_code is not None:
                    await upsert_user_department(
                        session=session,
                        user_id=user_id,
                        department_code=user.department_code,
                    )
                if user.department_role_code is not None and user.department_code is not None:
                    await upsert_user_department_role(
                        session=session,
                        user_id=user_id,
                        department_code=user.department_code,
                        role_code=user.department_role_code,
                    )
                if user.global_role_code is not None:
                    await upsert_user_global_role(
                        session=session,
                        user_id=user_id,
                        role_code=user.global_role_code,
                    )
                print(
                    "seed_user=passed "
                    f"label={label} username={user.username} "
                    f"department={user.department_code or '<none>'} "
                    f"department_role={user.department_role_code or '<none>'} "
                    f"global_role={user.global_role_code or '<none>'}"
                )

            await session.commit()
    finally:
        await engine.dispose()


async def assert_required_tool_roles_exist(session: Any) -> None:
    """确认 15-7 Alembic 种子角色已经存在。"""

    from sqlalchemy import text

    required = {
        "system_admin",
        "department_reader",
        "department_editor",
        "department_document_manager",
    }
    rows = (await session.execute(text("select code from roles"))).all()
    existing = {str(row[0]) for row in rows}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(
            "缺少 15-7 工具权限角色，请先运行 Alembic 迁移到 20260704_0005: "
            + ",".join(missing)
        )


async def upsert_tool_test_user(
    *,
    session: Any,
    user: ToolTestUser,
    password_hash: str,
) -> str:
    """按 username 幂等创建测试用户，并刷新密码和基础权限。"""

    from sqlalchemy import text

    row = (
        await session.execute(
            text(
                """
                insert into users
                    (id, username, email, display_name, password_hash, role, status, permissions_json)
                values
                    (:id, :username, :email, :display_name, :password_hash, :role, 'active', cast(:permissions_json as jsonb))
                on conflict (username) do update set
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    status = 'active',
                    permissions_json = excluded.permissions_json,
                    updated_at = now()
                returning id
                """
            ),
            {
                "id": user.user_id,
                "username": user.username,
                "email": f"{user.username}@example.com",
                "display_name": user.username,
                "password_hash": password_hash,
                "role": user.app_role,
                "permissions_json": json.dumps(["rag:chat"], ensure_ascii=False),
            },
        )
    ).one()
    return str(row[0])


async def upsert_user_department(
    *,
    session: Any,
    user_id: str,
    department_code: str,
) -> None:
    """幂等绑定用户所属部门，并把该部门设置为主部门。"""

    from sqlalchemy import text

    await session.execute(
        text(
            """
            update user_departments
            set is_primary = false
            where user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    await session.execute(
        text(
            """
            insert into user_departments (id, user_id, department_code, is_primary)
            values (:id, :user_id, :department_code, true)
            on conflict (user_id, department_code) do update set
                is_primary = true
            """
        ),
        {
            "id": build_stable_id("user_dept", user_id, department_code),
            "user_id": user_id,
            "department_code": department_code,
        },
    )


async def upsert_user_department_role(
    *,
    session: Any,
    user_id: str,
    department_code: str,
    role_code: str,
) -> None:
    """幂等绑定用户在某部门下的工具权限角色。"""

    from sqlalchemy import text

    await session.execute(
        text(
            """
            insert into user_department_roles (id, user_id, department_code, role_id)
            select :id, :user_id, :department_code, roles.id
            from roles
            where roles.code = :role_code
            on conflict (user_id, department_code, role_id) do nothing
            """
        ),
        {
            "id": build_stable_id("udr", user_id, department_code, role_code),
            "user_id": user_id,
            "department_code": department_code,
            "role_code": role_code,
        },
    )


async def upsert_user_global_role(
    *,
    session: Any,
    user_id: str,
    role_code: str,
) -> None:
    """幂等绑定用户全局角色。"""

    from sqlalchemy import text

    await session.execute(
        text(
            """
            insert into user_roles (id, user_id, role_id)
            select :id, :user_id, roles.id
            from roles
            where roles.code = :role_code
            on conflict (user_id, role_id) do nothing
            """
        ),
        {
            "id": build_stable_id("ur", user_id, role_code),
            "user_id": user_id,
            "role_code": role_code,
        },
    )


def build_stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def print_15_7_tool_users() -> None:
    """打印内置测试账号，便于手工登录验证。"""

    print("15-7 tool users:")
    for label, user in TOOL_TEST_USERS.items():
        print(
            f"  {label}: username={user.username} password={user.password} "
            f"department={user.department_code or '<none>'} "
            f"department_role={user.department_role_code or '<none>'} "
            f"global_role={user.global_role_code or '<none>'}"
        )


def run_interactive_loop(
    *,
    base_url: str,
    access_token: str,
    session_id: str,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    timeout_seconds: float,
    max_sources_print: int,
    show_source_content: bool,
    stream_events: bool,
    show_stream_events: bool,
    manual_confirm_tool_approvals: bool,
) -> None:
    """启动终端交互循环，直到用户输入 exit / quit。"""

    print("输入问题后按 Enter；输入 exit 或 quit 结束。")
    if stream_events:
        print("stream_endpoint=/rag/chat/stream/events")
        print("answer events: answer_delta / guard_sanitized / guard_blocked")
    else:
        print("endpoint=/rag/chat")

    while True:
        query = input("query> ").strip()
        if query.lower() in {"exit", "quit"}:
            print("bye")
            return

        if not query:
            continue

        if stream_events:
            run_stream_events_turn(
                base_url=base_url,
                access_token=access_token,
                session_id=session_id,
                query=query,
                mode=mode,
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                timeout_seconds=timeout_seconds,
                max_sources_print=max_sources_print,
                show_source_content=show_source_content,
                show_stream_events=show_stream_events,
                manual_confirm_tool_approvals=manual_confirm_tool_approvals,
            )
            continue

        try:
            response = request_rag_chat(
                base_url=base_url,
                access_token=access_token,
                session_id=session_id,
                query=query,
                mode=mode,
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            print(f"request_failed={exc}")
            continue

        print(f"request_id={response.get('request_id')}")
        print(f"trace_id={response.get('trace_id')}")
        print(f"effective_query={response.get('query')}")
        print("answer:")
        print(response.get("answer"))
        print_sources(
            sources=response.get("sources"),
            max_sources_print=max_sources_print,
            show_source_content=show_source_content,
        )
        maybe_prompt_and_confirm_tool_approval(
            base_url=base_url,
            access_token=access_token,
            approval_id=response.get("tool_approval_id"),
            answer_text=str(response.get("answer") or ""),
            timeout_seconds=timeout_seconds,
            manual_confirm_tool_approvals=manual_confirm_tool_approvals,
        )


def run_stream_events_turn(
    *,
    base_url: str,
    access_token: str,
    session_id: str,
    query: str,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    timeout_seconds: float,
    max_sources_print: int,
    show_source_content: bool,
    show_stream_events: bool,
    manual_confirm_tool_approvals: bool,
) -> None:
    """执行一轮结构化流式对话，并突出打印 Prompt Guard 相关事件。"""

    answer_parts: list[str] = []
    tool_approval_id: str | None = None
    blocked = False
    sanitized = False

    try:
        events = request_rag_chat_stream_events(
            base_url=base_url,
            access_token=access_token,
            session_id=session_id,
            query=query,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            timeout_seconds=timeout_seconds,
        )

        print("answer:")
        for event_name, data in events:
            if show_stream_events:
                print(f"\n[event={event_name}]")

            if event_name == "sources":
                sources = data.get("sources") if isinstance(data, dict) else data
                print_sources(
                    sources=sources,
                    max_sources_print=max_sources_print,
                    show_source_content=show_source_content,
                )
                print("answer:")
                continue

            if event_name == "tool_approval_created":
                if isinstance(data, dict):
                    raw_approval_id = data.get("approval_id")
                    if isinstance(raw_approval_id, str):
                        tool_approval_id = raw_approval_id
                    print("\ntool_approval_created:")
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                continue

            if event_name == "tool_confirmation_required":
                print("\ntool_confirmation_required:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                continue

            if event_name == "answer_delta":
                text = extract_stream_text(data)
                answer_parts.append(text)
                print(text, end="", flush=True)
                continue

            if event_name == "guard_sanitized":
                sanitized = True
                text = extract_stream_text(data)
                answer_parts.append(text)
                print(text, end="", flush=True)
                print("\n[prompt_guard=sanitized]")
                print_guard_summary(data)
                continue

            if event_name == "guard_blocked":
                blocked = True
                text = extract_stream_text(data)
                answer_parts.append(text)
                print(text, end="", flush=True)
                print("\n[prompt_guard=blocked]")
                print_guard_summary(data)
                continue

            if event_name == "error":
                print("\nstream_error:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return

            if event_name == "done":
                print("\nstream_done=passed")
                break

        print(f"answer_length={len(''.join(answer_parts))}")
        print(f"guard_sanitized={sanitized} guard_blocked={blocked}")
        maybe_prompt_and_confirm_tool_approval(
            base_url=base_url,
            access_token=access_token,
            approval_id=tool_approval_id,
            answer_text="".join(answer_parts),
            timeout_seconds=timeout_seconds,
            manual_confirm_tool_approvals=manual_confirm_tool_approvals,
        )

    except RuntimeError as exc:
        print(f"request_failed={exc}")


def extract_stream_text(data: Any) -> str:
    """从 answer_delta / guard_* 事件 data 中取出要展示的文本。"""

    if isinstance(data, dict):
        text = data.get("text")
        if isinstance(text, str):
            return text

        answer = data.get("answer")
        if isinstance(answer, str):
            return answer

    if isinstance(data, str):
        return data

    return ""


def maybe_prompt_and_confirm_tool_approval(
    *,
    base_url: str,
    access_token: str,
    approval_id: object,
    answer_text: str,
    timeout_seconds: float,
    manual_confirm_tool_approvals: bool,
) -> None:
    """交互模式下让人输入 true 后再调用确认接口。

    后端仍然校验完整 confirmation_text；这里的 true 只是 CLI 层的人机确认门槛。
    """

    if not manual_confirm_tool_approvals:
        return

    if not isinstance(approval_id, str) or not approval_id:
        return

    confirmation_text = extract_confirmation_text(answer_text)
    print("")
    print(f"detected_tool_approval_id={approval_id}")
    if confirmation_text is None:
        print("manual_confirm=unavailable reason=confirmation_text_not_found")
        return

    print("manual_confirm_prompt=输入 true 后执行该工具执行确认单；输入其它内容跳过。")
    user_input = input("confirm true?> ").strip()
    if user_input != "true":
        print("manual_confirm=skipped")
        return

    try:
        response = confirm_tool_approval(
            base_url=base_url,
            access_token=access_token,
            approval_id=approval_id,
            confirmation_text=confirmation_text,
            timeout_seconds=timeout_seconds,
        )
    except RuntimeError as exc:
        print(f"manual_confirm=failed error={exc}")
        return

    print("manual_confirm=passed")
    print(json.dumps(response, ensure_ascii=False, indent=2))


def print_guard_summary(data: Any) -> None:
    """打印 Prompt Guard 决策摘要，便于终端验收注入防护是否触发。"""

    if not isinstance(data, dict):
        return

    print(
        "guard_detail: "
        f"action={data.get('action')} "
        f"risk_level={data.get('risk_level')} "
        f"categories={data.get('categories')} "
        f"reason={data.get('reason')}"
    )


def run_15_7_tool_flow(
    *,
    base_url: str,
    timeout_seconds: float,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    run_id: str,
    department: str,
    knowledge_base_dir: str,
    keep_file: bool,
) -> None:
    """自动验收 15-7 从登录到工具计划确认执行的完整 HTTP 流程。"""

    target_path = f"{department}/cli-full-flow-{run_id}.md"
    target_file = Path(knowledge_base_dir) / target_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.exists():
        raise RuntimeError(
            f"测试目标文件已存在，为避免覆盖请换 --tool-flow-run-id: {target_file}"
        )

    print("tool_flow=start")
    print(f"base_url={base_url}")
    print(f"target_path={target_path}")
    print(f"local_target_file={target_file}")

    manager_token = login_tool_user(
        base_url=base_url,
        user=TOOL_TEST_USERS["manager"],
        timeout_seconds=timeout_seconds,
    )
    reader_token = login_tool_user(
        base_url=base_url,
        user=TOOL_TEST_USERS["reader"],
        timeout_seconds=timeout_seconds,
    )
    editor_token = login_tool_user(
        base_url=base_url,
        user=TOOL_TEST_USERS["editor"],
        timeout_seconds=timeout_seconds,
    )
    admin_token = login_tool_user(
        base_url=base_url,
        user=TOOL_TEST_USERS["admin"],
        timeout_seconds=timeout_seconds,
    )
    unscoped_token = login_tool_user(
        base_url=base_url,
        user=TOOL_TEST_USERS["unscoped"],
        timeout_seconds=timeout_seconds,
    )

    create_content = (
        f"# CLI Full Flow {run_id}\n\n"
        "这是 15-7 CLI 自动验收创建的测试文档。\n"
        "用途：验证 manager 用户可以生成执行确认单 并确认执行 create。"
    )
    create_response = request_tool_query(
        base_url=base_url,
        access_token=manager_token,
        query=(
            f"请创建 {target_path}，内容是：{create_content}"
        ),
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="manager_create_approval",
    )
    create_approval_id, create_confirmation = assert_tool_approval_created(
        create_response,
        label="manager_create_approval",
    )
    assert_wrong_confirmation_rejected(
        base_url=base_url,
        access_token=manager_token,
        approval_id=create_approval_id,
        timeout_seconds=timeout_seconds,
        label="manager_create_wrong_confirmation",
    )
    create_confirm = confirm_tool_approval(
        base_url=base_url,
        access_token=manager_token,
        approval_id=create_approval_id,
        confirmation_text=create_confirmation,
        timeout_seconds=timeout_seconds,
    )
    assert_confirm_executed(create_confirm, label="manager_create_confirm")
    assert_file_state(
        target_file=target_file,
        should_exist=True,
        contains="CLI 自动验收创建",
        label="manager_create_file",
    )

    reader_response = request_tool_query(
        base_url=base_url,
        access_token=reader_token,
        query=(
            f"请修改 {target_path}，内容改成：reader 不应该能修改这个文档"
        ),
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="reader_update_denied",
    )
    assert_tool_denied(reader_response, label="reader_update_denied")

    unscoped_response = request_tool_query(
        base_url=base_url,
        access_token=unscoped_token,
        query=(
            f"请创建 {department}/cli-unscoped-{run_id}.md，内容是："
            "unscoped 用户不应该能创建文档"
        ),
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="unscoped_create_denied",
    )
    assert_tool_denied(unscoped_response, label="unscoped_create_denied")

    editor_response = request_tool_query(
        base_url=base_url,
        access_token=editor_token,
        query=(
            f"请修改 {target_path}，内容改成："
            f"# CLI Full Flow {run_id}\n\neditor 只能生成 update approval，不能在本脚本中确认执行。"
        ),
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="editor_update_approval",
    )
    assert_tool_approval_created(editor_response, label="editor_update_approval")

    admin_content = (
        f"# CLI Full Flow {run_id}\n\n"
        "admin 已确认执行 update。"
    )
    admin_update_response = request_tool_query(
        base_url=base_url,
        access_token=admin_token,
        query=f"请修改 {target_path}，内容改成：{admin_content}",
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="admin_update_approval",
    )
    admin_update_approval_id, admin_update_confirmation = assert_tool_approval_created(
        admin_update_response,
        label="admin_update_approval",
    )
    admin_update_confirm = confirm_tool_approval(
        base_url=base_url,
        access_token=admin_token,
        approval_id=admin_update_approval_id,
        confirmation_text=admin_update_confirmation,
        timeout_seconds=timeout_seconds,
    )
    assert_confirm_executed(admin_update_confirm, label="admin_update_confirm")
    assert_file_state(
        target_file=target_file,
        should_exist=True,
        contains="admin 已确认执行 update",
        label="admin_update_file",
    )

    if keep_file:
        print("manager_delete=skipped reason=keep_tool_flow_file")
        print("tool_flow=passed")
        return

    delete_response = request_tool_query(
        base_url=base_url,
        access_token=manager_token,
        query=f"请删除 {target_path}，原因是 15-7 CLI 完整流程验收结束",
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
        label="manager_delete_approval",
    )
    delete_approval_id, delete_confirmation = assert_tool_approval_created(
        delete_response,
        label="manager_delete_approval",
    )
    delete_confirm = confirm_tool_approval(
        base_url=base_url,
        access_token=manager_token,
        approval_id=delete_approval_id,
        confirmation_text=delete_confirmation,
        timeout_seconds=timeout_seconds,
    )
    assert_confirm_executed(delete_confirm, label="manager_delete_confirm")
    assert_file_state(
        target_file=target_file,
        should_exist=False,
        contains=None,
        label="manager_delete_file",
    )
    print("tool_flow=passed")


def login_tool_user(
    *,
    base_url: str,
    user: ToolTestUser,
    timeout_seconds: float,
) -> str:
    login_result = login(
        base_url=base_url,
        username=user.username,
        password=user.password,
        timeout_seconds=timeout_seconds,
    )
    current_user = get_current_user(
        base_url=base_url,
        access_token=login_result.access_token,
        timeout_seconds=timeout_seconds,
    )
    departments = [str(item) for item in current_user.get("department_codes", [])]
    if user.department_code is not None and user.department_code not in departments:
        raise RuntimeError(
            f"{user.username} /auth/me 部门不正确: expected={user.department_code}, actual={departments}"
        )
    print(
        "tool_user_login=passed "
        f"username={user.username} user_id={current_user.get('user_id')} "
        f"role={current_user.get('role')} departments={','.join(departments)}"
    )
    return login_result.access_token


def request_tool_query(
    *,
    base_url: str,
    access_token: str,
    query: str,
    mode: str,
    top_k: int,
    candidate_k: int,
    min_score: float,
    timeout_seconds: float,
    label: str,
) -> dict[str, Any]:
    response = request_rag_chat(
        base_url=base_url,
        access_token=access_token,
        session_id=f"{label}-{uuid4().hex[:8]}",
        query=query,
        mode=mode,
        top_k=top_k,
        candidate_k=candidate_k,
        min_score=min_score,
        timeout_seconds=timeout_seconds,
    )
    print(
        f"{label}=response "
        f"tool_approval_id={response.get('tool_approval_id')} "
        f"tool_confirmation_required={response.get('tool_confirmation_required')}"
    )
    return response


def assert_tool_approval_created(response: dict[str, Any], *, label: str) -> tuple[str, str]:
    approval_id = response.get("tool_approval_id")
    if not isinstance(approval_id, str) or not approval_id:
        raise RuntimeError(
            f"{label}: 未生成 tool_approval_id。请确认服务端已启用 "
            "AGENT_DOCUMENT_TOOLS_ENABLED=true，且 planner 能识别该文档动作。"
            f" answer={response.get('answer')!r}"
        )
    if response.get("tool_confirmation_required") is not True:
        raise RuntimeError(
            f"{label}: 预期 tool_confirmation_required=True，实际为 "
            f"{response.get('tool_confirmation_required')!r}"
        )

    confirmation_text = extract_confirmation_text(str(response.get("answer") or ""))
    if confirmation_text is None:
        raise RuntimeError(f"{label}: answer 中没有 confirmation_text")

    print(f"{label}=passed approval_id={approval_id}")
    return approval_id, confirmation_text


def assert_tool_denied(response: dict[str, Any], *, label: str) -> None:
    if response.get("tool_approval_id") is not None:
        raise RuntimeError(f"{label}: 被拒绝请求不应生成 tool_approval_id")
    if response.get("tool_confirmation_required") is not False:
        raise RuntimeError(
            f"{label}: 被拒绝请求不应要求确认，actual={response.get('tool_confirmation_required')!r}"
        )
    answer = str(response.get("answer") or "")
    if "拒绝" not in answer and "没有" not in answer:
        raise RuntimeError(f"{label}: 拒绝响应文本不符合预期 answer={answer!r}")
    print(f"{label}=passed")


def assert_wrong_confirmation_rejected(
    *,
    base_url: str,
    access_token: str,
    approval_id: str,
    timeout_seconds: float,
    label: str,
) -> None:
    try:
        confirm_tool_approval(
            base_url=base_url,
            access_token=access_token,
            approval_id=approval_id,
            confirmation_text="WRONG CONFIRMATION TEXT",
            timeout_seconds=timeout_seconds,
        )
    except RuntimeError as exc:
        print(f"{label}=passed error={exc}")
        return
    raise RuntimeError(f"{label}: 错误 confirmation_text 不应执行成功")


def assert_confirm_executed(response: dict[str, Any], *, label: str) -> None:
    if response.get("executed") is not True:
        raise RuntimeError(f"{label}: expected executed=True actual={response}")
    if response.get("status") != "executed":
        raise RuntimeError(f"{label}: expected status=executed actual={response}")
    print(f"{label}=passed approval_id={response.get('approval_id')}")


def assert_file_state(
    *,
    target_file: Path,
    should_exist: bool,
    contains: str | None,
    label: str,
) -> None:
    exists = target_file.exists()
    if exists != should_exist:
        raise RuntimeError(
            f"{label}: 文件状态不符合预期 expected_exists={should_exist} "
            f"actual_exists={exists} path={target_file}"
        )
    if should_exist and contains is not None:
        content = target_file.read_text(encoding="utf-8")
        if contains not in content:
            raise RuntimeError(f"{label}: 文件内容未包含预期片段 {contains!r}")
    print(f"{label}=passed path={target_file}")


def extract_confirmation_text(answer: str) -> str | None:
    match = re.search(r"CONFIRM EXECUTE TOOL APPROVAL\s+tool_approval_[0-9]{14}_[a-f0-9]{12}", answer)
    return match.group(0) if match is not None else None


def main() -> int:
    """脚本入口：登录、验证身份，然后进入多轮 RAG Agent 终端对话。"""

    args = parse_args()
    base_url = args.base_url.rstrip("/")

    try:
        if args.print_15_7_tool_users:
            print_15_7_tool_users()

        if args.seed_15_7_tool_users:
            asyncio.run(seed_15_7_tool_users())
            print("seed_15_7_tool_users=passed")

        if args.run_15_7_tool_flow:
            run_id = args.tool_flow_run_id or uuid4().hex[:8]
            run_15_7_tool_flow(
                base_url=base_url,
                timeout_seconds=args.timeout_seconds,
                mode=args.mode,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
                min_score=args.min_score,
                run_id=run_id,
                department=args.tool_flow_department,
                knowledge_base_dir=args.tool_flow_knowledge_base_dir,
                keep_file=args.keep_tool_flow_file,
            )
            return 0

        if args.seed_15_7_tool_users or args.print_15_7_tool_users:
            return 0

        if not args.username:
            raise RuntimeError(
                "交互模式需要传入 --username；如果只想创建测试用户，请使用 "
                "--seed-15-7-tool-users。"
            )

        password = args.password or getpass.getpass("password> ")
        session_id = args.session_id or f"rag-agent-cli-{uuid4().hex[:8]}"

        login_result = login(
            base_url=base_url,
            username=args.username,
            password=password,
            timeout_seconds=args.timeout_seconds,
        )
        print("login=passed")
        print(f"token_type=bearer expires_in={login_result.expires_in}")
        print(f"refresh_token_present={bool(login_result.refresh_token)}")

        current_user = get_current_user(
            base_url=base_url,
            access_token=login_result.access_token,
            timeout_seconds=args.timeout_seconds,
        )
        print_user_summary(current_user)

        print(f"base_url={base_url}")
        print(f"session_id={session_id}")
        print(f"mode={args.mode} top_k={args.top_k} candidate_k={args.candidate_k}")
        print(f"stream_events={args.stream_events}")
        run_interactive_loop(
            base_url=base_url,
            access_token=login_result.access_token,
            session_id=session_id,
            mode=args.mode,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            min_score=args.min_score,
            timeout_seconds=args.timeout_seconds,
            max_sources_print=args.max_sources_print,
            show_source_content=args.show_source_content,
            stream_events=args.stream_events,
            show_stream_events=args.show_stream_events,
            manual_confirm_tool_approvals=args.manual_confirm_tool_approvals,
        )
        return 0

    except RuntimeError as exc:
        print(f"script_failed={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
