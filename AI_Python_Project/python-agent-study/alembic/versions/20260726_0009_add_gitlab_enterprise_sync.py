"""add GitLab enterprise document synchronization tables

Revision ID: 20260726_0009
Revises: 20260715_0008
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260726_0009"
down_revision: str | None = "20260715_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gitlab_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("host_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("project_path", sa.String(512), nullable=False),
        sa.Column("target_branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column("department_code", sa.String(64), nullable=False),
        sa.Column("default_visibility", sa.String(32), nullable=False, server_default="department"),
        sa.Column("sync_token_env", sa.String(128), nullable=False),
        sa.Column("agent_token_env", sa.String(128), nullable=False),
        sa.Column("webhook_secret_env", sa.String(128), nullable=False),
        sa.Column("last_synced_sha", sa.String(64), nullable=True),
        sa.Column("desired_sha", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "host_id",
            "project_id",
            name="uq_gitlab_sources_host_project",
        ),
    )
    op.create_table(
        "gitlab_webhook_deliveries",
        sa.Column("delivery_key", sa.String(128), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_uuid", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("before_sha", sa.String(64), nullable=True),
        sa.Column("after_sha", sa.String(64), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_gitlab_delivery_source_created", "gitlab_webhook_deliveries", ["source_id", "created_at"])
    op.create_table(
        "gitlab_sync_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("phase", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("base_sha", sa.String(64), nullable=True),
        sa.Column("target_sha", sa.String(64), nullable=False),
        sa.Column("candidate_version", sa.BigInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("child_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("change_counts_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_gitlab_jobs_status_created", "gitlab_sync_jobs", ["status", "created_at"])
    op.create_index(
        "uq_gitlab_jobs_active_source",
        "gitlab_sync_jobs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'publishing', 'retry_wait')"),
    )
    op.create_table(
        "gitlab_documents",
        sa.Column("doc_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repository_path", sa.String(1024), nullable=False),
        sa.Column("blob_id", sa.String(64), nullable=True),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("acl_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("chunk_strategy_version", sa.String(64), nullable=False),
        sa.Column("chunk_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("acl_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "repository_path", name="uq_gitlab_documents_source_path"),
    )
    op.create_index("idx_gitlab_documents_source_status", "gitlab_documents", ["source_id", "status"])
    op.create_table(
        "gitlab_change_requests",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_plan_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("base_sha", sa.String(64), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("merge_request_iid", sa.Integer(), nullable=True),
        sa.Column("merge_request_url", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_plan_id", "source_id", name="uq_gitlab_change_request_task_source"),
    )
    op.create_table(
        "knowledge_publications",
        sa.Column("version", sa.BigInteger(), primary_key=True),
        sa.Column("previous_version", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sync_job_id", sa.String(64), sa.ForeignKey("gitlab_sync_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_sha", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("validation_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "knowledge_publication_state",
        sa.Column("id", sa.Integer(), primary_key=True, server_default="1"),
        sa.Column("active_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_knowledge_publication_state_singleton"),
    )
    op.execute("INSERT INTO knowledge_publication_state (id, active_version) VALUES (1, 0)")
    op.create_table(
        "knowledge_change_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("publication_version", sa.BigInteger(), sa.ForeignKey("knowledge_publications.version", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("gitlab_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("affected_documents_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_knowledge_change_events_version", "knowledge_change_events", ["publication_version", "id"])


def downgrade() -> None:
    op.drop_index("idx_knowledge_change_events_version", table_name="knowledge_change_events")
    op.drop_table("knowledge_change_events")
    op.drop_table("knowledge_publication_state")
    op.drop_table("knowledge_publications")
    op.drop_table("gitlab_change_requests")
    op.drop_index("idx_gitlab_documents_source_status", table_name="gitlab_documents")
    op.drop_table("gitlab_documents")
    op.drop_index("uq_gitlab_jobs_active_source", table_name="gitlab_sync_jobs")
    op.drop_index("idx_gitlab_jobs_status_created", table_name="gitlab_sync_jobs")
    op.drop_table("gitlab_sync_jobs")
    op.drop_index("idx_gitlab_delivery_source_created", table_name="gitlab_webhook_deliveries")
    op.drop_table("gitlab_webhook_deliveries")
    op.drop_table("gitlab_sources")
