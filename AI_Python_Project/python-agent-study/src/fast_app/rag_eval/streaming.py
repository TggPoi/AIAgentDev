"""结构化 RAG SSE 的安全结果聚合。"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fast_app.rag_eval.models import RagEvalError


class SseProtocolError(ValueError):
    """结构化流缺少终态或出现重复终态。"""


class RagEvalStreamEvent(BaseModel):
    """从 HTTP SSE 解码后的单个结构化事件。"""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(min_length=1, description="SSE event 字段。")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="SSE data 解码后的 JSON object。",
    )


class RagStreamExecutionResult(BaseModel):
    """一次真实结构化 RAG 流可供 Eval 使用的最终结果。"""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        default="",
        description="仅由允许公开的 answer/Guard 事件拼接出的最终安全答案。",
    )
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="结构化流公开的来源对象；不包含完整最终上下文正文。",
    )
    route_intent: str | None = Field(
        default=None,
        description="RagAgent agent_route_selected 事件中的业务意图。",
    )
    route_source: str | None = Field(
        default=None,
        description="RagAgent 路由结论来源；非 RagAgent 流为空。",
    )
    guard_events: list[str] = Field(
        default_factory=list,
        description="按发生顺序记录的 guard_sanitized/guard_blocked 事件名。",
    )
    knowledge_version: int | None = Field(
        default=None,
        ge=0,
        description="done 事件返回的冻结知识版本。",
    )
    done: bool = Field(description="是否收到唯一且合法的 done 终态事件。")
    request_id: str | None = Field(
        default=None,
        description="错误事件或 HTTP 响应提供的请求 ID。",
    )
    trace_id: str | None = Field(
        default=None,
        description="错误事件提供的 trace ID；普通完成时可与 request_id 对齐。",
    )
    error: RagEvalError | None = Field(
        default=None,
        description="error 终态对应的结构化错误；正常完成时为空。",
    )


async def collect_structured_stream(
    events: AsyncIterable[RagEvalStreamEvent],
) -> RagStreamExecutionResult:
    """消费完整事件流并返回可评测的安全答案与终态。"""

    answer_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    route_intent: str | None = None
    route_source: str | None = None
    guard_events: list[str] = []
    knowledge_version: int | None = None
    request_id: str | None = None
    trace_id: str | None = None
    done_count = 0
    error: RagEvalError | None = None
    terminal_seen = False

    async for item in events:
        if terminal_seen:
            raise SseProtocolError("done/error 终态后不能继续发送事件")

        if item.event == "sources":
            raw_sources = item.data.get("sources", [])
            if not isinstance(raw_sources, list) or not all(
                isinstance(source, dict) for source in raw_sources
            ):
                raise SseProtocolError("sources 事件必须携带 object 列表")
            sources = list(raw_sources)
            continue

        if item.event in {"answer_delta", "guard_sanitized", "guard_blocked"}:
            text = item.data.get("text") or item.data.get("answer") or ""
            if not isinstance(text, str):
                raise SseProtocolError(f"{item.event} 的安全文本必须是字符串")
            answer_parts.append(text)
            if item.event.startswith("guard_"):
                guard_events.append(item.event)
            continue

        if item.event == "agent_route_selected":
            intent = item.data.get("intent")
            source = item.data.get("source")
            route_intent = str(intent) if intent is not None else None
            route_source = str(source) if source is not None else None
            continue

        if item.event == "done":
            done_count += 1
            if done_count > 1:
                raise SseProtocolError("结构化流不能发送重复 done")
            raw_version = item.data.get("knowledge_version")
            if isinstance(raw_version, int) and raw_version >= 0:
                knowledge_version = raw_version
            terminal_seen = True
            continue

        if item.event == "error":
            code = str(item.data.get("code") or "RAG_STREAM_ERROR")
            message = str(item.data.get("message") or "结构化 RAG 流执行失败")
            category = str(item.data.get("error_category") or "")
            error = RagEvalError(
                code=code,
                message=message,
                retryable=category in {"system_error", "external_service_error"},
            )
            request_id = _optional_text(item.data.get("request_id"))
            trace_id = _optional_text(item.data.get("trace_id"))
            terminal_seen = True

    if error is None and done_count != 1:
        raise SseProtocolError("结构化流必须以唯一 done 或 error 结束")

    return RagStreamExecutionResult(
        answer="".join(answer_parts),
        sources=sources,
        route_intent=route_intent,
        route_source=route_source,
        guard_events=guard_events,
        knowledge_version=knowledge_version,
        done=done_count == 1,
        request_id=request_id,
        trace_id=trace_id,
        error=error,
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "RagEvalStreamEvent",
    "RagStreamExecutionResult",
    "SseProtocolError",
    "collect_structured_stream",
]
