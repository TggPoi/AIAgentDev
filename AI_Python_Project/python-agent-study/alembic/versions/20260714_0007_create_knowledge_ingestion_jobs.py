"""create knowledge ingestion jobs

Revision ID: 20260714_0007
Revises: 20260713_0006
Create Date: 2026-07-14 00:07:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260714_0007"
down_revision: str | None = "20260713_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建导入任务表及领取、查询和活动目标唯一性所需索引。"""

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("department_code", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=False),
        sa.Column("staged_path", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("phase", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["department_code"], ["departments.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_knowledge_ingestion_jobs_user_created",
        "knowledge_ingestion_jobs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_knowledge_ingestion_jobs_status_created",
        "knowledge_ingestion_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_knowledge_ingestion_jobs_active_target",
        "knowledge_ingestion_jobs",
        ["target_path"],
        unique=True,
        # 终态任务保留审计记录，但不阻止同一路径今后再次创建任务。
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    """按依赖顺序删除导入任务索引和数据表。"""

    op.drop_index(
        "uq_knowledge_ingestion_jobs_active_target",
        table_name="knowledge_ingestion_jobs",
    )
    op.drop_index(
        "idx_knowledge_ingestion_jobs_status_created",
        table_name="knowledge_ingestion_jobs",
    )
    op.drop_index(
        "idx_knowledge_ingestion_jobs_user_created",
        table_name="knowledge_ingestion_jobs",
    )
    op.drop_table("knowledge_ingestion_jobs")
