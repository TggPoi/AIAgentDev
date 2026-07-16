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


class KnowledgeIngestionJobTable(Base):
    """持久化 Office 导入任务的状态机、租约、结果与追踪信息。"""

    __tablename__ = "knowledge_ingestion_jobs"

    # 输入与归属信息在任务创建后保持稳定，用于重跑时生成相同目标和 doc_id。
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'create'")
    )
    doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("departments.code", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    target_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    staged_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # status 表示任务终态，phase 表示 running 期间的细粒度处理进度。
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    phase: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    # worker_id 与 lease_expires_at 共同决定谁有权继续写共享产物。
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    excel_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    excel_profile_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    preview_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    diff_counts_json: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
        Index("idx_knowledge_ingestion_jobs_user_created", "user_id", "created_at"),
        Index("idx_knowledge_ingestion_jobs_status_created", "status", "created_at"),
        Index(
            "uq_knowledge_ingestion_jobs_active_target",
            "target_path",
            unique=True,
            # 历史成功/失败任务可以保留；仅禁止同一路径同时存在多个活动任务。
            postgresql_where=text(
                "status IN ('pending', 'running', 'awaiting_configuration')"
            ),
        ),
    )


class KnowledgeDocumentTable(Base):
    """Office 文档的服务端身份、目标路径与当前已提交版本。"""

    __tablename__ = "knowledge_documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    department_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("departments.code", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    current_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    # 不设置数据库外键，避免文档与 Profile 的双向依赖阻碍迁移和失败清理。
    active_excel_profile_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
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


class KnowledgeExcelImportProfileTable(Base):
    """保存经用户确认的 Excel 字段身份、主键与导入模式快照。"""

    __tablename__ = "knowledge_excel_import_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("knowledge_documents.doc_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_configs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    preview_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("doc_id", "version", name="uq_excel_profiles_doc_version"),
        Index("idx_excel_profiles_doc_status", "doc_id", "status"),
    )


__all__ = [
    "KnowledgeDocumentTable",
    "KnowledgeExcelImportProfileTable",
    "KnowledgeIngestionJobTable",
]
