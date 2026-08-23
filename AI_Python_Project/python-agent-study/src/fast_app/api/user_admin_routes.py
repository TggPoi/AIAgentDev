from fastapi import APIRouter, Depends, Query

from fast_app.dependencies.user_admin_dependencies import (
    get_user_administration_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.user_admin_schema import (
    AccessCatalogResponse,
    ManagedUserDetail,
    ManagedUserListResponse,
)
from fast_app.services.auth.user_administration_service import (
    UserAdministrationService,
)


router = APIRouter(prefix="/admin", tags=["user-administration"])


@router.get("/access/catalog", response_model=AccessCatalogResponse)
async def get_access_catalog_endpoint(
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> AccessCatalogResponse:
    """返回按当前 actor 管理范围裁剪后的账号、部门、角色和权限目录。"""

    return await service.get_access_catalog(actor)


@router.get("/users", response_model=ManagedUserListResponse)
async def list_users_endpoint(
    cursor: str | None = Query(default=None, description="上一页返回的不透明 keyset cursor。"),
    limit: int = Query(default=20, ge=1, le=100, description="本页最多返回的用户数。"),
    query: str | None = Query(default=None, max_length=128, description="匹配用户名、邮箱或展示名称的文本。"),
    status: UserStatus | None = Query(default=None, description="按 active 或 disabled 账号状态筛选。"),
    department_code: str | None = Query(default=None, max_length=64, description="管理员可选部门筛选；主管不能扩大为其他部门。"),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserListResponse:
    """按稳定 updated_at + user_id keyset 分页列出管理范围内账号。"""

    return await service.list_users(
        actor,
        cursor=cursor,
        limit=limit,
        query=query,
        status=status,
        department_code=department_code,
    )


@router.get("/users/{user_id}", response_model=ManagedUserDetail)
async def get_user_endpoint(
    user_id: str,
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserDetail:
    """返回目标用户的直接授权、角色和有效权限快照。"""

    return await service.get_user(actor, user_id)


__all__ = ["router"]
