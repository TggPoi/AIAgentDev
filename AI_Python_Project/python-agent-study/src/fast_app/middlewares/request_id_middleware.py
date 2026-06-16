from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fast_app.core.latency import elapsed_ms, log_slow_operation, start_timer
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.core.request_context import (
    REQUEST_ID_HEADER,
    reset_request_context,
    set_request_context,
)


logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        slow_http_request_threshold_ms: float = 3000.0,
    ):
        super().__init__(app)
        self.slow_http_request_threshold_ms = slow_http_request_threshold_ms

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

        start_time = start_timer()

        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            latency_ms = elapsed_ms(start_time)
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
            log_slow_operation(
                logger=logger,
                event="http.request.slow",
                latency_ms=latency_ms,
                threshold_ms=self.slow_http_request_threshold_ms,
                slow_component="http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                status="success",
            )
            return response
        except Exception as exc:
            latency_ms = elapsed_ms(start_time)
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
            log_slow_operation(
                logger=logger,
                event="http.request.slow",
                latency_ms=latency_ms,
                threshold_ms=self.slow_http_request_threshold_ms,
                slow_component="http_request",
                method=request.method,
                path=request.url.path,
                status="failed",
                error_type=type(exc).__name__,
            )
            raise
        finally:
            # # 当前上下文设置完成后，清空id，避免后续上下文被污染
            reset_request_context(
                request_id_token=request_id_token,
                trace_id_token=trace_id_token,
            )
