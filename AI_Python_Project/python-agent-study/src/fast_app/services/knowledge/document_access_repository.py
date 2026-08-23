from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.auth_tables import UserDepartmentTable, UserTable
from fast_app.db.document_access_tables import DocumentAccessGrantTable
from fast_app.db.gitlab_tables import GitLabDocumentTable, GitLabSourceTable


@dataclass(frozen=True)
class DocumentAccessGrantRecord:
    grant: DocumentAccessGrantTable
    grantee_username: str
    grantee_display_name: str | None
    grantee_primary_department_code: str | None
    repository_path: str
    document_department_code: str


@dataclass(frozen=True)
class GrantableDocumentRecord:
    document: GitLabDocumentTable
    department_code: str


class DocumentAccessRepository:
    """跨部门文档 grant 与运行时 doc_id 范围的 PostgreSQL adapter。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_grants(
        self,
        *,
        limit: int,
        target_account: str | None,
        doc_id: str | None,
        status: str | None,
        department_code: str | None,
        cursor_granted_at: datetime | None,
        cursor_grant_id: str | None,
    ) -> tuple[list[DocumentAccessGrantRecord], bool]:
        primary_department = UserDepartmentTable.__table__.alias("primary_department")
        stmt = (
            select(
                DocumentAccessGrantTable,
                UserTable.username,
                UserTable.display_name,
                primary_department.c.department_code,
                GitLabDocumentTable.repository_path,
                GitLabSourceTable.department_code,
            )
            .join(UserTable, UserTable.id == DocumentAccessGrantTable.grantee_user_id)
            .outerjoin(
                primary_department,
                and_(
                    primary_department.c.user_id == UserTable.id,
                    primary_department.c.is_primary.is_(True),
                ),
            )
            .join(
                GitLabDocumentTable,
                GitLabDocumentTable.doc_id == DocumentAccessGrantTable.doc_id,
            )
            .join(
                GitLabSourceTable,
                GitLabSourceTable.id == GitLabDocumentTable.source_id,
            )
        )
        if target_account:
            pattern = f"%{target_account.strip()}%"
            stmt = stmt.where(
                or_(
                    UserTable.username.ilike(pattern),
                    UserTable.email.ilike(pattern),
                )
            )
        if doc_id:
            stmt = stmt.where(DocumentAccessGrantTable.doc_id == doc_id)
        if status:
            stmt = stmt.where(DocumentAccessGrantTable.status == status)
        if department_code:
            stmt = stmt.where(GitLabSourceTable.department_code == department_code)
        if cursor_granted_at is not None and cursor_grant_id is not None:
            stmt = stmt.where(
                or_(
                    DocumentAccessGrantTable.granted_at < cursor_granted_at,
                    and_(
                        DocumentAccessGrantTable.granted_at == cursor_granted_at,
                        DocumentAccessGrantTable.id < cursor_grant_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            DocumentAccessGrantTable.granted_at.desc(),
            DocumentAccessGrantTable.id.desc(),
        ).limit(limit + 1)
        rows = (await self._session.execute(stmt)).all()
        records = [
            DocumentAccessGrantRecord(
                grant=row[0],
                grantee_username=row[1],
                grantee_display_name=row[2],
                grantee_primary_department_code=row[3],
                repository_path=row[4],
                document_department_code=row[5],
            )
            for row in rows[:limit]
        ]
        return records, len(rows) > limit

    async def resolve_target_account(self, account: str) -> UserTable | None:
        rows = list(
            (
                await self._session.scalars(
                    select(UserTable)
                    .where(
                        or_(
                            UserTable.username == account,
                            UserTable.email == account,
                        )
                    )
                    .limit(2)
                )
            ).all()
        )
        return rows[0] if len(rows) == 1 else None

    async def list_user_department_codes(self, user_id: str) -> set[str]:
        return set(
            (
                await self._session.scalars(
                    select(UserDepartmentTable.department_code).where(
                        UserDepartmentTable.user_id == user_id
                    )
                )
            ).all()
        )

    async def get_grantable_documents(
        self,
        doc_ids: set[str],
    ) -> dict[str, GrantableDocumentRecord]:
        if not doc_ids:
            return {}
        rows = (
            await self._session.execute(
                select(GitLabDocumentTable, GitLabSourceTable.department_code)
                .join(
                    GitLabSourceTable,
                    GitLabSourceTable.id == GitLabDocumentTable.source_id,
                )
                .where(
                    GitLabDocumentTable.doc_id.in_(doc_ids),
                    GitLabDocumentTable.status == "active",
                    GitLabSourceTable.status == "active",
                )
            )
        ).all()
        return {
            document.doc_id: GrantableDocumentRecord(
                document=document,
                department_code=department_code,
            )
            for document, department_code in rows
        }

    async def list_active_grants_for_user_and_documents(
        self,
        *,
        user_id: str,
        doc_ids: set[str],
    ) -> dict[str, DocumentAccessGrantTable]:
        if not doc_ids:
            return {}
        rows = (
            await self._session.scalars(
                select(DocumentAccessGrantTable).where(
                    DocumentAccessGrantTable.grantee_user_id == user_id,
                    DocumentAccessGrantTable.doc_id.in_(doc_ids),
                    DocumentAccessGrantTable.status == "active",
                    DocumentAccessGrantTable.revoked_at.is_(None),
                )
            )
        ).all()
        return {row.doc_id: row for row in rows}

    async def create_grant(
        self,
        *,
        user_id: str,
        doc_id: str,
        actor_user_id: str,
    ) -> DocumentAccessGrantTable:
        row = DocumentAccessGrantTable(
            id=f"document_access_{uuid4().hex}",
            grantee_user_id=user_id,
            doc_id=doc_id,
            granted_by_user_id=actor_user_id,
        )
        self._session.add(row)
        return row

    async def get_grant_record(
        self,
        grant_id: str,
        *,
        for_update: bool = False,
    ) -> DocumentAccessGrantRecord | None:
        primary_department = UserDepartmentTable.__table__.alias("primary_department")
        stmt = (
            select(
                DocumentAccessGrantTable,
                UserTable.username,
                UserTable.display_name,
                primary_department.c.department_code,
                GitLabDocumentTable.repository_path,
                GitLabSourceTable.department_code,
            )
            .join(UserTable, UserTable.id == DocumentAccessGrantTable.grantee_user_id)
            .outerjoin(
                primary_department,
                and_(
                    primary_department.c.user_id == UserTable.id,
                    primary_department.c.is_primary.is_(True),
                ),
            )
            .join(
                GitLabDocumentTable,
                GitLabDocumentTable.doc_id == DocumentAccessGrantTable.doc_id,
            )
            .join(
                GitLabSourceTable,
                GitLabSourceTable.id == GitLabDocumentTable.source_id,
            )
            .where(DocumentAccessGrantTable.id == grant_id)
        )
        if for_update:
            stmt = stmt.with_for_update(of=DocumentAccessGrantTable)
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return DocumentAccessGrantRecord(
            grant=row[0],
            grantee_username=row[1],
            grantee_display_name=row[2],
            grantee_primary_department_code=row[3],
            repository_path=row[4],
            document_department_code=row[5],
        )

    async def revoke_grant(
        self,
        row: DocumentAccessGrantTable,
        *,
        actor_user_id: str,
    ) -> None:
        if row.status == "revoked":
            return
        row.status = "revoked"
        row.revoked_by_user_id = actor_user_id
        row.revoked_at = datetime.now(UTC)

    async def list_active_granted_document_ids(self, user_id: str) -> list[str]:
        stmt: Select[tuple[str]] = (
            select(DocumentAccessGrantTable.doc_id)
            .join(
                GitLabDocumentTable,
                GitLabDocumentTable.doc_id == DocumentAccessGrantTable.doc_id,
            )
            .join(
                GitLabSourceTable,
                GitLabSourceTable.id == GitLabDocumentTable.source_id,
            )
            .where(
                DocumentAccessGrantTable.grantee_user_id == user_id,
                DocumentAccessGrantTable.status == "active",
                DocumentAccessGrantTable.revoked_at.is_(None),
                GitLabDocumentTable.status == "active",
                GitLabSourceTable.status == "active",
            )
            .order_by(DocumentAccessGrantTable.doc_id.asc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = [
    "DocumentAccessGrantRecord",
    "DocumentAccessRepository",
    "GrantableDocumentRecord",
]
