from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fast_app.core.logging import format_log_fields, get_logger
from fast_app.core.request_context import (
    REQUEST_ID_HEADER,
    reset_request_context,
    set_request_context,
)


logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_request_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming_request_id or uuid4().hex
        trace_id = request_id
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        request_id_token, trace_id_token = set_request_context(
            request_id=request_id,
            trace_id=trace_id,
        )

        start_time = perf_counter()

        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            latency_ms = (perf_counter() - start_time) * 1000
            logger.info(
                "http_request %s",
                format_log_fields(
                    event="http.request.finish",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            return response
        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.error(
                "http_request %s",
                format_log_fields(
                    event="http.request.failed",
                    method=request.method,
                    path=request.url.path,
                    latency_ms=round(latency_ms, 2),
                    error_type=type(exc).__name__,
                ),
            )
            raise
        finally:
            # 当前上下文设置完成后，清空id，避免后续上下文被污染
            reset_request_context(
                request_id_token=request_id_token,
                trace_id_token=trace_id_token,
            )
