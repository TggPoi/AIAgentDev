from typing import Any

from fast_app.core.config import Settings
from fast_app.schemas.debug_trace_schema import (
    DebugTraceErrorSnapshot,
    DebugTraceRequestSnapshot,
    DebugTraceRuntimeSnapshot,
    DebugTraceSourceSnapshot,
    RagDebugTraceResponse,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse


def build_debug_request_snapshot(req: RagChatRequest) -> DebugTraceRequestSnapshot:
    return DebugTraceRequestSnapshot(
        query=req.query,
        mode=req.mode,
        top_k=req.top_k,
        candidate_k=req.candidate_k,
        min_score=req.min_score,
        filters=req.filters.model_dump(),
    )


def build_debug_runtime_snapshot(settings: Settings) -> DebugTraceRuntimeSnapshot:
    return DebugTraceRuntimeSnapshot(
        pipeline_provider=settings.rag_pipeline_provider,
        llm_provider=settings.llm_provider,
        llm_model_name=settings.llm_model_name,
        vector_retriever_provider=settings.vector_retriever_provider,
        keyword_retriever_provider=settings.keyword_retriever_provider,
        reranker_provider=settings.reranker_provider,
        rerank_model_name=settings.rerank_model_name,
        langsmith_project=settings.langsmith_project,
    )


def build_debug_success_response(
    settings: Settings,
    req: RagChatRequest,
    response: RagChatResponse,
) -> RagDebugTraceResponse:
    max_sources = max(0, settings.debug_trace_max_sources)
    sources = [
        DebugTraceSourceSnapshot(
            id=source.id,
            source=source.source,
            retrieval_sources=source.retrieval_sources,
            title=source.title,
            section_path=source.section_path,
            score=source.score,
            scores=source.scores,
            metadata=source.metadata,
            content_preview=source.content_preview,
        )
        for source in response.sources[:max_sources]
    ]

    return RagDebugTraceResponse(
        status="success",
        request_id=response.request_id,
        trace_id=response.trace_id,
        request=build_debug_request_snapshot(req),
        runtime=build_debug_runtime_snapshot(settings),
        answer_length=len(response.answer),
        source_count=len(response.sources),
        sources=sources,
    )


def build_debug_error_response(
    settings: Settings,
    req: RagChatRequest,
    error_content: dict[str, Any],
    error_type: str,
) -> RagDebugTraceResponse:
    return RagDebugTraceResponse(
        status="failed",
        request_id=_get_optional_str(error_content, "request_id"),
        trace_id=_get_optional_str(error_content, "trace_id"),
        request=build_debug_request_snapshot(req),
        runtime=build_debug_runtime_snapshot(settings),
        source_count=0,
        error=DebugTraceErrorSnapshot(
            code=str(error_content["code"]),
            message=str(error_content["message"]),
            error_category=str(error_content["error_category"]),
            error_type=error_type,
        ),
    )


def _get_optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)

    if value is None:
        return None

    return str(value)
