import argparse
import json
import sys
from dataclasses import dataclass
from uuid import uuid4
from collections.abc import Iterator

import requests


@dataclass(frozen=True)
class RagChatScenario:
    name: str
    query: str
    mode: str
    top_k: int = 5
    candidate_k: int | None = 8
    min_score: float = 0.0


PHASE9_LANGSMITH_SCENARIOS = [
    RagChatScenario(
        name="phase9-model-refactor",
        query="阶段 9 为什么要重构 RetrievedDoc 和 RagSource 数据模型？",
        mode="hybrid",
    ),
    RagChatScenario(
        name="phase9-score-breakdown",
        query="阶段 9 如何保留 vector_score keyword_score rrf_score rerank_score？",
        mode="hybrid",
    ),
    RagChatScenario(
        name="phase9-retrieval-sources",
        query="阶段 9 为什么要记录 retrieval_sources 和多来源命中信息？",
        mode="hybrid",
    ),
    RagChatScenario(
        name="phase9-metadata-sources",
        query="阶段 9 为什么要把 metadata 写入 ES 和 Milvus，并在 sources 中展示 title 和 section_path？",
        mode="hybrid",
    ),
    RagChatScenario(
        name="phase9-stream-events",
        query="阶段 9 stream event 协议设计包含哪些事件？",
        mode="hybrid",
    ),
]


def build_headers(request_id: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}

    if request_id:
        headers["X-Request-ID"] = request_id

    return headers


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    """根据命令行参数构造 RagChatRequest 请求体。"""
    payload: dict[str, object] = {
        "query": args.query,
        "mode": args.mode,
        "top_k": args.top_k,
        "min_score": args.min_score,
    }

    if args.candidate_k is not None:
        payload["candidate_k"] = args.candidate_k

    filters: dict[str, object] = {}
    if args.source_path:
        filters["source_path"] = args.source_path
    if args.section_path:
        filters["section_path"] = args.section_path
    if filters:
        payload["filters"] = filters

    return payload


def build_scenario_payload(scenario: RagChatScenario) -> dict[str, object]:
    payload: dict[str, object] = {
        "query": scenario.query,
        "mode": scenario.mode,
        "top_k": scenario.top_k,
        "min_score": scenario.min_score,
    }

    if scenario.candidate_k is not None:
        payload["candidate_k"] = scenario.candidate_k

    return payload


def build_no_result_payload(args: argparse.Namespace) -> dict[str, object]:
    """构造一个会触发 NoSearchResultError 的请求体。"""
    payload = build_payload(args)
    payload["min_score"] = 1.0
    return payload


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


def assert_sources_match_filters(
    body: dict[str, object],
    source_path: str | None,
    section_path: list[str],
) -> None:
    """当命令行传入 filters 时，检查返回 sources 是否带有对应 metadata。"""
    if not source_path and not section_path:
        return

    sources = body.get("sources")

    if not isinstance(sources, list) or not sources:
        raise AssertionError("expected non-empty sources")

    for source in sources:
        if not isinstance(source, dict):
            raise AssertionError("expected source item to be object")

        metadata = source.get("metadata")
        if not isinstance(metadata, dict):
            raise AssertionError("expected source.metadata to be object")

        if source_path and metadata.get("source_path") != source_path:
            raise AssertionError(
                "expected source.metadata.source_path to match filter: "
                f"{source_path}"
            )

        if section_path:
            metadata_section_path = metadata.get("section_path")
            if not isinstance(metadata_section_path, list):
                raise AssertionError("expected source.metadata.section_path to be list")

            if not set(section_path).intersection(set(metadata_section_path)):
                raise AssertionError(
                    "expected source.metadata.section_path to match at least one "
                    f"filter value: {section_path}"
                )


