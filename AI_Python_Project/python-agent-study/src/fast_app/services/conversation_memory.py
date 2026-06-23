from collections import defaultdict
from typing import Protocol
import asyncio

from fast_app.domain.conversation_models import ConversationMessage


class ConversationMemoryStore(Protocol):
    """会话消息存储边界。

    这个协议只描述业务需要的最小能力，不绑定 Redis、PostgreSQL 或内存实现。
    后续替换真实存储时，只要实现同样的方法，pipeline 层就不需要重写。
    """

    async def append_message(self, message: ConversationMessage) -> None:
        """追加一条消息。"""
        ...

    async def list_recent_messages(
        self,
        conversation_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        """按创建顺序返回指定会话最近 limit 条消息。"""
        ...


class InMemoryConversationMemoryStore:
    """内存版会话消息存储。

    它只用于学习、mock 和后续 14-4/14-5 的最小闭环验证。
    进程重启后数据会丢失，不适合生产持久化。
    """

    def __init__(self) -> None:
        self._messages_by_conversation: dict[str, list[ConversationMessage]] = (
            defaultdict(list)
        )
        self._lock = asyncio.Lock()

    async def append_message(self, message: ConversationMessage) -> None:
        async with self._lock:
            self._messages_by_conversation[message.conversation_id].append(message)

    async def list_recent_messages(
        self,
        conversation_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        if limit <= 0:
            return []

        async with self._lock:
            messages = self._messages_by_conversation.get(conversation_id, [])
            return list(messages[-limit:])


__all__ = [
    "ConversationMemoryStore",
    "InMemoryConversationMemoryStore",
]
