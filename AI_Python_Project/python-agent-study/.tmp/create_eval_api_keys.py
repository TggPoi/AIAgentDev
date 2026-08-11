"""为 rbac_reader / rbac_operator 创建数据库 API Key（eval 认证修复）。

原始 key 只写一次到 .tmp/rag_eval_api_keys.json（该目录不提交仓库），
之后数据库只保存 hash，无法再次取回原始 key。
"""

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

TARGET_USERNAMES = ["rbac_reader", "rbac_operator"]
OUTPUT_PATH = Path(__file__).parent / "rag_eval_api_keys.json"


async def main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    result: dict[str, dict[str, str]] = {}
    try:
        async with session_factory() as session:
            repository = UserRepository(session=session)
            permission_repository = PermissionRepository(session=session)
            auth_service = AuthService(
                settings=settings,
                repository=repository,
                permission_service=PermissionService(permission_repository),
            )
            for username in TARGET_USERNAMES:
                user = await repository.get_user_by_username_or_email(username)
                if user is None:
                    raise SystemExit(f"用户不存在: {username}")
                current_user = await auth_service.build_current_user_context(
                    user=user,
                    auth_source="api_key",
                )
                created = await auth_service.create_api_key(
                    current_user=current_user,
                    name="rag-eval-local",
                    expires_at=None,
                )
                result[username] = {
                    "user_id": user.id,
                    "api_key_id": created.id,
                    "api_key": created.api_key,
                    "key_prefix": created.key_prefix,
                }
                print(f"created: username={username} user_id={user.id} "
                      f"key_prefix={created.key_prefix}")
    finally:
        await engine.dispose()

    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n原始 API Key 已写入 {OUTPUT_PATH}（仅本次可见，请妥善保留）")


if __name__ == "__main__":
    asyncio.run(main())
