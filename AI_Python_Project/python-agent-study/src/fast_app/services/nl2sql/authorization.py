from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.nl2sql_tables import Nl2SqlDatasetGrantTable
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import Nl2SqlPermissionDeniedError
from fast_app.services.nl2sql.models import DatasetAuthorization, DatasetDefinition


class Nl2SqlAuthorizationService:
    """复用 CurrentUserContext 的 RBAC 快照并合并 Dataset Grant。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def authorize(
        self,
        user: CurrentUserContext,
        dataset: DatasetDefinition,
    ) -> DatasetAuthorization:
        """合并两层授权并返回只能由服务端产生的可信 Scope。

        RBAC 的 ``data:query:execute`` 回答“能否使用 NL2SQL”；Dataset Grant
        回答“能查询哪个 Dataset 的哪些项目”。两者缺一不可，之后 PostgreSQL
        RLS 还会使用这里返回的 scope_ids 再执行一次数据库级限制。
        """

        if not user.is_authenticated or not user.has_global_permission(
            PermissionCode.DATA_QUERY_EXECUTE.value
        ):
            raise Nl2SqlPermissionDeniedError("当前用户没有结构化数据查询权限")

        if user.has_global_role(RoleCode.SYSTEM_ADMIN.value):
            return DatasetAuthorization(dataset_id=dataset.dataset_id, scope_ids=("*",))

        # Dataset Grant 支持直接授予用户，也支持授予其全局角色或部门。这里只从
        # 已认证 CurrentUserContext 构造主体集合，不接收模型或客户端提交的主体。
        subjects = [("user", user.user_id)]
        subjects.extend(("role", item) for item in user.global_role_codes)
        subjects.extend(("department", item) for item in user.department_codes)
        if not subjects:
            raise Nl2SqlPermissionDeniedError("当前用户没有 Dataset Grant")

        now = datetime.now(timezone.utc)
        statement = select(Nl2SqlDatasetGrantTable.scope_id).where(
            Nl2SqlDatasetGrantTable.dataset_id == dataset.dataset_id,
            Nl2SqlDatasetGrantTable.enabled.is_(True),
            or_(
                Nl2SqlDatasetGrantTable.expires_at.is_(None),
                Nl2SqlDatasetGrantTable.expires_at > now,
            ),
            or_(
                *[
                    and_(
                        Nl2SqlDatasetGrantTable.subject_type == subject_type,
                        Nl2SqlDatasetGrantTable.subject_key == subject_key,
                    )
                    for subject_type, subject_key in subjects
                ]
            ),
        )
        scope_ids = tuple(sorted(set((await self._session.scalars(statement)).all())))
        if not scope_ids:
            raise Nl2SqlPermissionDeniedError("当前用户没有 Dataset Grant")
        if "*" in scope_ids:
            scope_ids = ("*",)
        # 这里返回的 scope_ids 会在只读事务中写入 app.scope_ids；连接归还池前
        # 事务级设置自动失效，因此连续服务不同用户时不会复用上一个人的 Scope。
        return DatasetAuthorization(dataset_id=dataset.dataset_id, scope_ids=scope_ids)


__all__ = ["Nl2SqlAuthorizationService"]
