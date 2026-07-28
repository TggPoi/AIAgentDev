from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fast_app.db.base import Base


class GitLabSourceTable(Base):
    __tablename__ = "gitlab_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    host_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    project_path: Mapped[str] = mapped_column(String(512), nullable=False)
    target_branch: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=text("'main'")
    )
    department_code: Mapped[str] = mapped_column(String(64), nullable=False)
    default_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'department'")
    )
    sync_token_env: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_token_env: Mapped[str] = mapped_column(String(128), nullable=False)
    webhook_secret_env: Mapped[str] = mapped_column(String(128), nullable=False)
    last_synced_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    desired_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "host_id",
            "project_id",
            name="uq_gitlab_sources_host_project",
        ),
    )


class GitLabWebhookDeliveryTable(Base):
    __tablename__ = "gitlab_webhook_deliveries"

    delivery_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    before_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_gitlab_delivery_source_created", "source_id", "created_at"),
    )


class GitLabSyncJobTable(Base):
    __tablename__ = "gitlab_sync_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    parent_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    child_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    change_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_gitlab_jobs_status_created", "status", "created_at"),
        Index(
            "uq_gitlab_jobs_active_source",
            "source_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running', 'publishing', 'retry_wait')"
            ),
        ),
    )


class GitLabDocumentTable(Base):
    __tablename__ = "gitlab_documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    blob_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    acl_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    acl_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'active'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "repository_path",
            name="uq_gitlab_documents_source_path",
        ),
        Index("idx_gitlab_documents_source_status", "source_id", "status"),
    )


class GitLabChangeRequestTable(Base):
    __tablename__ = "gitlab_change_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merge_request_iid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merge_request_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "task_plan_id", "source_id", name="uq_gitlab_change_request_task_source"
        ),
    )


class KnowledgePublicationTable(Base):
    __tablename__ = "knowledge_publications"

    version: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    previous_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("gitlab_sync_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgePublicationStateTable(Base):
    __tablename__ = "knowledge_publication_state"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, server_default=text("1")
    )
    active_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KnowledgeChangeEventTable(Base):
    __tablename__ = "knowledge_change_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    publication_version: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_publications.version", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("gitlab_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_documents_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_knowledge_change_events_version", "publication_version", "id"),
    )


__all__ = [
    "GitLabChangeRequestTable",
    "GitLabDocumentTable",
    "GitLabSourceTable",
    "GitLabSyncJobTable",
    "GitLabWebhookDeliveryTable",
    "KnowledgeChangeEventTable",
    "KnowledgePublicationStateTable",
    "KnowledgePublicationTable",
]
