from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """生成带 UTC 时区的时间戳，避免后续持久化时出现 naive datetime。"""
    return datetime.now(timezone.utc)


def new_conversation_id() -> str:
    """生成默认会话 ID；后续也可以由客户端传入 session_id 映射而来。"""
    return uuid4().hex


def new_message_id() -> str:
    """生成默认消息 ID，便于内存存储、日志和后续数据库落表共用。"""
    return uuid4().hex


def new_summary_id() -> str:
    """生成会话摘要 ID，便于 summary 版本追溯和日志定位。"""
    return uuid4().hex


class ConversationRole(StrEnum):
    """会话消息角色，和常见 LLM role 保持一致。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    """会话中的一条结构化消息。"""

    id: str = Field(default_factory=new_message_id)
    conversation_id: str = Field(min_length=1, max_length=128)
    role: ConversationRole
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, object] = Field(default_factory=dict)


class Conversation(BaseModel):
    """一次多轮对话的容器对象。"""

    id: str = Field(default_factory=new_conversation_id, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, object] = Field(default_factory=dict)


class ConversationStructuredSummary(BaseModel):
    """面向 Agent 记忆压缩的轻量结构化摘要。

    这些字段只保存对话中明确出现的信息，不能把模型猜测写成长期事实。
    """

    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    important_entities: list[str] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    """会话摘要派生视图。

    summary 不替代原始 ConversationMessage，而是压缩窗口外旧消息，
    并通过 source_message_ids / version 保留可追溯性。
    """

    id: str = Field(default_factory=new_summary_id)
    conversation_id: str = Field(min_length=1, max_length=128)
    summary_text: str = Field(default="")
    structured_summary: ConversationStructuredSummary = Field(
        default_factory=ConversationStructuredSummary
    )
    version: int = Field(default=1, ge=1)
    source_message_ids: list[str] = Field(default_factory=list)
    source_message_count: int = Field(default=0, ge=0)
    covered_until_message_id: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, object] = Field(default_factory=dict)


__all__ = [
    "Conversation",
    "ConversationMessage",
    "ConversationRole",
    "ConversationStructuredSummary",
    "ConversationSummary",
    "new_conversation_id",
    "new_message_id",
    "new_summary_id",
    "utc_now",
]
