"""验证刚创建的 eval API Key 能通过真实认证链。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.auth.user_repository import UserRepository

KEYS_PATH = Path(__file__).parent / "rag_eval_api_keys.json"


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    keys = json.loads(KEYS_PATH.read_text(encoding="utf-8"))

    try:
        async with session_factory() as session:
            repository = UserRepository(session=session)
            auth_service = AuthService(
                settings=settings,
                repository=repository,
                permission_service=PermissionService(
                    PermissionRepository(session=session)
                ),
            )
            for username, info in keys.items():
                context = await auth_service.authenticate_api_key(info["api_key"])
                if context is None:
                    raise SystemExit(f"认证失败: {username}")
                assert context.user_id == info["user_id"], "user_id 不一致"
                print(
                    f"OK {username}: user_id={context.user_id} "
                    f"auth_source={context.auth_source} "
                    f"departments={context.department_codes} "
                    f"global_roles={context.global_role_codes}"
                )
    finally:
        await engine.dispose()
    print("\n两个 API Key 均通过真实认证链校验。")


if __name__ == "__main__":
    asyncio.run(main())
