from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fast_app.core.error_responses import build_error_response_content
from fast_app.core.logging import format_log_fields, get_logger


logger = get_logger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """在进入路由前根据 Content-Length 拒绝超大请求体。

    这里优先做低侵入的 HTTP 边界保护：不读取 request body，只使用客户端声明的
    Content-Length 做快速拦截，避免破坏 Starlette 后续对 body stream 的读取。
    """

    def __init__(
        self,
        app,
        max_body_bytes: int,
    ) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = _parse_content_length(
            request.headers.get("content-length")
        )

        if content_length is not None and content_length > self.max_body_bytes:
            logger.warning(
                "http_error %s",
                format_log_fields(
                    event="http.request.body_too_large",
                    error_category="user_error",
                    error_code="REQUEST_BODY_TOO_LARGE",
                    method=request.method,
                    path=request.url.path,
                    content_length=content_length,
                    max_body_bytes=self.max_body_bytes,
                    status_code=413,
                ),
            )
            return JSONResponse(
                status_code=413,
                content=build_error_response_content(
                    code="REQUEST_BODY_TOO_LARGE",
                    message=f"请求体过大，最大允许 {self.max_body_bytes} 字节",
                    error_category="user_error",
                ),
            )

        response = await call_next(request)
        return response


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None

    try:
        value = int(raw_value)
    except ValueError:
        return None

    if value < 0:
        return None

    return value


__all__ = ["RequestSizeLimitMiddleware"]
