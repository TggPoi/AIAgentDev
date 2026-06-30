from __future__ import annotations

import argparse
import getpass
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class LoginResult:
    """登录成功后的凭证信息。

    access_token 用于后续 /auth/me 和 /rag/chat 请求；refresh_token 当前脚本只展示
    是否存在，不参与刷新流程，避免交互脚本职责过重。
    """

    access_token: str
    refresh_token: str
    expires_in: int


def parse_args() -> argparse.Namespace:
    """解析交互式多轮 RAG Agent 测试脚本参数。"""

    parser = argparse.ArgumentParser(
        description=(
            "Login first, then run an interactive multi-turn /rag/chat test. "
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
        required=True,
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
        "--max-sources-print",
        type=int,
        default=5,
        help="每轮最多打印多少个 source 摘要。",
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
) -> None:
    """启动终端交互循环，直到用户输入 exit / quit。"""

    print("输入问题后按 Enter；输入 exit 或 quit 结束。")
    while True:
        query = input("query> ").strip()
        if query.lower() in {"exit", "quit"}:
            print("bye")
            return

        if not query:
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


def main() -> int:
    """脚本入口：登录、验证身份，然后进入多轮 RAG Agent 终端对话。"""

    args = parse_args()
    base_url = args.base_url.rstrip("/")
    password = args.password or getpass.getpass("password> ")
    session_id = args.session_id or f"rag-agent-cli-{uuid4().hex[:8]}"

    try:
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
        )
        return 0

    except RuntimeError as exc:
        print(f"script_failed={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
