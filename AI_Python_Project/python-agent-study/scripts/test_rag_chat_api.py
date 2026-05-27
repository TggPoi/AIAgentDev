import argparse
import json
import sys
from collections.abc import Iterator

import requests


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    """根据命令行参数构造 RagChatRequest 请求体。"""
    return {
        "query": args.query,
        "mode": args.mode,
        "top_k": args.top_k,
        "min_score": args.min_score,
    }


def print_response_json(resp: requests.Response) -> None:
    """打印 JSON 响应；如果不是 JSON，则打印原始文本。"""
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(resp.text)


def test_normal_chat(base_url: str, payload: dict[str, object]) -> None:
    """测试非流式 RAG 聊天接口。"""
    url = f"{base_url}/rag/chat"

    print("========== POST /rag/chat ==========")
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, json=payload, timeout=30)

    print(f"\nstatus: {resp.status_code}")
    print("response:")
    print_response_json(resp)
    resp.raise_for_status()


def iter_sse_lines(resp: requests.Response) -> Iterator[str]:
    """逐行读取 SSE 响应，过滤掉空行。"""
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            yield line


def test_stream_chat(base_url: str, payload: dict[str, object]) -> None:
    """测试流式 RAG 聊天接口，并实时打印 data token。"""
    url = f"{base_url}/rag/chat/stream"

    print("\n========== POST /rag/chat/stream ==========")
    print("stream output:")

    with requests.post(url, json=payload, stream=True, timeout=60) as resp:
        print(f"status: {resp.status_code}\n")
        resp.raise_for_status()

        current_event = "message"

        for line in iter_sse_lines(resp):
            if line.startswith("event:"):
                current_event = line.removeprefix("event:").strip()
                continue

            if not line.startswith("data:"):
                continue

            data = line.removeprefix("data:")
            if data.startswith(" "):
                data = data[1:]

            if current_event == "done":
                print(f"\n\n[done] {data}")
                break

            if current_event == "error":
                print(f"\n\n[error] {data}")
                break

            # 当前服务按字符流式返回；当 token 是换行符时，SSE 行会表现为空 data。
            print(data if data else "\n", end="", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test local FastAPI RAG chat endpoints.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="FastAPI 服务地址，默认 http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--query",
        default="什么是混合检索？",
        help="测试问题",
    )
    parser.add_argument(
        "--mode",
        choices=["vector", "keyword", "hybrid"],
        default="hybrid",
        help="检索模式",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="最多返回文档数",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="最低文档分数",
    )
    parser.add_argument(
        "--stream-only",
        action="store_true",
        help="只测试流式接口",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    payload = build_payload(args)

    try:
        if not args.stream_only:
            test_normal_chat(base_url, payload)

        test_stream_chat(base_url, payload)
        return 0

    except requests.ConnectionError:
        print(
            "\n无法连接 FastAPI 服务。请先启动：\n"
            "python -m uvicorn fast_app.main:app --reload",
            file=sys.stderr,
        )
        return 1

    except requests.HTTPError as e:
        print(f"\nHTTP 请求失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
