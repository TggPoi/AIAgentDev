from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    utc_now,
)
from fast_app.services.conversation.conversation_repository import PostgresConversationRepository


class ConversationPersistenceService:
    """PostgreSQL 会话持久化服务。

    这个服务只负责 durable storage，不负责 Redis 最近历史窗口。RAG 主链路
    通过它保存完整会话记录，query rewrite 仍然读取短期 memory。
    """

    def __init__(self, repository: PostgresConversationRepository) -> None:
        self.repository = repository

    async def save_turn(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, object],
        user_id: str | None = None,
    ) -> None:
        """把一次 user / assistant turn 持久化到 PostgreSQL。"""

        now = utc_now()
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            external_session_id=(
                str(metadata["external_session_id"])
                if metadata.get("external_session_id")
                else conversation_id
            ),
            title=_default_conversation_title(user_content),
            updated_at=now,
            metadata={
                "last_query_rewrite_reason": metadata.get("query_rewrite_reason"),
                "last_source_count": metadata.get("source_count"),
            },
        )
        messages = [
            ConversationMessage(
                conversation_id=conversation_id,
                role=ConversationRole.USER,
                content=user_content,
                created_at=now,
                metadata=metadata,
            ),
            ConversationMessage(
                conversation_id=conversation_id,
                role=ConversationRole.ASSISTANT,
                content=assistant_content,
                created_at=utc_now(),
                metadata=metadata,
            ),
        ]

        await self.repository.save_conversation_turn(
            conversation=conversation,
            messages=messages,
        )


__all__ = ["ConversationPersistenceService"]


def _default_conversation_title(content: str) -> str:
    normalized = " ".join(content.split())
    return (normalized[:60] or "新会话")
