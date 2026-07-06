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

    # 用户输入的消息。
    USER = "user"
    # 模型或 Agent 返回给用户的消息。
    ASSISTANT = "assistant"
    # 系统级上下文或内部提示消息。
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    """会话中的一条结构化消息。"""

    id: str = Field(default_factory=new_message_id, description="消息唯一 ID。")
    conversation_id: str = Field(
        min_length=1,
        max_length=128,
        description="消息所属会话 ID。",
    )
    role: ConversationRole = Field(description="消息角色，区分 user / assistant / system。")
    content: str = Field(min_length=1, description="消息正文内容。")
    created_at: datetime = Field(default_factory=utc_now, description="消息创建时间。")
    metadata: dict[str, object] = Field(default_factory=dict, description="消息附加元数据。")


class Conversation(BaseModel):
    """一次多轮对话的容器对象。"""

    id: str = Field(
        default_factory=new_conversation_id,
        min_length=1,
        max_length=128,
        description="会话唯一 ID；也可由外部 session_id 映射而来。",
    )
    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="会话归属用户 ID；匿名或未认证场景可为空。",
    )
    created_at: datetime = Field(default_factory=utc_now, description="会话创建时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="会话最近更新时间。")
    metadata: dict[str, object] = Field(default_factory=dict, description="会话附加元数据。")


class ConversationStructuredSummary(BaseModel):
    """面向 Agent 记忆压缩的轻量结构化摘要。

    这些字段只保存对话中明确出现的信息，不能把模型猜测写成长期事实。
    """

    goals: list[str] = Field(default_factory=list, description="对话中明确提出的目标。")
    constraints: list[str] = Field(default_factory=list, description="对话中明确给出的约束条件。")
    decisions: list[str] = Field(default_factory=list, description="对话过程中已经确定的决策。")
    open_questions: list[str] = Field(default_factory=list, description="尚未解决或需要继续确认的问题。")
    user_preferences: list[str] = Field(default_factory=list, description="用户明确表达的偏好。")
    important_entities: list[str] = Field(default_factory=list, description="对后续对话有价值的重要实体。")


class ConversationSummary(BaseModel):
    """会话摘要派生视图。

    summary 不替代原始 ConversationMessage，而是压缩窗口外旧消息，
    并通过 source_message_ids / version 保留可追溯性。
    """

    id: str = Field(default_factory=new_summary_id, description="会话摘要唯一 ID。")
    conversation_id: str = Field(
        min_length=1,
        max_length=128,
        description="摘要所属会话 ID。",
    )
    summary_text: str = Field(default="", description="自然语言摘要文本。")
    structured_summary: ConversationStructuredSummary = Field(
        default_factory=ConversationStructuredSummary,
        description="结构化摘要，便于 Agent 读取稳定事实。",
    )
    version: int = Field(default=1, ge=1, description="摘要版本号，便于后续增量更新。")
    source_message_ids: list[str] = Field(default_factory=list, description="参与生成摘要的原始消息 ID 列表。")
    source_message_count: int = Field(default=0, ge=0, description="参与生成摘要的原始消息数量。")
    covered_until_message_id: str | None = Field(
        default=None,
        description="摘要覆盖到的最后一条消息 ID。",
    )
    created_at: datetime = Field(default_factory=utc_now, description="摘要创建时间。")
    updated_at: datetime = Field(default_factory=utc_now, description="摘要最近更新时间。")
    metadata: dict[str, object] = Field(default_factory=dict, description="摘要附加元数据。")


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
