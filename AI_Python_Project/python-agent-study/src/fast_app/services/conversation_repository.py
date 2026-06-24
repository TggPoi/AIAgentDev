from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.conversation_tables import ConversationMessageTable, ConversationTable
from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)


class PostgresConversationRepository:
    """Conversation / Message 的 PostgreSQL 持久化仓储。

    仓储层负责把业务侧的 Pydantic 模型转换成 ORM 表对象，避免 API 或 Graph
    节点直接依赖 SQLAlchemy 表结构。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_conversation(self, conversation: Conversation) -> None:
        """新增或更新会话容器。"""

        existing = await self._session.get(ConversationTable, conversation.id)
        if existing is None:
            self._session.add(_conversation_to_table(conversation))
        else:
            existing.user_id = conversation.user_id
            existing.created_at = conversation.created_at
            existing.updated_at = conversation.updated_at
            existing.metadata_json = conversation.metadata

        await self._session.commit()

    async def append_message(self, message: ConversationMessage) -> None:
        """追加一条会话消息。

        这里不自动创建 conversation。调用方需要先通过 upsert_conversation 确保
        父会话存在，这样外键约束才能暴露真实的数据写入顺序问题。
        """

        self._session.add(_message_to_table(message))
        await self._session.commit()

    async def save_conversation_turn(
        self,
        conversation: Conversation,
        messages: list[ConversationMessage],
    ) -> None:
        """在一个事务里保存会话容器和当前轮消息。

        一轮对话通常包含 user / assistant 两条消息。这里统一 commit，避免
        conversation 已写入但 assistant message 写入失败这类半成功状态。
        """

        existing = await self._session.get(ConversationTable, conversation.id)
        if existing is None:
            self._session.add(_conversation_to_table(conversation))
        else:
            existing.user_id = conversation.user_id
            existing.updated_at = conversation.updated_at
            existing.metadata_json = {
                **(existing.metadata_json or {}),
                **conversation.metadata,
            }

        for message in messages:
            self._session.add(_message_to_table(message))

        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def list_messages(
        self,
        conversation_id: str,
        limit: int,
        offset: int = 0,
    ) -> list[ConversationMessage]:
        """按创建时间正序读取某个会话下的消息列表。"""

        if limit <= 0:
            return []

        stmt: Select[tuple[ConversationMessageTable]] = (
            select(ConversationMessageTable)
            .where(ConversationMessageTable.conversation_id == conversation_id)
            .order_by(
                ConversationMessageTable.created_at.asc(),
                ConversationMessageTable.id.asc(),
            )
            .offset(max(offset, 0))
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()

        return [_table_to_message(row) for row in rows]

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """按 ID 读取会话容器；不存在时返回 None。"""

        row = await self._session.get(ConversationTable, conversation_id)
        if row is None:
            return None

        return _table_to_conversation(row)


def _conversation_to_table(conversation: Conversation) -> ConversationTable:
    """把领域模型转换成 ORM 表对象。"""

    return ConversationTable(
        id=conversation.id,
        user_id=conversation.user_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        metadata_json=conversation.metadata,
    )


def _table_to_conversation(row: ConversationTable) -> Conversation:
    """把 ORM 表对象还原成领域模型。"""

    return Conversation(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=row.metadata_json,
    )


def _message_to_table(message: ConversationMessage) -> ConversationMessageTable:
    """把消息领域模型转换成 ORM 表对象。"""

    return ConversationMessageTable(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
        metadata_json=message.metadata,
    )


def _table_to_message(row: ConversationMessageTable) -> ConversationMessage:
    """把 ORM 消息记录还原成领域模型。"""

    return ConversationMessage(
        id=row.id,
        conversation_id=row.conversation_id,
        role=ConversationRole(row.role),
        content=row.content,
        created_at=row.created_at,
        metadata=row.metadata_json,
    )


__all__ = ["PostgresConversationRepository"]
