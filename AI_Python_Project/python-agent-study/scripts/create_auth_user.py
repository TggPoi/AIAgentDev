from __future__ import annotations

import argparse
import asyncio

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.auth_models import UserRole
from fast_app.services.auth_service import AuthService
from fast_app.services.user_repository import UserRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建本地认证用户")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        default=UserRole.USER.value,
    )
    parser.add_argument(
        "--permission",
        action="append",
        default=[],
        help="可重复传入，例如 --permission auth:api_keys:create",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            repository = UserRepository(session=session)
            auth_service = AuthService(settings=settings, repository=repository)
            user = await auth_service.create_user(
                username=args.username,
                password=args.password,
                email=args.email,
                display_name=args.display_name,
                role=UserRole(args.role),
                permissions=args.permission,
            )
            print(f"created_user_id={user.id}")
            print(f"username={user.username}")
            print(f"role={user.role.value}")
            print(f"permissions={','.join(user.permissions)}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
