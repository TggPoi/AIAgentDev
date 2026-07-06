from pydantic import BaseModel, Field


class AgentToolApprovalConfirmRequest(BaseModel):
    """工具执行确认单的确认请求体。"""

    confirmation_text: str = Field(
        min_length=1,
        max_length=512,
        description="用户提交的确认口令，必须和 approval 创建时返回的 confirmation_text 完全一致。",
    )


class AgentToolApprovalConfirmResponse(BaseModel):
    """工具执行确认单的确认响应体。"""

    approval_id: str = Field(description="被确认的工具执行确认单 ID。")
    status: str = Field(description="确认单执行后的状态，例如 executed。")
    executed: bool = Field(description="是否已经执行真实工具动作。")
    message: str = Field(description="执行结果说明，面向前端或 CLI 展示。")
    result: dict[str, object] = Field(
        default_factory=dict,
        description="文档动作执行结果详情，例如目标路径、是否 dry_run、预览信息。",
    )
    request_id: str | None = Field(
        default=None,
        description="本次确认请求的 request_id，用于和后端日志对齐。",
    )
    trace_id: str | None = Field(
        default=None,
        description="本次确认请求的 trace_id，用于链路追踪。",
    )


__all__ = [
    "AgentToolApprovalConfirmRequest",
    "AgentToolApprovalConfirmResponse",
]
