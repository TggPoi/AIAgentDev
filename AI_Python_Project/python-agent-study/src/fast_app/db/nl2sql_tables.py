from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from fast_app.db.base import Base


class Nl2SqlDatasetGrantTable(Base):
    """控制平面中的 Dataset/项目授权；不保存业务库凭证。"""

    __tablename__ = "nl2sql_dataset_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "subject_type",
            "subject_key",
            "scope_id",
            name="uq_nl2sql_dataset_grant_subject_scope",
        ),
        Index("idx_nl2sql_dataset_grants_lookup", "dataset_id", "enabled"),
    )


class Nl2SqlQueryAuditTable(Base):
    """NL2SQL 审计摘要；禁止保存真实参数和结果行。"""

    __tablename__ = "nl2sql_query_audits"

    query_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tokenized_question: Mapped[str] = mapped_column(Text, nullable=False)
    parameterized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_nl2sql_query_audits_user_created", "user_id", "created_at"),
        Index("idx_nl2sql_query_audits_dataset_created", "dataset_id", "created_at"),
    )


__all__ = ["Nl2SqlDatasetGrantTable", "Nl2SqlQueryAuditTable"]
