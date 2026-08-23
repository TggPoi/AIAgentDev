from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_administration_repository import (
    UserAdministrationRepository,
)
from fast_app.services.auth.user_administration_service import (
    UserAdministrationService,
)


def get_user_administration_service(
    session: AsyncSession = Depends(get_db_session),
) -> UserAdministrationService:
    """为单个请求装配共享同一数据库事务上下文的用户管理模块。"""

    return UserAdministrationService(
        repository=UserAdministrationRepository(session),
        permission_service=PermissionService(PermissionRepository(session)),
    )


__all__ = ["get_user_administration_service"]
