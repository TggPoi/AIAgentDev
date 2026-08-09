"""在独立端口启动当前工作树，用于 Agentic Research 真实链路验收。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ["RAG_USE_MOCK"] = "false"

from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.main import app


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


if _enabled("AGENT_ACCEPTANCE_SKIP_AUTH"):
    async def acceptance_user() -> CurrentUserContext:
        return CurrentUserContext(
            user_id="agentic-research-acceptance-admin",
            is_authenticated=True,
            auth_source="jwt",
            global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
            global_permission_codes=[
                PermissionCode.KNOWLEDGE_DOCUMENT_READ.value,
                PermissionCode.KNOWLEDGE_READ_ALL.value,
                PermissionCode.AGENT_TOOL_WEB_SEARCH.value,
                PermissionCode.AGENT_TOOL_MCP.value,
                PermissionCode.DATA_QUERY_EXECUTE.value,
            ],
        )

    app.dependency_overrides[get_current_user_context] = acceptance_user

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.getenv("AGENT_ACCEPTANCE_PORT", "8010")),
)
