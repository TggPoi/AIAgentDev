"""add Office document registry, Excel profiles, and incremental job fields

Revision ID: 20260715_0008
Revises: 20260714_0007
Create Date: 2026-07-15 00:08:00
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260715_0008"
down_revision: str | None = "20260714_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _doc_id(source_path: str) -> str:
    """与运行时代码使用相同的规范化路径和 SHA-1 截断规则。"""

    normalized = Path(source_path).as_posix()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def upgrade() -> None:
    """新增文档/Profile 注册表，并扩展导入任务的版本和差异快照。"""

    op.create_table(
        "knowledge_documents",
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("department_code", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("current_sha256", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("active_excel_profile_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_code"], ["departments.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("doc_id"),
        sa.UniqueConstraint("source_path"),
    )
    op.create_table(
        "knowledge_excel_import_profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("profile_name", sa.String(length=128), nullable=False),
        sa.Column("sheet_configs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preview_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["doc_id"], ["knowledge_documents.doc_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "version", name="uq_excel_profiles_doc_version"),
    )
    op.create_index(
        "idx_excel_profiles_doc_status",
        "knowledge_excel_import_profiles",
        ["doc_id", "status"],
    )

    with op.batch_alter_table("knowledge_ingestion_jobs") as batch:
        batch.add_column(sa.Column("operation", sa.String(length=16), server_default="create", nullable=False))
        batch.add_column(sa.Column("doc_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("base_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("new_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("excel_profile_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("excel_profile_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.add_column(sa.Column("preview_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.add_column(
            sa.Column(
                "diff_counts_json",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            )
        )

    connection = op.get_bind()
    jobs = connection.execute(
        sa.text(
            "SELECT id, target_path, sha256, department_code, document_type, "
            "user_id, status FROM knowledge_ingestion_jobs ORDER BY created_at DESC"
        )
    ).mappings()
    registered_paths: set[str] = set()
    for job in jobs:
        doc_id = _doc_id(job["target_path"])
        connection.execute(
            sa.text(
                "UPDATE knowledge_ingestion_jobs SET doc_id=:doc_id, new_sha256=sha256 "
                "WHERE id=:job_id"
            ),
            {"doc_id": doc_id, "job_id": job["id"]},
        )
        # 只把已成功、且每个路径最新的一条历史任务登记为当前活动文档。
        if job["status"] != "succeeded" or job["target_path"] in registered_paths:
            continue
        registered_paths.add(job["target_path"])
        connection.execute(
            sa.text(
                "INSERT INTO knowledge_documents "
                "(doc_id, source_path, department_code, document_type, current_sha256, "
                "version, status, created_by, updated_by) VALUES "
                "(:doc_id, :source_path, :department_code, :document_type, :sha256, "
                "1, 'active', :user_id, :user_id)"
            ),
            {
                "doc_id": doc_id,
                "source_path": job["target_path"],
                "department_code": job["department_code"],
                "document_type": job["document_type"],
                "sha256": job["sha256"],
                "user_id": job["user_id"],
            },
        )

    op.drop_index(
        "uq_knowledge_ingestion_jobs_active_target",
        table_name="knowledge_ingestion_jobs",
    )
    op.create_index(
        "uq_knowledge_ingestion_jobs_active_target",
        "knowledge_ingestion_jobs",
        ["target_path"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'running', 'awaiting_configuration')"
        ),
    )


def downgrade() -> None:
    """删除增量导入结构，并恢复旧活动任务索引。"""

    op.drop_index(
        "uq_knowledge_ingestion_jobs_active_target",
        table_name="knowledge_ingestion_jobs",
    )
    op.create_index(
        "uq_knowledge_ingestion_jobs_active_target",
        "knowledge_ingestion_jobs",
        ["target_path"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    with op.batch_alter_table("knowledge_ingestion_jobs") as batch:
        for column in (
            "diff_counts_json",
            "preview_json",
            "excel_profile_snapshot_json",
            "excel_profile_id",
            "new_sha256",
            "base_sha256",
            "doc_id",
            "operation",
        ):
            batch.drop_column(column)
    op.drop_index(
        "idx_excel_profiles_doc_status",
        table_name="knowledge_excel_import_profiles",
    )
    op.drop_table("knowledge_excel_import_profiles")
    op.drop_table("knowledge_documents")
