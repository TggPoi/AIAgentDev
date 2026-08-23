from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.gitlab_tables import GitLabDocumentTable, GitLabSourceTable
from fast_app.domain.knowledge_permissions import RetrievalPermissionScope


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    document: GitLabDocumentTable
    source: GitLabSourceTable


class KnowledgeDocumentReadRepository:
    """只读查询正式 GitLab manifest，并在 SQL 层应用可信文档 ACL。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_documents(
        self,
        *,
        scope: RetrievalPermissionScope,
        limit: int,
        query: str | None,
        department_code: str | None,
        document_type: str | None,
        cursor_updated_at: datetime | None,
        cursor_doc_id: str | None,
    ) -> tuple[list[KnowledgeDocumentRecord], bool]:
        stmt = (
            select(GitLabDocumentTable, GitLabSourceTable)
            .join(
                GitLabSourceTable,
                GitLabSourceTable.id == GitLabDocumentTable.source_id,
            )
            .where(
                GitLabDocumentTable.status == "active",
                GitLabSourceTable.status == "active",
            )
        )
        permission_clause = _permission_clause(scope)
        if permission_clause is not None:
            stmt = stmt.where(permission_clause)
        if query:
            pattern = f"%{_escape_like(query)}%"
            stmt = stmt.where(
                or_(
                    GitLabDocumentTable.repository_path.ilike(
                        pattern,
                        escape="\\",
                    ),
                    GitLabDocumentTable.doc_id.ilike(pattern, escape="\\"),
                )
            )
        if department_code:
            stmt = stmt.where(GitLabSourceTable.department_code == department_code)
        if document_type:
            stmt = stmt.where(GitLabDocumentTable.document_type == document_type)
        if cursor_updated_at is not None and cursor_doc_id is not None:
            stmt = stmt.where(
                or_(
                    GitLabDocumentTable.updated_at < cursor_updated_at,
                    and_(
                        GitLabDocumentTable.updated_at == cursor_updated_at,
                        GitLabDocumentTable.doc_id < cursor_doc_id,
                    ),
                )
            )
        rows = (
            await self._session.execute(
                stmt.order_by(
                    GitLabDocumentTable.updated_at.desc(),
                    GitLabDocumentTable.doc_id.desc(),
                ).limit(limit + 1)
            )
        ).all()
        records = [
            KnowledgeDocumentRecord(document=row[0], source=row[1])
            for row in rows[:limit]
        ]
        return records, len(rows) > limit

    async def get_document(self, doc_id: str) -> KnowledgeDocumentRecord | None:
        row = (
            await self._session.execute(
                select(GitLabDocumentTable, GitLabSourceTable)
                .join(
                    GitLabSourceTable,
                    GitLabSourceTable.id == GitLabDocumentTable.source_id,
                )
                .where(
                    GitLabDocumentTable.doc_id == doc_id,
                    GitLabDocumentTable.status == "active",
                    GitLabSourceTable.status == "active",
                )
            )
        ).one_or_none()
        return (
            KnowledgeDocumentRecord(document=row[0], source=row[1])
            if row is not None
            else None
        )


def _permission_clause(scope: RetrievalPermissionScope):
    if scope.can_read_all:
        return None
    clauses = []
    if scope.allow_public:
        clauses.append(
            GitLabDocumentTable.acl_json["visibility"].as_string() == "public"
        )
    if scope.department_codes:
        clauses.append(GitLabSourceTable.department_code.in_(scope.department_codes))
    if scope.user_id:
        clauses.append(
            GitLabDocumentTable.acl_json["allowed_users"].contains([scope.user_id])
        )
    if scope.granted_document_ids:
        clauses.append(
            GitLabDocumentTable.doc_id.in_(scope.granted_document_ids)
        )
    return or_(*clauses) if clauses else GitLabDocumentTable.doc_id == "__deny_all__"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["KnowledgeDocumentReadRepository", "KnowledgeDocumentRecord"]
