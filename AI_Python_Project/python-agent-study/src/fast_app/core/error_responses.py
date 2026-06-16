from typing import Any

from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.services.exceptions import AppServiceError


def build_error_response_content(
    code: str,
    message: str,
    error_category: str,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "error_category": error_category,
        "request_id": request_id or get_request_id(),
        "trace_id": trace_id or get_trace_id(),
    }


def build_app_error_response_content(
    exc: AppServiceError,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return build_error_response_content(
        code=exc.error_code,
        message=exc.public_message,
        error_category=exc.error_category,
        request_id=request_id,
        trace_id=trace_id,
    )


def build_internal_error_response_content(
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    return build_error_response_content(
        code="INTERNAL_SERVER_ERROR",
        message="服务器内部错误",
        error_category="system_error",
        request_id=request_id,
        trace_id=trace_id,
    )


def build_http_error_response_content(
    status_code: int,
    message: str,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    error_category = "user_error" if status_code < 500 else "system_error"
    return build_error_response_content(
        code=f"HTTP_{status_code}",
        message=message,
        error_category=error_category,
        request_id=request_id,
        trace_id=trace_id,
    )
