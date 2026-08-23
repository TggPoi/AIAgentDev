from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fast_app.db.base import Base


class ConversationTable(Base):
    """conversations 表：一条记录代表一个会话容器。"""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        server_default=text("'新会话'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # ORM 的 metadata 是保留属性，所以数据库字段用 metadata_json 显式避让。
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    messages: Mapped[list[ConversationMessageTable]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    summaries: Mapped[list[ConversationSummaryTable]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_conversations_user_external_session",
            "user_id",
            "external_session_id",
            unique=True,
        ),
        Index(
            "idx_conversations_user_updated_id",
            "user_id",
            updated_at.desc(),
            id.desc(),
        ),
    )


class ConversationMessageTable(Base):
    """conversation_messages 表：一条记录代表一次 user/assistant/system 发言。"""

    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sequence_no: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
    )
    conversation_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    conversation: Mapped[ConversationTable] = relationship(
        back_populates="messages",
    )

    __table_args__ = (
        Index(
            "idx_conversation_messages_conversation_created_at",
            "conversation_id",
            "created_at",
        ),
        Index(
            "idx_conversation_messages_conversation_sequence",
            "conversation_id",
            "sequence_no",
        ),
    )


class ConversationSummaryTable(Base):
    """conversation_summaries 表：保存窗口外历史的可追溯摘要版本。"""

    __tablename__ = "conversation_summaries"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_message_ids_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    source_message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    covered_until_message_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    conversation: Mapped[ConversationTable] = relationship(
        back_populates="summaries",
    )

    __table_args__ = (
        Index(
            "idx_conversation_summaries_conversation_version",
            "conversation_id",
            "version",
        ),
    )
