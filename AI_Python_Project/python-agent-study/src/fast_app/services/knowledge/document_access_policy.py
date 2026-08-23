from __future__ import annotations

from collections.abc import Iterable

from fast_app.domain.knowledge_permissions import (
    DocumentAccessSource,
    RetrievalPermissionScope,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessRepository,
)
from fast_app.services.knowledge.knowledge_permission_policy import (
    KnowledgePermissionPolicy,
)


class DocumentAccessPolicy:
    """统一生成页面读取与 RAG 检索使用的文档访问裁决。"""

    def __init__(self, repository: DocumentAccessRepository) -> None:
        self._repository = repository
        self._base_policy = KnowledgePermissionPolicy()

    async def build_retrieval_scope(
        self,
        user: CurrentUserContext,
    ) -> RetrievalPermissionScope:
        base_scope = self._base_policy.build_scope(user)
        if base_scope.can_read_all or not user.is_authenticated:
            return base_scope
        granted_document_ids = (
            await self._repository.list_active_granted_document_ids(user.user_id)
        )
        return self._base_policy.build_scope(
            user,
            granted_document_ids=granted_document_ids,
        )

    async def can_read_document(
        self,
        user: CurrentUserContext,
        *,
        document_id: str,
        document_department_code: str,
        visibility: str,
        allowed_user_ids: Iterable[str] = (),
    ) -> bool:
        """按管理员、public、所属部门、active 精确 grant 的顺序裁决读取。"""

        return (
            await self.resolve_access_source(
                user,
                document_id=document_id,
                document_department_code=document_department_code,
                visibility=visibility,
                allowed_user_ids=allowed_user_ids,
            )
            is not None
        )

    async def resolve_access_source(
        self,
        user: CurrentUserContext,
        *,
        document_id: str,
        document_department_code: str,
        visibility: str,
        allowed_user_ids: Iterable[str] = (),
    ) -> DocumentAccessSource | None:
        scope = await self.build_retrieval_scope(user)
        return self.resolve_access_source_from_scope(
            scope,
            document_id=document_id,
            document_department_code=document_department_code,
            visibility=visibility,
            allowed_user_ids=allowed_user_ids,
        )

    @staticmethod
    def resolve_access_source_from_scope(
        scope: RetrievalPermissionScope,
        *,
        document_id: str,
        document_department_code: str,
        visibility: str,
        allowed_user_ids: Iterable[str] = (),
    ) -> DocumentAccessSource | None:
        if scope.can_read_all:
            return "admin"
        if scope.allow_public and visibility == "public":
            return "public"
        if document_department_code in scope.department_codes:
            return "department"
        if scope.user_id and scope.user_id in set(allowed_user_ids):
            return "original_acl"
        if document_id in scope.granted_document_ids:
            return "explicit_grant"
        return None


__all__ = ["DocumentAccessPolicy"]