def test_normal_chat(
    base_url: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> None:
    """测试非流式 RAG 聊天接口。"""
    url = f"{base_url}/rag/chat"
    headers = build_headers(request_id)

    print("========== POST /rag/chat ==========")
    if request_id:
        print(f"request_id: {request_id}")
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, json=payload, headers=headers, timeout=60)

    print(f"\nstatus: {resp.status_code}")
    print("response:")
    print_response_json(resp)

    body = resp.json()
    assert_sources_have_scores(body)
    assert_sources_have_retrieval_sources(body)
    assert_sources_have_metadata(body)

    filters = payload.get("filters")
    if isinstance(filters, dict):
        source_path = filters.get("source_path")
        section_path = filters.get("section_path")
        assert_sources_match_filters(
            body=body,
            source_path=source_path if isinstance(source_path, str) else None,
            section_path=section_path if isinstance(section_path, list) else [],
        )

    resp.raise_for_status()


def test_normal_chat_error(
    base_url: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> None:
    """测试非流式接口被全局异常处理器转换后的 JSON 错误响应。"""
    url = f"{base_url}/rag/chat"
    headers = build_headers(request_id)

    print("\n========== POST /rag/chat error ==========")
    if request_id:
        print(f"request_id: {request_id}")
    print("request:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, json=payload, headers=headers, timeout=60)

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


def test_stream_chat(
    base_url: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> None:
    """测试流式 RAG 聊天接口，并实时打印 data token。"""
    url = f"{base_url}/rag/chat/stream"
    headers = build_headers(request_id)

    print("\n========== POST /rag/chat/stream ==========")
    if request_id:
        print(f"request_id: {request_id}")
    print("stream output:")

    with requests.post(
        url,
        json=payload,
        headers=headers,
        stream=True,
        timeout=90,
    ) as resp:
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


def parse_sse_json_data(data: str) -> dict[str, object]:
    try:
        value = json.loads(data)
    except json.JSONDecodeError as e:
        raise AssertionError(f"expected JSON SSE data, got {data}") from e

    if not isinstance(value, dict):
        raise AssertionError(f"expected SSE data object, got {type(value)}")

    return value


def test_structured_stream_chat(
    base_url: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> None:
    """测试结构化流式 RAG 聊天接口。"""
    url = f"{base_url}/rag/chat/stream/events"
    headers = build_headers(request_id)

    print("\n========== POST /rag/chat/stream/events ==========")
    if request_id:
        print(f"request_id: {request_id}")
    print("structured stream output:")

    saw_sources = False
    saw_token = False
    saw_done = False
    token_preview: list[str] = []

    with requests.post(
        url,
        json=payload,
        headers=headers,
        stream=True,
        timeout=90,
    ) as resp:
        print(f"status: {resp.status_code}\n")
        resp.raise_for_status()

        current_event = "message"

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

            body = parse_sse_json_data(data)

            if current_event == "sources":
                saw_sources = True
                sources = body.get("sources")
                if not isinstance(sources, list) or not sources:
                    raise AssertionError("expected non-empty sources event")

                assert_sources_have_scores(body)
                assert_sources_have_retrieval_sources(body)
                assert_sources_have_metadata(body)

                filters = payload.get("filters")
                if isinstance(filters, dict):
                    source_path = filters.get("source_path")
                    section_path = filters.get("section_path")
                    assert_sources_match_filters(
                        body=body,
                        source_path=source_path if isinstance(source_path, str) else None,
                        section_path=section_path if isinstance(section_path, list) else [],
                    )

            elif current_event == "token":
                saw_token = True
                token = body.get("token")
                if not isinstance(token, str):
                    raise AssertionError("expected token event data.token to be string")
                if len(token_preview) < 20:
                    token_preview.append(token)

            elif current_event == "done":
                saw_done = True
                if body.get("status") != "done":
                    raise AssertionError(
                        f"expected done status, got {body.get('status')}"
                    )
                break

            elif current_event == "error":
                raise AssertionError(f"unexpected structured stream error: {body}")

    if not saw_sources:
        raise AssertionError("expected sources event")
    if not saw_token:
        raise AssertionError("expected token event")
    if not saw_done:
        raise AssertionError("expected done event")

    print("\nstructured token preview:")
    print("".join(token_preview))


def test_stream_chat_error(
    base_url: str,
    payload: dict[str, object],
    request_id: str | None = None,
) -> None:
    """测试流式接口在异常时返回 SSE error event。"""
    url = f"{base_url}/rag/chat/stream"
    headers = build_headers(request_id)

    print("\n========== POST /rag/chat/stream error ==========")
    if request_id:
        print(f"request_id: {request_id}")
    print("stream output:")

    with requests.post(
        url,
        json=payload,
        headers=headers,
        stream=True,
        timeout=90,
    ) as resp:
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
        default="阶段 9 为什么要进行 RAG 数据模型重构？",
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
        "--candidate-k",
        type=int,
        default=None,
        help="每个召回源先取多少候选文档；不传时后端使用 top_k",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        help="按 metadata.source_path 限定检索范围",
    )
    parser.add_argument(
        "--section-path",
        action="append",
        default=[],
        help="按 metadata.section_path 限定检索范围；可以重复传入多次",
    )
    parser.add_argument(
        "--stream-only",
        action="store_true",
        help="只测试流式接口",
    )
    parser.add_argument(
        "--structured-stream-only",
        action="store_true",
        help="只测试结构化流式接口 /rag/chat/stream/events",
    )
    parser.add_argument(
        "--skip-structured-stream",
        action="store_true",
        help="跳过结构化流式接口测试",
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        help="跳过异常场景测试",
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="写入 X-Request-ID 请求头；用于和后端日志 / LangSmith metadata 对齐",
    )
    parser.add_argument(
        "--request-id-prefix",
        default="langsmith-phase9",
        help="批量场景生成 X-Request-ID 时使用的前缀",
    )
    parser.add_argument(
        "--phase9-langsmith-suite",
        action="store_true",
        help="运行一组基于 learning-docs/phase-9 数据的 RAG 问题，方便在 LangSmith 中观察 trace",
    )
    parser.add_argument(
        "--suite-structured-stream",
        action="store_true",
        help="phase9 LangSmith suite 额外测试 /rag/chat/stream/events",
    )
    return parser.parse_args()


def test_phase9_langsmith_suite(args: argparse.Namespace, base_url: str) -> None:
    suite_id = uuid4().hex[:8]

    print("========== phase9 LangSmith suite ==========")
    print(f"suite_id: {suite_id}")
    print(
        "提示：如果服务端 LANGSMITH_TRACING=true，下面每个 request_id "
        "都会写入 LangSmith metadata。"
    )

    for index, scenario in enumerate(PHASE9_LANGSMITH_SCENARIOS, start=1):
        request_id = f"{args.request_id_prefix}-{suite_id}-{index:02d}-{scenario.name}"
        payload = build_scenario_payload(scenario)

        print(f"\n========== scenario {index}: {scenario.name} ==========")
        test_normal_chat(
            base_url=base_url,
            payload=payload,
            request_id=request_id,
        )

        if args.suite_structured_stream:
            test_structured_stream_chat(
                base_url=base_url,
                payload=payload,
                request_id=f"{request_id}-stream-events",
            )


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    payload = build_payload(args)
    error_payload = build_no_result_payload(args)

    try:
        if args.phase9_langsmith_suite:
            test_phase9_langsmith_suite(args, base_url)
            return 0

        if args.structured_stream_only:
            test_structured_stream_chat(base_url, payload, args.request_id)
            return 0

        if not args.stream_only:
            test_normal_chat(base_url, payload, args.request_id)

        stream_request_id = (
            f"{args.request_id}-stream"
            if args.request_id
            else None
        )
        test_stream_chat(base_url, payload, stream_request_id)

        if not args.skip_structured_stream:
            structured_request_id = (
                f"{args.request_id}-stream-events"
                if args.request_id
                else None
            )
            test_structured_stream_chat(base_url, payload, structured_request_id)

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
