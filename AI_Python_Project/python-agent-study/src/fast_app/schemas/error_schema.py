"""前端可安全消费的公共 HTTP 错误响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class RequestValidationFieldError(BaseModel):
    """一个经过服务端 allowlist 投影的公开请求字段错误。"""

    field: Literal[
        "username_or_email",
        "password",
        "refresh_token",
        "current_password",
        "new_password",
        "title",
    ] = Field(
        description="允许向客户端公开的顶层请求字段名；不包含请求值或嵌套内部位置。",
    )
    code: Literal[
        "required",
        "invalid_type",
        "too_short",
        "too_long",
        "invalid",
    ] = Field(
        description="稳定的公开校验错误 code，不直接暴露 Pydantic/FastAPI 内部 context。",
    )
    message: str = Field(
        description="可安全显示的固定校验提示，不包含客户端提交值或服务端内部信息。",
    )


class RequestValidationErrorResponse(BaseModel):
    """已批准 Route 的 RequestValidationError 安全公共 422 响应。"""

    code: Literal["REQUEST_VALIDATION_ERROR"] = Field(
        description="请求模型校验失败时的稳定顶层错误 code。",
    )
    message: str = Field(
        description="请求模型校验失败时可安全显示的 form-level 通用提示。",
    )
    error_category: Literal["user_error"] = Field(
        description="错误责任分类；请求模型校验失败固定为 user_error。",
    )
    request_id: str | None = Field(
        description="当前 HTTP 请求 ID；测试或缺少请求上下文时可以为空。",
    )
    trace_id: str | None = Field(
        description="当前服务端 trace ID；缺少 trace 上下文时可以为空。",
    )
    field_errors: list[RequestValidationFieldError] = Field(
        description="仅包含当前 Route 明确 allowlist 顶层字段的安全错误；无法安全映射时为空。",
    )


__all__ = [
    "RequestValidationErrorResponse",
    "RequestValidationFieldError",
]
