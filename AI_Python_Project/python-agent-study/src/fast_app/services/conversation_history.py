from pydantic import BaseModel

from fast_app.domain.conversation_models import (
    ConversationMessage,
    ConversationRole,
    ConversationSummary,
)
from fast_app.services.conversation_memory import ConversationMemoryStore


class ConversationHistoryWindow(BaseModel):
    """给 query rewrite / 多轮 RAG 使用的最近历史窗口。"""

    conversation_id: str
    messages: list[ConversationMessage]
    formatted_text: str


class ConversationMemoryContext(BaseModel):
    """query rewrite 使用的完整记忆上下文。

    summary_text 来自窗口外旧消息的压缩摘要，recent_window 保留最近 N 轮原始对话。
    """

    conversation_id: str
    summary_text: str | None
    summary_version: int | None
    summary_source_message_count: int
    summary_source_message_ids: list[str]
    recent_window: ConversationHistoryWindow
    formatted_text: str


def format_history_messages(messages: list[ConversationMessage]) -> str:
    """把 user / assistant 消息格式化为稳定的中文对话文本。"""

    lines: list[str] = []
    for message in messages:
        if message.role == ConversationRole.USER:
            lines.append(f"用户：{message.content}")
        elif message.role == ConversationRole.ASSISTANT:
            lines.append(f"助手：{message.content}")

    return "\n".join(lines)


def build_conversation_memory_context(
    conversation_id: str,
    recent_window: ConversationHistoryWindow,
    summary: ConversationSummary | None = None,
) -> ConversationMemoryContext:
    """组合会话摘要和最近窗口，形成 query rewrite 的输入文本。"""

    parts: list[str] = []
    summary_text = None
    summary_version = None
    summary_source_message_count = 0
    summary_source_message_ids: list[str] = []

    if summary is not None and summary.summary_text.strip():
        summary_text = summary.summary_text.strip()
        summary_version = summary.version
        summary_source_message_count = summary.source_message_count
        summary_source_message_ids = list(summary.source_message_ids)
        parts.append("【会话摘要】")
        parts.append(summary_text)

    if recent_window.formatted_text.strip():
        if parts:
            parts.append("")
        parts.append("【最近对话】")
        parts.append(recent_window.formatted_text)

    return ConversationMemoryContext(
        conversation_id=conversation_id,
        summary_text=summary_text,
        summary_version=summary_version,
        summary_source_message_count=summary_source_message_count,
        summary_source_message_ids=summary_source_message_ids,
        recent_window=recent_window,
        formatted_text="\n".join(parts),
    )


async def load_recent_history_window(
    store: ConversationMemoryStore,
    conversation_id: str,
    max_turns: int,
) -> ConversationHistoryWindow:
    """从会话 store 读取最近 N 轮 user / assistant 历史。"""

    max_messages = max(max_turns, 0) * 2
    raw_messages = await store.list_recent_messages(
        conversation_id=conversation_id,
        limit=max_messages,
    )
    messages = [
        message
        for message in raw_messages
        if message.role in {ConversationRole.USER, ConversationRole.ASSISTANT}
    ]

    return ConversationHistoryWindow(
        conversation_id=conversation_id,
        messages=messages,
        formatted_text=format_history_messages(messages),
    )


__all__ = [
    "ConversationMemoryContext",
    "ConversationHistoryWindow",
    "build_conversation_memory_context",
    "format_history_messages",
    "load_recent_history_window",
]
