from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fast_app.core.config import get_settings
from fast_app.db.nl2sql_tables import Nl2SqlDatasetGrantTable
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import Nl2SqlPermissionDeniedError
from fast_app.services.nl2sql.authorization import Nl2SqlAuthorizationService
from fast_app.services.nl2sql.models import DatasetDefinition


DATASET = DatasetDefinition(
    dataset_id="authorization_test",
    name="授权测试",
    domain="game",
    database_key="unused",
    privacy_classification="non_sensitive",
    scope_column="project_id",
    allowed_views=("analytics.asset_catalog",),
    report_supported=True,
    enabled=True,
)


async def denied(service: Nl2SqlAuthorizationService, user: CurrentUserContext) -> None:
    try:
        await service.authorize(user, DATASET)
    except Nl2SqlPermissionDeniedError:
        return
    raise AssertionError("authorization unexpectedly allowed")


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            transaction = await session.begin()
            grants = (
                ("user", "auth_user", "game_p1"),
                ("role", "data_analyst", "game_p2"),
                ("department", "game_design", "game_p3"),
            )
            for subject_type, subject_key, scope_id in grants:
                session.add(
                    Nl2SqlDatasetGrantTable(
                        id=str(uuid4()),
                        dataset_id=DATASET.dataset_id,
                        subject_type=subject_type,
                        subject_key=subject_key,
                        scope_id=scope_id,
                        enabled=True,
                        created_by="nl2sql_test",
                    )
                )
            await session.flush()
            service = Nl2SqlAuthorizationService(session)
            await denied(
                service,
                CurrentUserContext(
                    user_id="auth_user",
                    is_authenticated=True,
                    auth_source="jwt",
                ),
            )
            await denied(
                service,
                CurrentUserContext(
                    user_id="no_grant",
                    is_authenticated=True,
                    auth_source="jwt",
                    global_permission_codes=[PermissionCode.DATA_QUERY_EXECUTE.value],
                ),
            )
            authorized = await service.authorize(
                CurrentUserContext(
                    user_id="auth_user",
                    is_authenticated=True,
                    auth_source="jwt",
                    global_role_codes=["data_analyst"],
                    global_permission_codes=[PermissionCode.DATA_QUERY_EXECUTE.value],
                    department_codes=["game_design"],
                ),
                DATASET,
            )
            assert authorized.scope_ids == ("game_p1", "game_p2", "game_p3")
            admin = await service.authorize(
                CurrentUserContext(
                    user_id="admin",
                    is_authenticated=True,
                    auth_source="jwt",
                    global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
                    global_permission_codes=[PermissionCode.DATA_QUERY_EXECUTE.value],
                ),
                DATASET,
            )
            assert admin.scope_ids == ("*",)
            await transaction.rollback()
    finally:
        await engine.dispose()
    print("NL2SQL Dataset authorization checks passed")


if __name__ == "__main__":
    asyncio.run(main())
