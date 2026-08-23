from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.conversation_tables import (
    ConversationMessageTable,
    ConversationSummaryTable,
    ConversationTable,
)
from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    ConversationStructuredSummary,
    ConversationSummary,
)


class PostgresConversationRepository:
    """Conversation / Message 的 PostgreSQL 持久化仓储。

    仓储层负责把业务侧的 Pydantic 模型转换成 ORM 表对象，避免 API 或 Graph
    节点直接依赖 SQLAlchemy 表结构。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(self, conversation: Conversation) -> None:
        self._session.add(_conversation_to_table(conversation))
        await self._session.commit()

    async def list_conversations_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        cursor_updated_at: datetime | None,
        cursor_id: str | None,
    ) -> tuple[list[ConversationListRecord], bool]:
        last_content = (
            select(ConversationMessageTable.content)
            .where(
                ConversationMessageTable.conversation_id == ConversationTable.id
            )
            .order_by(ConversationMessageTable.sequence_no.desc())
            .limit(1)
            .scalar_subquery()
        )
        last_role = (
            select(ConversationMessageTable.role)
            .where(
                ConversationMessageTable.conversation_id == ConversationTable.id
            )
            .order_by(ConversationMessageTable.sequence_no.desc())
            .limit(1)
            .scalar_subquery()
        )
        message_count = (
            select(func.count(ConversationMessageTable.id))
            .where(
                ConversationMessageTable.conversation_id == ConversationTable.id
            )
            .scalar_subquery()
        )
        stmt = select(
            ConversationTable,
            last_content,
            last_role,
            message_count,
        ).where(ConversationTable.user_id == user_id)
        if cursor_updated_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    ConversationTable.updated_at < cursor_updated_at,
                    (
                        (ConversationTable.updated_at == cursor_updated_at)
                        & (ConversationTable.id < cursor_id)
                    ),
                )
            )
        rows = (
            await self._session.execute(
                stmt.order_by(
                    ConversationTable.updated_at.desc(),
                    ConversationTable.id.desc(),
                ).limit(limit + 1)
            )
        ).all()
        return (
            [
                ConversationListRecord(
                    conversation=_table_to_conversation(row[0]),
                    last_message_content=row[1],
                    last_message_role=row[2],
                    message_count=int(row[3] or 0),
                )
                for row in rows[:limit]
            ],
            len(rows) > limit,
        )

    async def get_conversation_by_external_session(
        self,
        *,
        user_id: str,
        external_session_id: str,
    ) -> Conversation | None:
        row = await self._session.scalar(
            select(ConversationTable).where(
                ConversationTable.user_id == user_id,
                ConversationTable.external_session_id == external_session_id,
            )
        )
        return _table_to_conversation(row) if row is not None else None

    async def update_title(
        self,
        *,
        user_id: str,
        external_session_id: str,
        title: str,
    ) -> Conversation | None:
        result = await self._session.execute(
            update(ConversationTable)
            .where(
                ConversationTable.user_id == user_id,
                ConversationTable.external_session_id == external_session_id,
            )
            .values(title=title, updated_at=ConversationTable.updated_at)
        )
        await self._session.commit()
        if not result.rowcount:
            return None
        return await self.get_conversation_by_external_session(
            user_id=user_id,
            external_session_id=external_session_id,
        )

    async def delete_conversation_for_user(
        self,
        *,
        user_id: str,
        external_session_id: str,
    ) -> str | None:
        deleted_id = await self._session.scalar(
            delete(ConversationTable)
            .where(
                ConversationTable.user_id == user_id,
                ConversationTable.external_session_id == external_session_id,
            )
            .returning(ConversationTable.id)
        )
        await self._session.commit()
        return deleted_id

    async def list_message_records_for_user(
        self,
        *,
        conversation_id: str,
        user_id: str,
        limit: int,
        after_sequence_no: int | None,
    ) -> tuple[list[ConversationMessageRecord], bool]:
        stmt = (
            select(ConversationMessageTable)
            .join(ConversationTable)
            .where(
                ConversationMessageTable.conversation_id == conversation_id,
                ConversationTable.user_id == user_id,
                ConversationMessageTable.role.in_(["user", "assistant"]),
            )
        )
        if after_sequence_no is not None:
            stmt = stmt.where(
                ConversationMessageTable.sequence_no > after_sequence_no
            )
        rows = list(
            (
                await self._session.scalars(
                    stmt.order_by(ConversationMessageTable.sequence_no.asc()).limit(
                        limit + 1
                    )
                )
            ).all()
        )
        return (
            [
                ConversationMessageRecord(
                    message=_table_to_message(row),
                    sequence_no=row.sequence_no,
                )
                for row in rows[:limit]
            ],
            len(rows) > limit,
        )

    async def upsert_conversation(self, conversation: Conversation) -> None:
        """新增或更新会话容器。"""

        existing = await self._session.get(ConversationTable, conversation.id)
        if existing is None:
            self._session.add(_conversation_to_table(conversation))
        else:
            existing.user_id = conversation.user_id
            if conversation.external_session_id is not None:
                existing.external_session_id = conversation.external_session_id
            existing.title = conversation.title
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
    ) -> list[ConversationMessage]:
        """在一个事务里保存会话容器和当前轮消息。

        一轮对话通常包含 user / assistant 两条消息。这里统一 commit，避免
        conversation 已写入但 assistant message 写入失败这类半成功状态。
        """

        conversation_values = _conversation_values(conversation)
        excluded = pg_insert(ConversationTable).excluded
        await self._session.execute(
            pg_insert(ConversationTable)
            .values(**conversation_values)
            .on_conflict_do_update(
                index_elements=[ConversationTable.id],
                set_={
                    "user_id": excluded.user_id,
                    "updated_at": excluded.updated_at,
                    "metadata_json": ConversationTable.metadata_json.op("||")(
                        excluded.metadata_json
                    ),
                },
            )
        )
        inserted_messages: list[ConversationMessage] = []
        for message in messages:
            inserted_id = await self._session.scalar(
                pg_insert(ConversationMessageTable)
                .values(**_message_values(message))
                .on_conflict_do_nothing(index_elements=[ConversationMessageTable.id])
                .returning(ConversationMessageTable.id)
            )
            if inserted_id is not None:
                inserted_messages.append(message)

        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return inserted_messages

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
                ConversationMessageTable.sequence_no.asc(),
            )
            .offset(max(offset, 0))
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()

        return [_table_to_message(row) for row in rows]

    async def list_messages_for_user(
        self,
        conversation_id: str,
        user_id: str,
        limit: int,
        offset: int = 0,
    ) -> list[ConversationMessage]:
        """按 user_id + conversation_id 读取消息，避免裸 session_id 越权。"""

        if limit <= 0:
            return []

        stmt: Select[tuple[ConversationMessageTable]] = (
            select(ConversationMessageTable)
            .join(ConversationTable)
            .where(
                ConversationMessageTable.conversation_id == conversation_id,
                ConversationTable.user_id == user_id,
            )
            .order_by(
                ConversationMessageTable.sequence_no.asc(),
            )
            .offset(max(offset, 0))
            .limit(limit)
        )
        rows = (await self._session.scalars(stmt)).all()

        return [_table_to_message(row) for row in rows]

    async def count_messages_for_user(
        self,
        *,
        conversation_id: str,
        user_id: str,
    ) -> int:
        """在数据库中统计当前用户会话消息，避免为计数加载完整正文。"""

        stmt = (
            select(func.count(ConversationMessageTable.id))
            .join(ConversationTable)
            .where(
                ConversationMessageTable.conversation_id == conversation_id,
                ConversationTable.user_id == user_id,
            )
        )
        return int((await self._session.scalar(stmt)) or 0)

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """按 ID 读取会话容器；不存在时返回 None。"""

        row = await self._session.get(ConversationTable, conversation_id)
        if row is None:
            return None

        return _table_to_conversation(row)

    async def get_conversation_for_user(
        self,
        conversation_id: str,
        user_id: str,
    ) -> Conversation | None:
        """按 user_id + conversation_id 读取会话容器。"""

        stmt: Select[tuple[ConversationTable]] = select(ConversationTable).where(
            ConversationTable.id == conversation_id,
            ConversationTable.user_id == user_id,
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None

        return _table_to_conversation(row)

    async def append_summary(self, summary: ConversationSummary) -> None:
        """追加一个新的会话摘要版本。

        摘要不覆盖旧版本，便于追溯“某个 summary 是从哪些消息压缩出来的”。
        """

        self._session.add(_summary_to_table(summary))
        await self._session.commit()

    async def get_latest_summary(
        self,
        conversation_id: str,
    ) -> ConversationSummary | None:
        """读取某个会话最新版本的 summary。"""

        stmt: Select[tuple[ConversationSummaryTable]] = (
            select(ConversationSummaryTable)
            .where(ConversationSummaryTable.conversation_id == conversation_id)
            .order_by(
                ConversationSummaryTable.version.desc(),
                ConversationSummaryTable.created_at.desc(),
                ConversationSummaryTable.id.desc(),
            )
            .limit(1)
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None

        return _table_to_summary(row)

    async def list_messages_after_summary(
        self,
        conversation_id: str,
        after_message_id: str | None,
        limit: int,
    ) -> list[ConversationMessage]:
        """读取 latest summary 之后还没有被摘要覆盖的消息。

        本阶段按创建时间在 Python 侧定位 after_message_id，逻辑更直观，
        数据量也符合学习项目当前的会话规模。
        """

        if limit <= 0:
            return []

        stmt: Select[tuple[ConversationMessageTable]] = (
            select(ConversationMessageTable)
            .where(ConversationMessageTable.conversation_id == conversation_id)
            .order_by(
                ConversationMessageTable.sequence_no.asc(),
            )
        )
        rows = list((await self._session.scalars(stmt)).all())
        if after_message_id is not None:
            for index, row in enumerate(rows):
                if row.id == after_message_id:
                    rows = rows[index + 1 :]
                    break

        return [_table_to_message(row) for row in rows[:limit]]


def _conversation_to_table(conversation: Conversation) -> ConversationTable:
    """把领域模型转换成 ORM 表对象。"""

    return ConversationTable(**_conversation_values(conversation))


def _conversation_values(conversation: Conversation) -> dict[str, object]:
    return {
        "id": conversation.id,
        "user_id": conversation.user_id,
        "external_session_id": (
            conversation.external_session_id
            or str(conversation.metadata.get("external_session_id") or conversation.id)
        ),
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "metadata_json": conversation.metadata,
    }


def _table_to_conversation(row: ConversationTable) -> Conversation:
    """把 ORM 表对象还原成领域模型。"""

    return Conversation(
        id=row.id,
        user_id=row.user_id,
        external_session_id=row.external_session_id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=row.metadata_json,
    )


def _message_to_table(message: ConversationMessage) -> ConversationMessageTable:
    """把消息领域模型转换成 ORM 表对象。"""

    return ConversationMessageTable(**_message_values(message))


def _message_values(message: ConversationMessage) -> dict[str, object]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role.value,
        "content": message.content,
        "created_at": message.created_at,
        "metadata_json": message.metadata,
    }


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


def _summary_to_table(summary: ConversationSummary) -> ConversationSummaryTable:
    """把 summary 领域模型转换成 ORM 表对象。"""

    return ConversationSummaryTable(
        id=summary.id,
        conversation_id=summary.conversation_id,
        summary_text=summary.summary_text,
        structured_summary_json=summary.structured_summary.model_dump(),
        version=summary.version,
        source_message_ids_json=summary.source_message_ids,
        source_message_count=summary.source_message_count,
        covered_until_message_id=summary.covered_until_message_id,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        metadata_json=summary.metadata,
    )


def _table_to_summary(row: ConversationSummaryTable) -> ConversationSummary:
    """把 ORM summary 记录还原成领域模型。"""

    return ConversationSummary(
        id=row.id,
        conversation_id=row.conversation_id,
        summary_text=row.summary_text,
        structured_summary=ConversationStructuredSummary.model_validate(
            row.structured_summary_json or {}
        ),
        version=row.version,
        source_message_ids=list(row.source_message_ids_json or []),
        source_message_count=row.source_message_count,
        covered_until_message_id=row.covered_until_message_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=row.metadata_json,
    )


@dataclass(frozen=True)
class ConversationListRecord:
    conversation: Conversation
    last_message_content: str | None
    last_message_role: str | None
    message_count: int


@dataclass(frozen=True)
class ConversationMessageRecord:
    message: ConversationMessage
    sequence_no: int


__all__ = [
    "ConversationListRecord",
    "ConversationMessageRecord",
    "PostgresConversationRepository",
]
