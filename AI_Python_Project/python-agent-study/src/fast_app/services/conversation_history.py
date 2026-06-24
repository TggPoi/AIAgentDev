from pydantic import BaseModel

from fast_app.domain.conversation_models import (
    ConversationMessage,
    ConversationRole,
)
from fast_app.services.conversation_memory import ConversationMemoryStore


class ConversationHistoryWindow(BaseModel):
    """给 query rewrite / 多轮 RAG 使用的最近历史窗口。"""

    conversation_id: str
    messages: list[ConversationMessage]
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
    "ConversationHistoryWindow",
    "format_history_messages",
    "load_recent_history_window",
]
