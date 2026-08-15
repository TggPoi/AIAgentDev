"""split TaskPlan active states around human confirmation

Revision ID: 20260815_0014
Revises: 20260813_0013
"""

from alembic import op


revision = "20260815_0014"
down_revision = "20260813_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_agent_task_plans_status",
        "agent_task_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_task_plans_status",
        "agent_task_plans",
        "status IN ("
        "'created','preparing_confirmation','waiting_confirmation',"
        "'executing_confirmed','completed','completed_with_warnings',"
        "'failed','cancelled')",
    )


def downgrade() -> None:
    # downgrade 明确恢复旧模型；它不是新代码的运行时兼容路径。
    op.execute(
        "UPDATE agent_task_plans SET status = 'running' "
        "WHERE status IN ('preparing_confirmation','executing_confirmed')"
    )
    op.drop_constraint(
        "ck_agent_task_plans_status",
        "agent_task_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_task_plans_status",
        "agent_task_plans",
        "status IN ("
        "'created','running','waiting_confirmation','completed',"
        "'completed_with_warnings','failed','cancelled')",
    )
