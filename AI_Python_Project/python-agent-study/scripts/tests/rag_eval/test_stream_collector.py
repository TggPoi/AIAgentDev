"""真实结构化 RAG SSE 的轻量 Eval 聚合契约测试。"""

import asyncio

from fast_app.rag_eval.streaming import (
    RagEvalStreamEvent,
    SseProtocolError,
    collect_structured_stream,
)


async def event_stream(events: list[RagEvalStreamEvent]):
    for event in events:
        yield event


async def test_safe_answer_and_route_are_aggregated() -> None:
    result = await collect_structured_stream(
        event_stream(
            [
                RagEvalStreamEvent(
                    event="agent_route_selected",
                    data={"intent": "simple_rag", "source": "model"},
                ),
                RagEvalStreamEvent(
                    event="sources",
                    data={"sources": [{"id": "source-1"}]},
                ),
                RagEvalStreamEvent(event="answer_delta", data={"text": "第一段"}),
                RagEvalStreamEvent(
                    event="guard_sanitized",
                    data={"text": "[已脱敏]", "action": "sanitize"},
                ),
                RagEvalStreamEvent(
                    event="guard_blocked",
                    data={"answer": "无法继续", "action": "block"},
                ),
                RagEvalStreamEvent(
                    event="done",
                    data={"status": "done", "knowledge_version": 6},
                ),
            ]
        )
    )

    assert result.answer == "第一段[已脱敏]无法继续"
    assert result.route_intent == "simple_rag"
    assert result.sources == [{"id": "source-1"}]
    assert result.guard_events == ["guard_sanitized", "guard_blocked"]
    assert result.knowledge_version == 6
    assert result.done is True
    assert result.error is None


async def test_error_event_is_not_reported_as_success() -> None:
    result = await collect_structured_stream(
        event_stream(
            [
                RagEvalStreamEvent(
                    event="error",
                    data={
                        "code": "NO_SEARCH_RESULT",
                        "message": "没有可靠资料",
                        "error_category": "user_error",
                    },
                )
            ]
        )
    )

    assert result.done is False
    assert result.error is not None
    assert result.error.code == "NO_SEARCH_RESULT"


async def expect_protocol_error(events: list[RagEvalStreamEvent]) -> None:
    try:
        await collect_structured_stream(event_stream(events))
    except SseProtocolError:
        return
    raise AssertionError("expected SseProtocolError")


async def protocol_tests() -> None:
    await test_safe_answer_and_route_are_aggregated()
    await test_error_event_is_not_reported_as_success()
    await expect_protocol_error(
        [RagEvalStreamEvent(event="answer_delta", data={"text": "missing done"})]
    )
    await expect_protocol_error(
        [
            RagEvalStreamEvent(event="done", data={"status": "done"}),
            RagEvalStreamEvent(event="done", data={"status": "done"}),
        ]
    )


if __name__ == "__main__":
    asyncio.run(protocol_tests())
    print("rag_eval stream collector tests passed")
