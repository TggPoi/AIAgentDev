from collections.abc import Iterable, Mapping
from typing import Any

from fast_app.domain.knowledge_permissions import RetrievalPermissionScope
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext


KNOWLEDGE_READ_ALL_PERMISSION = PermissionCode.KNOWLEDGE_READ_ALL.value


class KnowledgePermissionPolicy:
    """知识库检索权限策略。

    它只负责把可信的 CurrentUserContext 转换成 RetrievalPermissionScope，
    不直接访问 ES / Milvus，也不读取客户端传入的权限字段。
    """

    def build_scope(
        self,
        user: CurrentUserContext,
        *,
        granted_document_ids: Iterable[str] = (),
    ) -> RetrievalPermissionScope:
        """根据当前用户身份生成服务端检索权限范围。"""

        can_read_all = (
            user.has_global_role(RoleCode.SYSTEM_ADMIN.value)
            or user.has_global_permission(KNOWLEDGE_READ_ALL_PERMISSION)
        )

        if can_read_all:
            return RetrievalPermissionScope(
                can_read_all=True,
                user_id=user.user_id,
                department_codes=[],
                granted_document_ids=[],
                allow_public=True,
            )

        return RetrievalPermissionScope(
            can_read_all=False,
            user_id=user.user_id if user.is_authenticated else None,
            department_codes=list(user.department_codes),
            granted_document_ids=sorted(set(granted_document_ids)),
            allow_public=True,
        )


def build_retrieval_filters_from_mapping(
    filters: Mapping[str, Any] | None,
) -> RetrievalFilters:
    """把 state / request 中用于查询过滤的 dict 条件字段转成内部业务对象 RetrievalFilters。

    这个 helper 同时处理客户端业务过滤和服务端权限过滤，供 Classic、
    LangGraph 和 RAG Agent 三条链路复用。
    """

    filters = filters or {}

    raw_section_path = filters.get("section_path") or []
    section_path = (
        [str(item) for item in raw_section_path]
        if isinstance(raw_section_path, list)
        else []
    )

    raw_department_codes = filters.get("department_codes") or []
    department_codes = (
        [str(item) for item in raw_department_codes]
        if isinstance(raw_department_codes, list)
        else []
    )

    raw_granted_document_ids = filters.get("granted_document_ids") or []
    granted_document_ids = (
        [str(item) for item in raw_granted_document_ids]
        if isinstance(raw_granted_document_ids, list)
        else []
    )

    source_path = filters.get("source_path")
    user_id = filters.get("user_id")

    return RetrievalFilters(
        source_path=str(source_path) if source_path else None,
        section_path=section_path,
        can_read_all=bool(filters.get("can_read_all", False)),
        user_id=str(user_id) if user_id else None,
        department_codes=department_codes,
        granted_document_ids=granted_document_ids,
        allow_public=bool(filters.get("allow_public", True)),
        knowledge_version=(
            int(filters["knowledge_version"])
            if filters.get("knowledge_version") is not None
            else None
        ),
    )


def merge_permission_scope_into_filter_dict(
    filters: Mapping[str, Any] | None,
    permission_scope: RetrievalPermissionScope | None,
    *,
    knowledge_version: int | None = None,
) -> dict[str, Any]:
    """把服务端权限 scope 合并进传给检索链路的 filters dict。"""

    merged = dict(filters or {})
    if permission_scope is None:
        if knowledge_version is not None:
            merged["knowledge_version"] = knowledge_version
        return merged

    merged.update(permission_scope.model_dump())
    if knowledge_version is not None:
        merged["knowledge_version"] = knowledge_version
    return merged


__all__ = [
    "KNOWLEDGE_READ_ALL_PERMISSION",
    "KnowledgePermissionPolicy",
    "build_retrieval_filters_from_mapping",
    "merge_permission_scope_into_filter_dict",
]
