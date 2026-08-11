"""通过真实结构化 SSE 执行 RAG case 的进程内 EvalTarget。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Mapping
from time import perf_counter
from typing import Literal

import httpx
from fastapi import FastAPI
from httpx_sse import aconnect_sse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from fast_app.core.config import Settings
from fast_app.evaluation.cases.models import RagEvalCase
from fast_app.evaluation.pipeline.models import EvaluationError, EvaluationSnapshot
from fast_app.evaluation.pipeline.snapshot_capture import capture_evaluation_snapshot
from fast_app.rag_eval.models import RagEvalError
from fast_app.rag_eval.streaming import (
    RagEvalStreamEvent,
    RagStreamExecutionResult,
    SseProtocolError,
    collect_structured_stream,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse, RagSource


RagEvalTargetStatus = Literal["evaluated", "skipped", "failed"]


class RagEvalAuth(BaseModel):
    """真实 ASGI 请求使用的评测认证方式。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo", "api_key", "bearer"] = Field(
        description="demo、X-API-Key 或 Bearer 认证模式。",
    )
    credential: SecretStr | None = Field(
        default=None,
        description="API key/Bearer 密钥；demo 模式为空且不会进入报告。",
    )

    @model_validator(mode="after")
    def validate_credential(self) -> "RagEvalAuth":
        if (self.mode == "demo") != (self.credential is None):
            raise ValueError("demo 模式不能携带凭据，安全认证模式必须携带凭据")
        return self

    @classmethod
    def from_environment(
        cls,
        settings: Settings,
        environ: Mapping[str, str] | None = None,
    ) -> "RagEvalAuth":
        import os

        values = environ if environ is not None else os.environ
        api_key = values.get("RAG_EVAL_API_KEY", "").strip()
        bearer = values.get("RAG_EVAL_BEARER_TOKEN", "").strip()
        if api_key and bearer:
            raise ValueError("RAG_EVAL_API_KEY 和 RAG_EVAL_BEARER_TOKEN 不能同时配置")
        if api_key:
            return cls(mode="api_key", credential=api_key)
        if bearer:
            return cls(mode="bearer", credential=bearer)
        if settings.auth_enabled:
            raise ValueError("认证已启用时必须配置 RAG_EVAL_API_KEY 或 Bearer Token")
        return cls(mode="demo")

    def headers_for(self, eval_principal_id: str) -> dict[str, str]:
        if self.mode == "demo":
            return {"X-Demo-User-Id": eval_principal_id}
        secret = self.credential.get_secret_value() if self.credential else ""
        if self.mode == "api_key":
            return {"X-API-Key": secret}
        return {"Authorization": f"Bearer {secret}"}


@dataclass(frozen=True)
class RagEvalTargetExecution:
    """一次 case 的真实流结果、冻结快照和路由结论。"""

    case_id: str
    status: RagEvalTargetStatus
    stream: RagStreamExecutionResult
    snapshot: EvaluationSnapshot
    knowledge_retrieval_performed: bool
    error: RagEvalError | None = None


class InProcessStructuredStreamTarget:
    """以小接口隐藏 ASGI、SSE、认证和快照采集细节。"""

    def __init__(
        self,
        *,
        app: FastAPI,
        settings: Settings,
        pipeline_provider: str,
        auth: RagEvalAuth,
    ) -> None:
        self.app = app
        self.settings = settings
        self.pipeline_provider = pipeline_provider.strip().lower()
        self.auth = auth

    async def execute(self, case: RagEvalCase) -> RagEvalTargetExecution:
        request = _build_request(case)
        started = perf_counter()
        with capture_evaluation_snapshot(
            req=request,
            settings=self.settings,
            pipeline_provider=self.pipeline_provider,
            eval_principal_id=case.eval_principal_id,
        ) as collector:
            try:
                stream = await self._request_stream(case, request)
            except Exception as exc:
                error = RagEvalError(
                    code=(
                        "sse_protocol_error"
                        if isinstance(exc, SseProtocolError)
                        else "stream_request_failed"
                    ),
                    message=str(exc) or type(exc).__name__,
                    retryable=isinstance(exc, httpx.TransportError),
                )
                stream = RagStreamExecutionResult(
                    done=False,
                    error=error,
                )

            try:
                response = _build_response(case, stream)
            except Exception as exc:
                stream.error = RagEvalError(
                    code="stream_response_invalid",
                    message=(str(exc) or type(exc).__name__)[:500],
                )
                response = None
            snapshot = collector.finalize(
                response=response,
                latency_ms=(perf_counter() - started) * 1000,
                error=(
                    EvaluationError(
                        code=stream.error.code,
                        message=stream.error.message,
                        retryable=stream.error.retryable,
                    )
                    if stream.error is not None
                    else None
                ),
            )

        return _classify_execution(
            case=case,
            provider=self.pipeline_provider,
            stream=stream,
            snapshot=snapshot,
        )

    async def _request_stream(
        self,
        case: RagEvalCase,
        request: RagChatRequest,
    ) -> RagStreamExecutionResult:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://rag-eval.local",
            timeout=None,
        ) as client:
            headers = self.auth.headers_for(case.eval_principal_id)
            if self.auth.mode != "demo":
                await _verify_authenticated_principal(client, headers, case)

            async with aconnect_sse(
                client,
                "POST",
                "/rag/chat/stream/events",
                headers=headers,
                json=request.model_dump(mode="json"),
            ) as event_source:
                event_source.response.raise_for_status()
                request_id = event_source.response.headers.get("X-Request-ID")
                result = await collect_structured_stream(
                    _decoded_events(event_source.aiter_sse())
                )
                if request_id and result.request_id is None:
                    result.request_id = request_id
                    result.trace_id = result.trace_id or request_id
                return result


