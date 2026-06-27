"""create auth tables

Revision ID: 20260626_0003
Revises: 20260624_0002
Create Date: 2026-06-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260626_0003"
down_revision: str | None = "20260624_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "permissions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=24), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_fingerprint"),
    )
    op.create_index(
        "idx_api_keys_user_status",
        "api_keys",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "idx_refresh_tokens_user_status",
        "refresh_tokens",
        ["user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_refresh_tokens_user_status",
        table_name="refresh_tokens",
    )
    op.drop_table("refresh_tokens")
    op.drop_index("idx_api_keys_user_status", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("users")
