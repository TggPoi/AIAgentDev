from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy.exc import IntegrityError

from fast_app.domain.auth_models import AccountType, UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.document_access_schema import (
    CreateDocumentAccessGrantsRequest,
    CreateDocumentAccessGrantsResponse,
    DocumentAccessGrantableDocumentItem,
    DocumentAccessGrantableDocumentListResponse,
    DocumentAccessGrantItem,
    DocumentAccessGrantListResponse,
    DocumentAccessGrantUser,
)
from fast_app.services.exceptions import (
    DocumentAccessGrantConflictError,
    DocumentAccessGrantInvalidError,
    DocumentAccessGrantNotFoundError,
    DocumentAccessPermissionDeniedError,
)
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessGrantRecord,
    DocumentAccessRepository,
    GrantableDocumentRecord,
)


class DocumentAccessService:
    """集中执行文档所属部门范围、精确账号和 grant 生命周期规则。"""

    def __init__(self, repository: DocumentAccessRepository) -> None:
        self._repository = repository

    async def list_grantable_documents(
        self,
        actor: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
        query: str | None,
        department_code: str | None,
    ) -> DocumentAccessGrantableDocumentListResponse:
        is_admin, manager_department = self._management_scope(actor)
        if not is_admin:
            if department_code is not None and department_code != manager_department:
                raise DocumentAccessPermissionDeniedError(
                    "部门主管不能扩大文档授权候选部门范围"
            )
            department_code = manager_department
        cursor_updated_at, cursor_doc_id = _decode_grantable_document_cursor(cursor)
        records, has_more = await self._repository.list_grantable_documents(
            limit=limit,
            department_code=department_code,
            query=query.strip() if query and query.strip() else None,
            cursor_updated_at=cursor_updated_at,
            cursor_doc_id=cursor_doc_id,
        )
        return DocumentAccessGrantableDocumentListResponse(
            items=[_to_grantable_document_item(record) for record in records],
            next_cursor=(
                _encode_grantable_document_cursor(
                    records[-1].document.updated_at,
                    records[-1].document.doc_id,
                )
                if has_more and records
                else None
            ),
        )

    async def list_grants(
        self,
        actor: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
        target_account: str | None,
        doc_id: str | None,
        status: str | None,
        department_code: str | None,
    ) -> DocumentAccessGrantListResponse:
        is_admin, manager_department = self._management_scope(actor)
        if not is_admin:
            if department_code is not None and department_code != manager_department:
                raise DocumentAccessPermissionDeniedError(
                    "部门主管不能扩大文档授权查询部门范围"
                )
            department_code = manager_department
        cursor_granted_at, cursor_grant_id = _decode_cursor(cursor)
        rows, has_more = await self._repository.list_grants(
            limit=limit,
            target_account=(
                target_account.strip() if target_account and target_account.strip() else None
            ),
            doc_id=doc_id,
            status=status,
            department_code=department_code,
            cursor_granted_at=cursor_granted_at,
            cursor_grant_id=cursor_grant_id,
        )
        return DocumentAccessGrantListResponse(
            items=[_to_item(row) for row in rows],
            next_cursor=(
                _encode_cursor(rows[-1].grant.granted_at, rows[-1].grant.id)
                if has_more and rows
                else None
            ),
        )

    async def create_grants(
        self,
        actor: CurrentUserContext,
        request: CreateDocumentAccessGrantsRequest,
    ) -> CreateDocumentAccessGrantsResponse:
        is_admin, manager_department = self._management_scope(actor)
        target = await self._repository.resolve_target_account(request.target_account)
        if target is None or target.status != UserStatus.ACTIVE.value:
            raise DocumentAccessGrantNotFoundError("不存在唯一匹配的 active 目标账号")
        doc_ids = set(request.document_ids)
        documents = await self._repository.get_grantable_documents(doc_ids)
        if set(documents) != doc_ids:
            raise DocumentAccessGrantNotFoundError("授权请求包含不存在或未激活的文档")
        if not is_admin and any(
            item.department_code != manager_department
            for item in documents.values()
        ):
            raise DocumentAccessPermissionDeniedError(
                "部门主管只能授权自己部门拥有的文档"
            )
        target_departments = await self._repository.list_user_department_codes(
            target.id
        )
        redundant_docs = sorted(
            doc_id
            for doc_id, item in documents.items()
            if _document_is_already_readable(
                item,
                target_user_id=target.id,
                target_departments=target_departments,
            )
        )
        if redundant_docs:
            raise DocumentAccessGrantInvalidError(
                "目标用户已经可以访问所选文档，无需跨部门授权",
                field="document_ids",
                field_code="invalid",
            )

        try:
            existing = await self._repository.list_active_grants_for_user_and_documents(
                user_id=target.id,
                doc_ids=doc_ids,
            )
            created_count = 0
            for doc_id in request.document_ids:
                if doc_id in existing:
                    continue
                existing[doc_id] = await self._repository.create_grant(
                    user_id=target.id,
                    doc_id=doc_id,
                    actor_user_id=actor.user_id,
                )
                created_count += 1
            await self._repository.flush()
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DocumentAccessGrantConflictError(
                "授权与并发创建的 active grant 冲突，请刷新后重试"
            ) from exc
        except Exception:
            await self._repository.rollback()
            raise

        items: list[DocumentAccessGrantItem] = []
        for doc_id in request.document_ids:
            record = await self._repository.get_grant_record(existing[doc_id].id)
            if record is None:
                raise DocumentAccessGrantNotFoundError("授权提交后无法读取 grant")
            items.append(_to_item(record))
        return CreateDocumentAccessGrantsResponse(
            items=items,
            created_count=created_count,
            existing_count=len(request.document_ids) - created_count,
        )

    async def revoke_grant(
        self,
        actor: CurrentUserContext,
        grant_id: str,
    ) -> DocumentAccessGrantItem:
        is_admin, manager_department = self._management_scope(actor)
        try:
            record = await self._repository.get_grant_record(
                grant_id,
                for_update=True,
            )
            if record is None:
                raise DocumentAccessGrantNotFoundError("文档授权不存在")
            if (
                not is_admin
                and record.document_department_code != manager_department
            ):
                raise DocumentAccessPermissionDeniedError(
                    "部门主管只能撤销自己部门文档的授权"
                )
            await self._repository.revoke_grant(
                record.grant,
                actor_user_id=actor.user_id,
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        refreshed = await self._repository.get_grant_record(grant_id)
        if refreshed is None:
            raise DocumentAccessGrantNotFoundError("撤销后无法读取文档授权")
        return _to_item(refreshed)

    @staticmethod
    def _management_scope(actor: CurrentUserContext) -> tuple[bool, str]:
        if not actor.is_authenticated:
            raise DocumentAccessPermissionDeniedError(
                "文档授权管理只允许已认证管理员或部门主管"
            )
        if actor.account_type == AccountType.ADMIN:
            return True, ""
        if (
            actor.account_type == AccountType.DEPARTMENT_MANAGER
            and actor.primary_department_code
        ):
            return False, actor.primary_department_code
        raise DocumentAccessPermissionDeniedError("当前用户没有文档授权管理权限")


def _to_item(record: DocumentAccessGrantRecord) -> DocumentAccessGrantItem:
    row = record.grant
    return DocumentAccessGrantItem(
        grant_id=row.id,
        document_id=row.doc_id,
        repository_path=record.repository_path,
        document_department_code=record.document_department_code,
        grantee=DocumentAccessGrantUser(
            user_id=row.grantee_user_id,
            username=record.grantee_username,
            display_name=record.grantee_display_name,
            primary_department_code=record.grantee_primary_department_code,
        ),
        status=row.status,
        granted_by_user_id=row.granted_by_user_id,
        granted_at=row.granted_at,
        revoked_by_user_id=row.revoked_by_user_id,
        revoked_at=row.revoked_at,
    )


def _to_grantable_document_item(
    record: GrantableDocumentRecord,
) -> DocumentAccessGrantableDocumentItem:
    file_name = PurePosixPath(record.document.repository_path).name
    return DocumentAccessGrantableDocumentItem(
        doc_id=record.document.doc_id,
        title=PurePosixPath(file_name).stem or file_name,
        repository_path=record.document.repository_path,
        document_department_code=record.department_code,
        document_type=record.document.document_type,
    )


def _document_is_already_readable(
    record: GrantableDocumentRecord,
    *,
    target_user_id: str,
    target_departments: set[str],
) -> bool:
    acl = record.document.acl_json if isinstance(record.document.acl_json, dict) else {}
    allowed_users = acl.get("allowed_users") or []
    return (
        acl.get("visibility") == "public"
        or record.department_code in target_departments
        or target_user_id in allowed_users
    )


def _encode_cursor(granted_at: datetime, grant_id: str) -> str:
    payload = json.dumps(
        {"granted_at": granted_at.isoformat(), "grant_id": grant_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _encode_grantable_document_cursor(updated_at: datetime, doc_id: str) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "doc_id": doc_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_grantable_document_cursor(
    cursor: str | None,
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        doc_id = payload["doc_id"]
        if updated_at.tzinfo is None or not isinstance(doc_id, str) or not doc_id:
            raise ValueError
        return updated_at, doc_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise DocumentAccessGrantInvalidError(
            "文档授权候选目录 cursor 无效"
        ) from exc


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        granted_at = datetime.fromisoformat(payload["granted_at"])
        grant_id = payload["grant_id"]
        if granted_at.tzinfo is None or not isinstance(grant_id, str) or not grant_id:
            raise ValueError
        return granted_at, grant_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise DocumentAccessGrantInvalidError("文档授权列表 cursor 无效") from exc


__all__ = ["DocumentAccessService"]
