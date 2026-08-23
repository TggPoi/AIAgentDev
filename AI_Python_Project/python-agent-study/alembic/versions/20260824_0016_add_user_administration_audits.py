"""add user administration audit facts

Revision ID: 20260824_0016
Revises: 20260824_0015
Create Date: 2026-08-24 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260824_0016"
down_revision: str | None = "20260824_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_administration_audits",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('create_user', 'replace_access', 'update_status', 'reset_password')",
            name="ck_user_administration_audits_action",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_administration_audits_actor_created",
        "user_administration_audits",
        ["actor_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_user_administration_audits_target_created",
        "user_administration_audits",
        ["target_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_administration_audits_target_created",
        table_name="user_administration_audits",
    )
    op.drop_index(
        "idx_user_administration_audits_actor_created",
        table_name="user_administration_audits",
    )
    op.drop_table("user_administration_audits")
