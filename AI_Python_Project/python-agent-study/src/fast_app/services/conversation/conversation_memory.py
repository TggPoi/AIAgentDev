from collections import defaultdict
from typing import Protocol
import asyncio

from redis.asyncio import Redis

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

    async def delete_conversation(self, conversation_id: str) -> None:
        """删除会话的全部短期消息。"""
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
            messages = self._messages_by_conversation[message.conversation_id]
            if any(item.id == message.id for item in messages):
                return
            messages.append(message)

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

    async def delete_conversation(self, conversation_id: str) -> None:
        async with self._lock:
            self._messages_by_conversation.pop(conversation_id, None)


class RedisConversationMemoryStore:
    """Redis 版短期会话消息存储。

    每个 conversation 使用一个 Redis List 保存消息 JSON：
    conversation:{conversation_id}:messages
    """

    def __init__(
        self,
        redis_client: Redis,
        ttl_seconds: int,
        max_messages: int,
    ) -> None:
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages

    def _messages_key(self, conversation_id: str) -> str:
        return f"conversation:{conversation_id}:messages"

    async def append_message(self, message: ConversationMessage) -> None:
        key = self._messages_key(message.conversation_id)
        payload = message.model_dump_json()

        pipeline = self.redis_client.pipeline()
        # 同一 turn 重试时先移除完全相同的消息 JSON，再追加，保持 List 幂等。
        pipeline.lrem(key, 0, payload)
        pipeline.rpush(key, payload)
        pipeline.ltrim(key, -self.max_messages, -1)
        pipeline.expire(key, self.ttl_seconds)
        await pipeline.execute()

    async def list_recent_messages(
        self,
        conversation_id: str,
        limit: int,
    ) -> list[ConversationMessage]:
        if limit <= 0:
            return []

        key = self._messages_key(conversation_id)
        effective_limit = min(limit, self.max_messages)
        raw_items = await self.redis_client.lrange(key, -effective_limit, -1)

        return [
            ConversationMessage.model_validate_json(raw_item)
            for raw_item in raw_items
        ]

    async def delete_conversation(self, conversation_id: str) -> None:
        await self.redis_client.delete(self._messages_key(conversation_id))


__all__ = [
    "ConversationMemoryStore",
    "InMemoryConversationMemoryStore",
    "RedisConversationMemoryStore",
]
