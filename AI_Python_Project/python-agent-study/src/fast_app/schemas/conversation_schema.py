from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fast_app.schemas.rag_chat_schema import RagSource


class ConversationItem(BaseModel):
    session_id: str = Field(description="当前用户命名空间内的外部会话 ID。")
    title: str = Field(description="侧边栏会话标题。")
    created_at: datetime = Field(description="会话创建时间。")
    updated_at: datetime = Field(description="最后一轮持久化消息时间。")
    message_count: int = Field(ge=0, description="会话中 user/assistant 消息总数。")
    last_message_role: Literal["user", "assistant"] | None = Field(
        default=None,
        description="最后一条公开消息角色；空会话为 null。",
    )
    last_message_preview: str | None = Field(
        default=None,
        description="最后一条消息的有界单行摘要；空会话为 null。",
    )


class ConversationListResponse(BaseModel):
    items: list[ConversationItem] = Field(
        description="当前页中只属于当前认证用户的会话。",
    )
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明 keyset cursor；没有更多会话时为空。",
    )


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        max_length=160,
        description="可选初始标题；为空时使用服务端默认标题。",
    )

    @field_validator("title")
    @classmethod
    def normalize_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title 不能只包含空白字符")
        return normalized


class UpdateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=160,
        description="规范化后非空的新会话标题。",
    )

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title 不能只包含空白字符")
        return normalized


class ConversationMessageItem(BaseModel):
    message_id: str = Field(description="持久化消息唯一 ID。")
    sequence_no: int = Field(ge=1, description="数据库生成的稳定消息序号。")
    role: Literal["user", "assistant"] = Field(description="公开消息角色。")
    content: str = Field(description="消息正文或结构化流公开错误说明。")
    sources: list[RagSource] = Field(
        default_factory=list,
        description="该轮最终上下文来源；通常只附在 assistant 消息。",
    )
    agent_task_plan_id: str | None = Field(
        default=None,
        description="该轮关联的 TaskPlan ID；没有复杂任务时为空。",
    )
    agent_task_status: str | None = Field(
        default=None,
        description="该轮 TaskPlan 最后可见状态；没有复杂任务时为空。",
    )
    terminal_status: Literal["completed", "error", "aborted"] = Field(
        description="结构化流该轮最终持久化状态。",
    )
    created_at: datetime = Field(description="消息持久化时间。")


class ConversationMessageListResponse(BaseModel):
    items: list[ConversationMessageItem] = Field(
        description="按 sequence_no 正序返回的当前页公开消息。",
    )
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明 sequence cursor；没有更多消息时为空。",
    )


__all__ = [
    "ConversationItem",
    "ConversationListResponse",
    "ConversationMessageItem",
    "ConversationMessageListResponse",
    "CreateConversationRequest",
    "UpdateConversationRequest",
]
