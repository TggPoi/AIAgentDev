"""add PostgreSQL Agent TaskPlan facts, leases and idempotency

Revision ID: 20260813_0013
Revises: 20260731_0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260813_0013"
down_revision = "20260731_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_task_plans",
        sa.Column("task_plan_id", sa.String(128), primary_key=True),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("task_kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=False),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_fence_token", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("active_operation", sa.String(32), nullable=True),
        sa.Column("capacity_workload_type", sa.String(32), nullable=True),
        sa.Column("capacity_slot_no", sa.Integer(), nullable=True),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('created','running','waiting_confirmation','completed',"
            "'completed_with_warnings','failed','cancelled')",
            name="ck_agent_task_plans_status",
        ),
        sa.CheckConstraint("record_version >= 1", name="ck_agent_task_plans_record_version"),
        sa.CheckConstraint("lease_fence_token >= 0", name="ck_agent_task_plans_lease_fence_token"),
        sa.CheckConstraint(
            "(capacity_workload_type IS NULL) = (capacity_slot_no IS NULL)",
            name="ck_agent_task_plans_capacity_pair",
        ),
    )
    op.create_index("idx_agent_task_plans_owner_created", "agent_task_plans", ["owner_user_id", "created_at"])
    op.create_index("idx_agent_task_plans_status_updated", "agent_task_plans", ["status", "updated_at"])
    op.create_index("idx_agent_task_plans_lease_until", "agent_task_plans", ["lease_until"])

    op.create_table(
        "agent_task_plan_runtime_records",
        sa.Column(
            "task_plan_id",
            sa.String(128),
            sa.ForeignKey("agent_task_plans.task_plan_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("record_version >= 1", name="ck_agent_task_plan_runtime_record_version"),
    )
    op.create_index(
        "idx_agent_task_plan_runtime_expires",
        "agent_task_plan_runtime_records",
        ["expires_at"],
    )

    op.create_table(
        "agent_task_plan_commands",
        sa.Column("command_id", sa.String(64), primary_key=True),
        sa.Column(
            "task_plan_id",
            sa.String(128),
            sa.ForeignKey("agent_task_plans.task_plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("lease_fence_token", sa.BigInteger(), nullable=True),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "task_plan_id",
            "operation",
            "idempotency_key",
            name="uq_agent_task_plan_command_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','rejected','cancelled')",
            name="ck_agent_task_plan_commands_status",
        ),
    )
    op.create_index(
        "idx_agent_task_plan_commands_task_created",
        "agent_task_plan_commands",
        ["task_plan_id", "created_at"],
    )

    op.create_table(
        "agent_task_capacity_slots",
        sa.Column("workload_type", sa.String(32), primary_key=True),
        sa.Column("slot_no", sa.Integer(), primary_key=True),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_fence_token", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("task_plan_id", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("slot_no >= 1", name="ck_agent_task_capacity_slot_no"),
        sa.CheckConstraint(
            "workload_type IN ('research','document')",
            name="ck_agent_task_capacity_workload_type",
        ),
        sa.CheckConstraint("lease_fence_token >= 0", name="ck_agent_task_capacity_fence_token"),
    )
    op.create_index(
        "idx_agent_task_capacity_lease",
        "agent_task_capacity_slots",
        ["workload_type", "lease_until"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_task_capacity_lease", table_name="agent_task_capacity_slots")
    op.drop_table("agent_task_capacity_slots")
    op.drop_index("idx_agent_task_plan_commands_task_created", table_name="agent_task_plan_commands")
    op.drop_table("agent_task_plan_commands")
    op.drop_index("idx_agent_task_plan_runtime_expires", table_name="agent_task_plan_runtime_records")
    op.drop_table("agent_task_plan_runtime_records")
    op.drop_index("idx_agent_task_plans_lease_until", table_name="agent_task_plans")
    op.drop_index("idx_agent_task_plans_status_updated", table_name="agent_task_plans")
    op.drop_index("idx_agent_task_plans_owner_created", table_name="agent_task_plans")
    op.drop_table("agent_task_plans")
