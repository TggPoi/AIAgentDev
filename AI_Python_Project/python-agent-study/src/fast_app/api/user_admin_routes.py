from fastapi import APIRouter, Depends, Path, Query, status

from fast_app.dependencies.user_admin_dependencies import (
    get_user_administration_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import UserStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.user_admin_schema import (
    AccessCatalogResponse,
    CreateManagedUserRequest,
    ManagedUserDetail,
    ManagedUserListResponse,
    ManagedUserPasswordResetResponse,
    ManagedUserStatusResponse,
    ReplaceManagedUserAccessRequest,
    ResetManagedUserPasswordRequest,
    UpdateManagedUserStatusRequest,
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
    user_id: str = Path(
        min_length=1,
        max_length=64,
        description="要查看的目标用户唯一 ID。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserDetail:
    """返回目标用户的直接授权、角色和有效权限快照。"""

    return await service.get_user(actor, user_id)


@router.post(
    "/users",
    response_model=ManagedUserDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_endpoint(
    request: CreateManagedUserRequest,
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserDetail:
    """在 actor 管理范围内创建账号及完整初始访问快照。"""

    return await service.create_user(actor, request)


@router.put("/users/{user_id}/access", response_model=ManagedUserDetail)
async def replace_user_access_endpoint(
    request: ReplaceManagedUserAccessRequest,
    user_id: str = Path(
        min_length=1,
        max_length=64,
        description="要原子替换访问快照的目标用户唯一 ID。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserDetail:
    """原子替换账号类型、部门成员关系、部门角色和直接权限。"""

    return await service.replace_user_access(actor, user_id, request)


@router.patch("/users/{user_id}/status", response_model=ManagedUserStatusResponse)
async def update_user_status_endpoint(
    request: UpdateManagedUserStatusRequest,
    user_id: str = Path(
        min_length=1,
        max_length=64,
        description="要启用或禁用的目标用户唯一 ID。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserStatusResponse:
    """切换账号状态；禁用同时撤销现有 refresh token 和 API Key。"""

    return await service.update_user_status(actor, user_id, request)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=ManagedUserPasswordResetResponse,
)
async def reset_user_password_endpoint(
    request: ResetManagedUserPasswordRequest,
    user_id: str = Path(
        min_length=1,
        max_length=64,
        description="要重置密码的目标用户唯一 ID。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: UserAdministrationService = Depends(get_user_administration_service),
) -> ManagedUserPasswordResetResponse:
    """为管理范围内账号设置新密码并撤销现有凭证。"""

    return await service.reset_user_password(actor, user_id, request)


__all__ = ["router"]