async def _decoded_events(raw_events):
    async for event in raw_events:
        try:
            data = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise SseProtocolError(f"{event.event} data 不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise SseProtocolError(f"{event.event} data 必须是 JSON object")
        yield RagEvalStreamEvent(event=event.event or "message", data=data)


async def _verify_authenticated_principal(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    case: RagEvalCase,
) -> None:
    response = await client.get("/auth/me", headers=headers)
    response.raise_for_status()
    payload = response.json()
    actual = str(payload.get("user_id") or "") if isinstance(payload, dict) else ""
    if actual != case.eval_principal_id:
        raise PermissionError(
            "认证用户与 Golden eval_principal_id 不一致: "
            f"expected={case.eval_principal_id}, actual={actual or '<missing>'}"
        )


def _build_request(case: RagEvalCase) -> RagChatRequest:
    return RagChatRequest(
        query=case.question,
        mode=case.mode,
        top_k=case.top_k,
        candidate_k=case.candidate_k,
        min_score=case.min_score,
        filters=case.filters,
        allow_web_fallback=False,
        allow_direct_web=False,
        min_knowledge_version=case.knowledge_version,
    )


def _build_response(
    case: RagEvalCase,
    stream: RagStreamExecutionResult,
) -> RagChatResponse | None:
    if stream.error is not None:
        return None
    return RagChatResponse(
        request_id=stream.request_id,
        trace_id=stream.trace_id,
        knowledge_version=stream.knowledge_version or case.knowledge_version,
        query=case.question,
        answer=stream.answer,
        sources=[RagSource.model_validate(source) for source in stream.sources],
        route_intent=stream.route_intent,
        route_source=stream.route_source,
    )


def _classify_execution(
    *,
    case: RagEvalCase,
    provider: str,
    stream: RagStreamExecutionResult,
    snapshot: EvaluationSnapshot,
) -> RagEvalTargetExecution:
    retrieval_performed = any(
        stage.status != "not_executed"
        for stage in snapshot.payload.retrieval_stages.values()
    )
    wrong_rag_agent_intent = (
        provider == "rag_agent"
        and stream.route_intent != "simple_rag"
    )
    if wrong_rag_agent_intent:
        error = RagEvalError(
            code="route_mismatch",
            message=(
                "Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径"
            ),
        )
        return RagEvalTargetExecution(
            case_id=case.case_id,
            status="failed",
            stream=stream,
            snapshot=snapshot,
            knowledge_retrieval_performed=retrieval_performed,
            error=error,
        )

    if not retrieval_performed:
        if stream.error is not None and stream.error.code in {
            "sse_protocol_error",
            "stream_request_failed",
            "stream_response_invalid",
        }:
            return RagEvalTargetExecution(
                case_id=case.case_id,
                status="failed",
                stream=stream,
                snapshot=snapshot,
                knowledge_retrieval_performed=False,
                error=stream.error,
            )
        error = RagEvalError(
            code="route_mismatch",
            message=(
                "Golden 要求普通 RAG，但实际未进入顶层 knowledge_retrieval 路径"
            ),
        )
        return RagEvalTargetExecution(
            case_id=case.case_id,
            status="failed",
            stream=stream,
            snapshot=snapshot,
            knowledge_retrieval_performed=False,
            error=error,
        )

    if stream.error is not None:
        if not case.answerable and stream.error.code == "NO_SEARCH_RESULT":
            return RagEvalTargetExecution(
                case_id=case.case_id,
                status="evaluated",
                stream=stream,
                snapshot=snapshot,
                knowledge_retrieval_performed=True,
            )
        return RagEvalTargetExecution(
            case_id=case.case_id,
            status="failed",
            stream=stream,
            snapshot=snapshot,
            knowledge_retrieval_performed=True,
            error=stream.error,
        )

    if case.answerable and snapshot.payload.final_context is None:
        error = RagEvalError(
            code="missing_final_context",
            message="answerable RAG case 没有捕获模型实际使用的最终上下文",
        )
        return RagEvalTargetExecution(
            case_id=case.case_id,
            status="failed",
            stream=stream,
            snapshot=snapshot,
            knowledge_retrieval_performed=True,
            error=error,
        )

    return RagEvalTargetExecution(
        case_id=case.case_id,
        status="evaluated",
        stream=stream,
        snapshot=snapshot,
        knowledge_retrieval_performed=True,
    )


__all__ = [
    "InProcessStructuredStreamTarget",
    "RagEvalAuth",
    "RagEvalTargetExecution",
    "RagEvalTargetStatus",
]
