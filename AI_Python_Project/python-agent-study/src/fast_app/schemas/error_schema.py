"""前端可安全消费的公共 HTTP 错误响应模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RequestValidationFieldError(BaseModel):
    """一个经过服务端 allowlist 投影的公开请求字段错误。"""

    field: Literal[
        "username_or_email",
        "username",
        "password",
        "email",
        "display_name",
        "account_type",
        "department_access",
        "direct_permission_codes",
        "refresh_token",
        "current_password",
        "new_password",
        "title",
        "query",
        "department_code",
        "document_type",
        "target_account",
        "doc_id",
        "document_ids",
        "status",
        "session_id",
        "limit",
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


class ManagedUserAccessFieldError(BaseModel):
    """账号访问快照业务校验的安全公开字段错误。"""

    field: Literal[
        "username",
        "account_type",
        "department_access",
        "direct_permission_codes",
    ] = Field(
        description="由服务端确定性业务分支选择的公开表单字段；不包含提交值或嵌套位置。",
    )
    code: Literal["invalid"] = Field(
        description="账号访问快照不满足目录或组织约束时的稳定字段错误 code。",
    )
    message: str = Field(
        description="固定安全字段提示，不包含自然语言业务异常、提交值或内部信息。",
    )


class ManagedUserAccessInvalidErrorResponse(BaseModel):
    """账号访问快照业务校验失败的安全公共 422 响应。"""

    code: Literal["MANAGED_USER_ACCESS_INVALID"] = Field(
        description="账号访问快照不满足服务端目录或组织约束时的稳定顶层错误 code。",
    )
    message: str = Field(
        description="账号访问快照业务校验失败时可安全显示的固定通用提示。",
    )
    error_category: Literal["user_error"] = Field(
        description="错误责任分类；账号访问快照业务校验失败固定为 user_error。",
    )
    request_id: str | None = Field(
        description="当前 HTTP 请求 ID；测试或缺少请求上下文时可以为空。",
    )
    trace_id: str | None = Field(
        description="当前服务端 trace ID；缺少 trace 上下文时可以为空。",
    )
    field_errors: list[ManagedUserAccessFieldError] = Field(
        description="只包含服务端确定性分支批准公开的账号访问字段错误。",
    )


class DocumentAccessGrantFieldError(BaseModel):
    """跨部门文档授权业务校验的安全公开字段错误。"""

    field: Literal["document_ids"] = Field(
        description="由服务端确定性业务分支选择的公开授权字段；不包含文档标识或数组位置。",
    )
    code: Literal["invalid"] = Field(
        description="文档无需或不能重复授权时的稳定字段错误 code。",
    )
    message: str = Field(
        description="固定安全字段提示，不包含文档标识、ACL、部门或自然语言业务异常。",
    )


class DocumentAccessGrantInvalidErrorResponse(BaseModel):
    """跨部门文档授权业务校验失败的安全公共 422 响应。"""

    code: Literal["DOCUMENT_ACCESS_GRANT_INVALID"] = Field(
        description="授权请求不满足精确跨部门授权语义时的稳定顶层错误 code。",
    )
    message: str = Field(
        description="授权业务校验失败时可安全显示的固定通用提示。",
    )
    error_category: Literal["user_error"] = Field(
        description="错误责任分类；授权业务校验失败固定为 user_error。",
    )
    request_id: str | None = Field(
        description="当前 HTTP 请求 ID；测试或缺少请求上下文时可以为空。",
    )
    trace_id: str | None = Field(
        description="当前服务端 trace ID；缺少 trace 上下文时可以为空。",
    )
    field_errors: list[DocumentAccessGrantFieldError] = Field(
        description="只包含服务端确定性分支批准公开的文档授权字段错误；cursor 等页面级错误为空。",
    )


UserAdministrationValidationErrorResponse = Annotated[
    RequestValidationErrorResponse | ManagedUserAccessInvalidErrorResponse,
    Field(discriminator="code"),
]

DocumentAccessGrantValidationErrorResponse = Annotated[
    RequestValidationErrorResponse | DocumentAccessGrantInvalidErrorResponse,
    Field(discriminator="code"),
]


__all__ = [
    "DocumentAccessGrantFieldError",
    "DocumentAccessGrantInvalidErrorResponse",
    "DocumentAccessGrantValidationErrorResponse",
    "ManagedUserAccessFieldError",
    "ManagedUserAccessInvalidErrorResponse",
    "RequestValidationErrorResponse",
    "RequestValidationFieldError",
    "UserAdministrationValidationErrorResponse",
]
