"""验证 RagAgent 主结构化 SSE 和 RagSource 导航公开契约。"""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fast_app.api.rag_chat_routes import (
    format_sse_event,
    rag_chat_structured_sse_event_generator,
    router,
)
from fast_app.core.request_context import REQUEST_ID_HEADER
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.middlewares.request_id_middleware import RequestIdMiddleware
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagScoreBreakdown, RagSource
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.rag.rag_pipeline_service import docs_to_sources


class _RagAgentEvents:
    pipeline_provider = "rag_agent"

    def __init__(self, events: list[RagStreamEvent], *, fail: bool = False) -> None:
        self._events = events
        self._fail = fail

    async def stream_events(self, _request: RagChatRequest):
        for event in self._events:
            yield event
        if self._fail:
            raise ExternalServiceError("rag agent unavailable")


def main() -> None:
    assert_source_navigation_contract()
    asyncio.run(assert_event_order_contract())
    assert_event_validation_and_unknown_compatibility()
    assert_request_id_header_contract()
    assert_openapi_contract()
    print("rag_stream_contract=passed")


def assert_source_navigation_contract() -> None:
    knowledge, web, invalid = docs_to_sources(
        [
            RetrievedDoc(
                id="chunk-knowledge",
                content="knowledge",
                score=0.9,
                source="elasticsearch",
                metadata={"doc_id": "doc-navigation", "source_path": "docs/a.md"},
            ),
            RetrievedDoc(
                id="web-1",
                content="web",
                score=0.8,
                source="web_search",
                metadata={"url": "https://example.com/docs?q=rag"},
            ),
            RetrievedDoc(
                id="web-invalid",
                content="invalid",
                score=0.7,
                source="web_search",
                metadata={"url": "javascript:alert(1)"},
            ),
        ]
    )
    assert knowledge.source_type == "knowledge_document"
    assert knowledge.doc_id == "doc-navigation"
    assert knowledge.href is None
    assert web.source_type == "web"
    assert web.href == "https://example.com/docs?q=rag"
    assert "url" not in web.metadata
    assert invalid.source_type == "knowledge_document"
    assert invalid.href is None
    assert "url" not in invalid.metadata
    try:
        RagSource(
            source_type="web",
            href="https://user:password@example.com/private",
            id="bad",
            source="web_search",
            score=1.0,
            scores=RagScoreBreakdown(),
            content_preview="bad",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("带凭据的 Web href 未被拒绝")


async def assert_event_order_contract() -> None:
    request = RagChatRequest(query="contract", session_id="contract-session")
    pipeline = _RagAgentEvents(
        [
            RagStreamEvent(
                event="agent_route_selected",
                data={
                    "intent": "simple_rag",
                    "source": "rule",
                    "confidence": 1.0,
                    "reason": "test",
                },
            ),
            RagStreamEvent(event="sources", data={"sources": []}),
            RagStreamEvent(event="answer_delta", data={"text": "answer"}),
        ]
    )
    frames = [
        _parse_frame(chunk)
        async for chunk in rag_chat_structured_sse_event_generator(
            request,
            pipeline,  # type: ignore[arg-type]
        )
    ]
    assert [event for event, _data in frames] == [
        "agent_route_selected",
        "sources",
        "answer_delta",
        "done",
    ]
    assert all(data["contract_version"] == "1.0" for _event, data in frames)
    assert frames[-1][1]["status"] == "done"

    error_frames = [
        _parse_frame(chunk)
        async for chunk in rag_chat_structured_sse_event_generator(
            request,
            _RagAgentEvents([], fail=True),  # type: ignore[arg-type]
        )
    ]
    assert [event for event, _data in error_frames] == ["error"]
    assert error_frames[0][1]["code"] == "EXTERNAL_SERVICE_ERROR"


def assert_event_validation_and_unknown_compatibility() -> None:
    try:
        format_sse_event("answer_delta", {})
    except ValidationError:
        pass
    else:
        raise AssertionError("缺少 text 的 answer_delta 未被契约拒绝")

    try:
        format_sse_event("agent_task_plan_created", {"status": "created"})
    except ValidationError:
        pass
    else:
        raise AssertionError("缺少 task_plan_id 的任务事件未被契约拒绝")

    event, data = _parse_frame(
        format_sse_event("future_optional_event", {"feature": "future"})
    )
    assert event == "future_optional_event"
    assert data["feature"] == "future"
    assert data["contract_version"] == "1.0"


def assert_request_id_header_contract() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/stream")
    async def stream():
        async def generate():
            yield format_sse_event("done", {"status": "done"})

        return StreamingResponse(generate(), media_type="text/event-stream")

    with TestClient(app) as client:
        response = client.get("/stream", headers={REQUEST_ID_HEADER: "request-contract"})
    assert response.headers[REQUEST_ID_HEADER] == "request-contract"
    _event, data = _parse_frame(response.text)
    assert data["request_id"] == "request-contract"


def assert_openapi_contract() -> None:
    app = FastAPI()
    app.include_router(router)
    response = app.openapi()["paths"]["/rag/chat/stream/events"]["post"]["responses"]["200"]
    assert "X-Request-ID" in response["headers"]
    schema = response["content"]["text/event-stream"]["schema"]
    assert set(schema["properties"]) == {"event", "data"}


def _parse_frame(chunk: str) -> tuple[str, dict[str, object]]:
    lines = chunk.strip().splitlines()
    event = next(line[7:] for line in lines if line.startswith("event: "))
    data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return event, data


if __name__ == "__main__":
    main()
