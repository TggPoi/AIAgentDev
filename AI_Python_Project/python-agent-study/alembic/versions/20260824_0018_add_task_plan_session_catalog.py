"""add TaskPlan session association and catalog indexes

Revision ID: 20260824_0018
Revises: 20260824_0017
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0018"
down_revision: str | None = "20260824_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_task_plans",
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        """
        update agent_task_plans
        set session_id = nullif(snapshot_json ->> 'session_id', '')
        where session_id is null
        """
    )
    op.create_index(
        "idx_agent_task_plans_owner_updated_id",
        "agent_task_plans",
        ["owner_user_id", sa.text("updated_at DESC"), sa.text("task_plan_id DESC")],
        unique=False,
    )
    op.create_index(
        "idx_agent_task_plans_owner_session_updated_id",
        "agent_task_plans",
        [
            "owner_user_id",
            "session_id",
            sa.text("updated_at DESC"),
            sa.text("task_plan_id DESC"),
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_task_plans_owner_session_updated_id",
        table_name="agent_task_plans",
    )
    op.drop_index(
        "idx_agent_task_plans_owner_updated_id",
        table_name="agent_task_plans",
    )
    op.drop_column("agent_task_plans", "session_id")
