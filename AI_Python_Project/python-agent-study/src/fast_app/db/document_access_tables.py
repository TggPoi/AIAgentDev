from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from fast_app.db.base import Base


class DocumentAccessGrantTable(Base):
    """按 doc_id 授予外部门用户只读访问的可审计事实。"""

    __tablename__ = "document_access_grants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grantee_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    doc_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("gitlab_documents.doc_id", ondelete="RESTRICT"),
        nullable=False,
    )
    granted_by_user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'active'"),
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_document_access_grants_status",
        ),
        CheckConstraint(
            "(status = 'active' AND revoked_by_user_id IS NULL AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_by_user_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_document_access_grants_revocation",
        ),
        Index(
            "idx_document_access_grants_grantee_status",
            "grantee_user_id",
            "status",
        ),
        Index("idx_document_access_grants_doc_status", "doc_id", "status"),
        Index(
            "uq_document_access_grants_active",
            "grantee_user_id",
            "doc_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


__all__ = ["DocumentAccessGrantTable"]
