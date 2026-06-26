import argparse
from uuid import uuid4

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive HTTP smoke test for multi-turn RAG Agent /rag/chat.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="FastAPI service base URL.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Conversation session_id. Defaults to a generated value.",
    )
    # 支持 --user-id 测试隔离。
    parser.add_argument(
        "--user-id",
        default="anonymous",
        help="Value sent as X-Demo-User-Id for phase 14-9 user/session isolation.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Value sent as X-API-Key when AUTH_ENABLED=true.",
    )
    parser.add_argument(
        "--bearer-token",
        default=None,
        help="Value sent as Authorization: Bearer when AUTH_ENABLED=true.",
    )
    parser.add_argument(
        "--mode",
        default="hybrid",
        choices=["vector", "keyword", "hybrid"],
        help="Retrieval mode.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of sources requested from /rag/chat.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum source score.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="HTTP request timeout.",
    )
    return parser.parse_args()


def print_source_summary(body: dict[str, object]) -> None:
    sources = body.get("sources")
    if not isinstance(sources, list):
        print("source_count=<invalid>")
        return

    print(f"source_count={len(sources)}")
    for index, source in enumerate(sources[:3], start=1):
        if not isinstance(source, dict):
            continue

        source_id = source.get("id")
        title = source.get("title")
        score = source.get("score")
        print(f"source_{index}=id:{source_id} title:{title} score:{score}")


def request_rag_chat(
    base_url: str,
    user_id: str,
    api_key: str | None,
    bearer_token: str | None,
    session_id: str,
    query: str,
    mode: str,
    top_k: int,
    min_score: float,
    timeout_seconds: float,
) -> dict[str, object]:
    payload = {
        "session_id": session_id,
        "query": query,
        "mode": mode,
        "top_k": top_k,
        "min_score": min_score,
    }
    headers = {"X-Demo-User-Id": user_id}
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    response = requests.post(
        f"{base_url.rstrip('/')}/rag/chat",
        json=payload,
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    args = parse_args()
    session_id = args.session_id or f"terminal-14-11-{uuid4().hex[:8]}"

    print(f"base_url={args.base_url.rstrip('/')}")
    print(f"user_id={args.user_id}")
    print(f"api_key_enabled={args.api_key is not None}")
    print(f"bearer_token_enabled={args.bearer_token is not None}")
    print(f"session_id={session_id}")
    print("输入问题后按 Enter；输入 exit 或 quit 结束。")

    while True:
        query = input("query> ").strip()
        if query.lower() in {"exit", "quit"}:
            return 0

        if not query:
            continue

        try:
            body = request_rag_chat(
                base_url=args.base_url,
                user_id=args.user_id,
                api_key=args.api_key,
                bearer_token=args.bearer_token,
                session_id=session_id,
                query=query,
                mode=args.mode,
                top_k=args.top_k,
                min_score=args.min_score,
                timeout_seconds=args.timeout_seconds,
            )
        except requests.RequestException as exc:
            print(f"request_failed={type(exc).__name__}: {exc}")
            continue

        print(f"effective_query={body.get('query')}")
        print(f"answer={body.get('answer')}")
        print_source_summary(body)


if __name__ == "__main__":
    raise SystemExit(main())
