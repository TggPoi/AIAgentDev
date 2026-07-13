"""add deterministic conversation message sequence

Revision ID: 20260713_0006
Revises: 20260704_0005
Create Date: 2026-07-13 00:06:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260713_0006"
down_revision: str | None = "20260704_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_messages",
        sa.Column(
            "sequence_no",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_conversation_messages_conversation_sequence",
        "conversation_messages",
        ["conversation_id", "sequence_no"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_conversation_messages_conversation_sequence",
        table_name="conversation_messages",
    )
    op.drop_column("conversation_messages", "sequence_no")
