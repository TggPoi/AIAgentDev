from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fast_app.core.request_context import (
    REQUEST_ID_HEADER,
    reset_request_context,
    set_request_context,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming_request_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming_request_id or uuid4().hex
        trace_id = request_id

        request_id_token, trace_id_token = set_request_context(
            request_id=request_id,
            trace_id=trace_id,
        )

        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            reset_request_context(
                request_id_token=request_id_token,
                trace_id_token=trace_id_token,
            )
