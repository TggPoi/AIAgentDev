from fastapi import APIRouter, Depends, HTTPException, Request

from fast_app.core.config import Settings, get_settings
from fast_app.core.error_responses import (
    build_app_error_response_content,
    build_internal_error_response_content,
)
from fast_app.core.latency import elapsed_ms, log_slow_operation, start_timer
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.dependencies.rag_dependencies import get_rag_pipeline
from fast_app.schemas.debug_trace_schema import RagDebugTraceResponse
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.debug_trace_builder import (
    build_debug_error_response,
    build_debug_success_response,
)
from fast_app.services.exceptions import AppServiceError
from fast_app.services.rag_pipeline_service import RagPipeline


logger = get_logger(__name__)
router = APIRouter(prefix="/debug", tags=["debug-trace"])

DEBUG_TRACE_TOKEN_HEADER = "X-Debug-Trace-Token"


def verify_debug_trace_access(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Settings:
    if not settings.debug_trace_enabled:
        raise HTTPException(status_code=404, detail="Not Found")

    token = request.headers.get(DEBUG_TRACE_TOKEN_HEADER)

    if not settings.debug_trace_token or token != settings.debug_trace_token:
        raise HTTPException(status_code=403, detail="Debug trace access denied")

    return settings


@router.post("/rag/trace", response_model=RagDebugTraceResponse)
async def debug_rag_trace_endpoint(
    request: Request,
    req: RagChatRequest,
    settings: Settings = Depends(verify_debug_trace_access),
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> RagDebugTraceResponse:
    start_time = start_timer()
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    trace_id = getattr(request.state, "trace_id", None) or get_trace_id()
    logger.info(
        "debug_trace %s",
        format_log_fields(
            event="debug.trace.start",
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            candidate_k=req.candidate_k,
            min_score=req.min_score,
        ),
    )

    try:
        response = await pipeline.run(req)
        response.request_id = request_id
        response.trace_id = trace_id
        latency_ms = elapsed_ms(start_time)
        debug_response = build_debug_success_response(
            settings=settings,
            req=req,
            response=response,
            latency_ms=round(latency_ms, 2),
        )
    except AppServiceError as exc:
        error_content = build_app_error_response_content(
            exc,
            request_id=request_id,
            trace_id=trace_id,
        )
        latency_ms = elapsed_ms(start_time)
        debug_response = build_debug_error_response(
            settings=settings,
            req=req,
            error_content=error_content,
            error_type=type(exc).__name__,
            latency_ms=round(latency_ms, 2),
        )
    except Exception as exc:
        logger.exception(
            "debug_trace %s",
            format_log_fields(
                event="debug.trace.failed",
                error_type=type(exc).__name__,
            ),
        )
        error_content = build_internal_error_response_content(
            request_id=request_id,
            trace_id=trace_id,
        )
        latency_ms = elapsed_ms(start_time)
        debug_response = build_debug_error_response(
            settings=settings,
            req=req,
            error_content=error_content,
            error_type=type(exc).__name__,
            latency_ms=round(latency_ms, 2),
        )

    logger.info(
        "debug_trace %s",
        format_log_fields(
            event="debug.trace.finish",
            status=debug_response.status,
            source_count=debug_response.source_count,
            latency_ms=round(latency_ms, 2),
        ),
    )
    log_slow_operation(
        logger=logger,
        event="debug.trace.slow",
        latency_ms=latency_ms,
        threshold_ms=settings.slow_rag_pipeline_threshold_ms,
        slow_component="debug_trace",
        status=debug_response.status,
        source_count=debug_response.source_count,
    )
    return debug_response
