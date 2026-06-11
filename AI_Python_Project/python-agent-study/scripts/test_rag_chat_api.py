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


def build_no_result_payload(args: argparse.Namespace) -> dict[str, object]:
    """构造一个会触发 NoSearchResultError 的请求体。"""
    return {
        "query": args.query,
        "mode": args.mode,
        "top_k": args.top_k,
        "min_score": 1.0,
    }


def print_response_json(resp: requests.Response) -> None:
    """打印 JSON 响应；如果不是 JSON，则打印原始文本。"""
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(resp.text)

# 检查scores字段存在且格式正确
def assert_sources_have_scores(body: dict[str, object]) -> None:
    sources = body.get("sources")

    if not isinstance(sources, list) or not sources:
        raise AssertionError("expected non-empty sources")

    first_source = sources[0]
    if not isinstance(first_source, dict):
        raise AssertionError("expected source item to be object")

    scores = first_source.get("scores")
    if not isinstance(scores, dict):
        raise AssertionError("expected source.scores to be object")

# 检查检索来源内容存在
def assert_sources_have_retrieval_sources(body: dict[str, object]) -> None:
    sources = body.get("sources")

    if not isinstance(sources, list) or not sources:
        raise AssertionError("expected non-empty sources")

    first_source = sources[0]
    if not isinstance(first_source, dict):
        raise AssertionError("expected source item to be object")

    retrieval_sources = first_source.get("retrieval_sources")
    if not isinstance(retrieval_sources, list) or not retrieval_sources:
        raise AssertionError("expected source.retrieval_sources to be non-empty list")


def assert_sources_have_metadata(body: dict[str, object]) -> None:
    sources = body.get("sources")

    if not isinstance(sources, list) or not sources:
        raise AssertionError("expected non-empty sources")

    first_source = sources[0]
    if not isinstance(first_source, dict):
        raise AssertionError("expected source item to be object")

    title = first_source.get("title")
    if title is not None and not isinstance(title, str):
        raise AssertionError("expected source.title to be string or null")

    section_path = first_source.get("section_path")
    if not isinstance(section_path, list):
        raise AssertionError("expected source.section_path to be list")

    metadata = first_source.get("metadata")
    if not isinstance(metadata, dict):
        raise AssertionError("expected source.metadata to be object")


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

    body = resp.json()
    assert_sources_have_scores(body)
    assert_sources_have_retrieval_sources(body)
    assert_sources_have_metadata(body)

    resp.raise_for_status()


def test_normal_chat_error(base_url: str, payload: dict[str, object]) -> None:
    """测试非流式接口被全局异常处理器转换后的 JSON 错误响应。"""
    url = f"{base_url}/rag/chat"

    print("\n========== POST /rag/chat error ==========")
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, json=payload, timeout=30)

    print(f"\nstatus: {resp.status_code}")
    print("response:")
    print_response_json(resp)

    if resp.status_code != 404:
        raise AssertionError(f"expected 404, got {resp.status_code}")

    try:
        body = resp.json()
    except ValueError as e:
        raise AssertionError("expected JSON error response") from e

    if body.get("code") != "NO_SEARCH_RESULT":
        raise AssertionError(f"expected code NO_SEARCH_RESULT, got {body.get('code')}")


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


def test_stream_chat_error(base_url: str, payload: dict[str, object]) -> None:
    """测试流式接口在异常时返回 SSE error event。"""
    url = f"{base_url}/rag/chat/stream"

    print("\n========== POST /rag/chat/stream error ==========")
    print("stream output:")

    with requests.post(url, json=payload, stream=True, timeout=60) as resp:
        print(f"status: {resp.status_code}\n")
        resp.raise_for_status()

        current_event = "message"
        saw_error_event = False

        for line in iter_sse_lines(resp):
            print(line)

            if line.startswith("event:"):
                current_event = line.removeprefix("event:").strip()
                continue

            if not line.startswith("data:"):
                continue

            data = line.removeprefix("data:")
            if data.startswith(" "):
                data = data[1:]

            if current_event == "error":
                saw_error_event = True
                if "NO_SEARCH_RESULT" not in data:
                    raise AssertionError(f"expected NO_SEARCH_RESULT error, got {data}")
                break

        if not saw_error_event:
            raise AssertionError("expected SSE error event")


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
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="跳过异常场景测试",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    payload = build_payload(args)
    error_payload = build_no_result_payload(args)

    try:
        if not args.stream_only:
            test_normal_chat(base_url, payload)

        test_stream_chat(base_url, payload)

        # if not args.skip_errors:
        #     if not args.stream_only:
        #         test_normal_chat_error(base_url, error_payload)

        #     test_stream_chat_error(base_url, error_payload)

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

    except AssertionError as e:
        print(f"\n测试断言失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
