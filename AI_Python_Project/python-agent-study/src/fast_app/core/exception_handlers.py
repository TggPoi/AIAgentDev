from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fast_app.core.error_responses import (
    build_app_error_response_content,
    build_error_response_content,
    build_http_error_response_content,
    build_internal_error_response_content,
)
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.schemas.error_schema import (
    RequestValidationErrorResponse,
    RequestValidationFieldError,
)
from fast_app.services.exceptions import AppServiceError


logger = get_logger(__name__)


_AUTH_VALIDATION_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("POST", "/auth/login"): frozenset({"username_or_email", "password"}),
    ("POST", "/auth/refresh"): frozenset({"refresh_token"}),
    ("POST", "/auth/change-password"): frozenset(
        {"current_password", "new_password"}
    ),
}

_PUBLIC_VALIDATION_ERRORS: dict[str, tuple[str, str]] = {
    "missing": ("required", "该字段为必填项"),
    "string_type": ("invalid_type", "请输入文本"),
    "string_too_short": ("too_short", "输入长度过短"),
    "string_too_long": ("too_long", "输入长度过长"),
    "value_error": ("invalid", "输入值不合法"),
}


def get_request_ids_from_request(request: Request) -> tuple[str | None, str | None]:
    return (
        getattr(request.state, "request_id", None),
        getattr(request.state, "trace_id", None),
    )


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id, trace_id = get_request_ids_from_request(request)
        logger.warning(
            "http_error %s",
            format_log_fields(
                event="http.error",
                error_category="user_error",
                error_code="REQUEST_VALIDATION_ERROR",
                path=request.url.path,
                method=request.method,
                status_code=422,
                error_type=type(exc).__name__,
                validation_error_count=len(exc.errors()),
            ),
        )

        content = build_error_response_content(
            code="REQUEST_VALIDATION_ERROR",
            message="请求参数不合法",
            error_category="user_error",
            request_id=request_id,
            trace_id=trace_id,
        )
        field_errors = _project_auth_validation_field_errors(request, exc.errors())
        if field_errors is not None:
            content = RequestValidationErrorResponse(
                **content,
                field_errors=field_errors,
            ).model_dump(mode="json")

        return JSONResponse(
            status_code=422,
            content=content,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        request_id, trace_id = get_request_ids_from_request(request)
        error_category = "user_error" if exc.status_code < 500 else "system_error"
        log_method = logger.warning if error_category == "user_error" else logger.error
        message = str(exc.detail) if exc.detail else "请求处理失败"

        log_method(
            "http_error %s",
            format_log_fields(
                event="http.error",
                error_category=error_category,
                error_code=f"HTTP_{exc.status_code}",
                path=request.url.path,
                method=request.method,
                status_code=exc.status_code,
                error_type=type(exc).__name__,
                message=message,
            ),
        )

        return JSONResponse(
            status_code=exc.status_code,
            content=build_http_error_response_content(
                status_code=exc.status_code,
                message=message,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )

    @app.exception_handler(AppServiceError)
    async def handle_app_service_error(
        request: Request,
        exc: AppServiceError,
    ) -> JSONResponse:
        request_id, trace_id = get_request_ids_from_request(request)
        log_method = logger.warning

        if exc.error_category == "external_service_error":
            log_method = logger.error

        log_method(
            "http_error %s",
            format_log_fields(
                event="http.error",
                error_category=exc.error_category,
                error_code=exc.error_code,
                path=request.url.path,
                method=request.method,
                status_code=exc.status_code,
                error_type=type(exc).__name__,
                message=str(exc),
            ),
        )

        headers = None
        retry_after = getattr(exc, "retry_after_seconds", None)
        if isinstance(retry_after, int) and retry_after > 0:
            headers = {"Retry-After": str(retry_after)}

        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content=build_app_error_response_content(
                exc,
                request_id=request_id,
                trace_id=trace_id,
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id, trace_id = get_request_ids_from_request(request)
        logger.exception(
            "http_error %s",
            format_log_fields(
                event="http.error",
                error_category="system_error",
                error_code="INTERNAL_SERVER_ERROR",
                path=request.url.path,
                method=request.method,
                status_code=500,
                error_type=type(exc).__name__,
            ),
        )

        return JSONResponse(
            status_code=500,
            content=build_internal_error_response_content(
                request_id=request_id,
                trace_id=trace_id,
            ),
        )


def _project_auth_validation_field_errors(
    request: Request,
    errors: list[dict[str, object]],
) -> list[RequestValidationFieldError] | None:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if not isinstance(route_path, str):
        return None

    allowed_fields = _AUTH_VALIDATION_FIELDS.get((request.method.upper(), route_path))
    if allowed_fields is None:
        return None

    projected: list[RequestValidationFieldError] = []
    projected_fields: set[str] = set()
    for error in errors:
        location = error.get("loc")
        if (
            not isinstance(location, (list, tuple))
            or len(location) != 2
            or location[0] != "body"
            or not isinstance(location[1], str)
        ):
            continue

        field = location[1]
        public_error = _PUBLIC_VALIDATION_ERRORS.get(str(error.get("type", "")))
        if (
            field not in allowed_fields
            or field in projected_fields
            or public_error is None
        ):
            continue

        public_code, public_message = public_error
        projected.append(
            RequestValidationFieldError(
                field=field,
                code=public_code,
                message=public_message,
            )
        )
        projected_fields.add(field)

    return projected
