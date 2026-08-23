"""add conversation catalog fields

Revision ID: 20260824_0017
Revises: 20260824_0016
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0017"
down_revision: str | None = "20260824_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("external_session_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "title",
            sa.String(length=160),
            nullable=False,
            server_default=sa.text("'新会话'"),
        ),
    )
    op.execute(
        """
        update conversations
        set external_session_id = coalesce(
            nullif(metadata_json ->> 'external_session_id', ''),
            id
        )
        where external_session_id is null
        """
    )
    op.alter_column("conversations", "external_session_id", nullable=False)
    op.create_index(
        "uq_conversations_user_external_session",
        "conversations",
        ["user_id", "external_session_id"],
        unique=True,
    )
    op.create_index(
        "idx_conversations_user_updated_id",
        "conversations",
        ["user_id", sa.text("updated_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_conversations_user_updated_id",
        table_name="conversations",
    )
    op.drop_index(
        "uq_conversations_user_external_session",
        table_name="conversations",
    )
    op.drop_column("conversations", "title")
    op.drop_column("conversations", "external_session_id")
