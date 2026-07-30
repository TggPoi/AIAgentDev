"""幂等地给真实员工账号授予 NL2SQL 功能角色和一个 Dataset Scope。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import get_settings
from fast_app.db.auth_tables import RoleTable, UserRoleTable, UserTable
from fast_app.db.nl2sql_tables import Nl2SqlDatasetGrantTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import RoleCode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="给已有员工账号授予 data_analyst 和一个直接用户 Dataset Grant"
    )
    parser.add_argument("--username", required=True, help="已有平台员工账号 username")
    parser.add_argument("--dataset-id", required=True, help="目标 Dataset ID")
    parser.add_argument("--scope-id", required=True, help="Dataset 内允许访问的项目 ID")
    parser.add_argument(
        "--created-by",
        default="nl2sql_employee_access_script",
        help="写入 Grant 审计字段的操作者标识",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            user = await session.scalar(
                select(UserTable).where(UserTable.username == args.username.strip().lower())
            )
            if user is None:
                raise RuntimeError(f"员工账号不存在: {args.username}")

            analyst_role = await session.scalar(
                select(RoleTable).where(RoleTable.code == RoleCode.DATA_ANALYST.value)
            )
            if analyst_role is None:
                raise RuntimeError("data_analyst 角色不存在，请先执行最新 Alembic 迁移")

            existing_user_role = await session.scalar(
                select(UserRoleTable).where(
                    UserRoleTable.user_id == user.id,
                    UserRoleTable.role_id == analyst_role.id,
                )
            )
            role_action = "existing"
            if existing_user_role is None:
                session.add(
                    UserRoleTable(
                        id=f"user_role_{uuid4().hex}",
                        user_id=user.id,
                        role_id=analyst_role.id,
                    )
                )
                role_action = "created"

            existing_grant = await session.scalar(
                select(Nl2SqlDatasetGrantTable).where(
                    Nl2SqlDatasetGrantTable.dataset_id == args.dataset_id,
                    Nl2SqlDatasetGrantTable.subject_type == "user",
                    Nl2SqlDatasetGrantTable.subject_key == user.id,
                    Nl2SqlDatasetGrantTable.scope_id == args.scope_id,
                )
            )
            grant_action = "existing"
            if existing_grant is None:
                session.add(
                    Nl2SqlDatasetGrantTable(
                        id=str(uuid4()),
                        dataset_id=args.dataset_id,
                        subject_type="user",
                        subject_key=user.id,
                        scope_id=args.scope_id,
                        enabled=True,
                        created_by=args.created_by,
                    )
                )
                grant_action = "created"
            else:
                existing_grant.enabled = True
                existing_grant.expires_at = None

            await session.commit()

            print(f"username={user.username}")
            print(f"user_id={user.id}")
            print(f"data_analyst_role={role_action}")
            print(
                "dataset_grant="
                f"{grant_action}:{args.dataset_id}:user:{user.id}:{args.scope_id}"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
