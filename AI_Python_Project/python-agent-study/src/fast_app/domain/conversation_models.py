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


__all__ = [
    "Conversation",
    "ConversationMessage",
    "ConversationRole",
    "new_conversation_id",
    "new_message_id",
    "utc_now",
]
