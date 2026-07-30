from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.rag_agent.rag_agent_nodes import create_next_action_decision_node
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.exceptions import Nl2SqlSensitiveReportForbiddenError
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.service import Nl2SqlService


class RouterMustNotRun:
    async def route(self, **_: object) -> object:
        raise AssertionError("Dataset report must not call AgentTaskRouter")


async def main() -> None:
    settings = Settings(
        LANGSMITH_TRACING=False,
        NL2SQL_ENABLED=True,
        NL2SQL_REAL_ESTATE_TEST_ENABLED=True,
        NL2SQL_GAME_TEST_ENABLED=True,
        NL2SQL_DATABASE_URLS_JSON=(
            '{"real_estate_test":"postgresql://unused/real",'
            '"game_test":"postgresql://unused/game"}'
        ),
    )
    user = CurrentUserContext(
        user_id="routing_admin",
        is_authenticated=True,
        auth_source="jwt",
        global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
        global_permission_codes=[PermissionCode.DATA_QUERY_EXECUTE.value],
    )
    request = RagChatRequest(
        query="结合设计文档和资产数据创建分析报告",
        dataset_id="game_test",
        nl2sql_action="report",
    )
    state = build_rag_agent_initial_state(request, "run", current_user=user)
    node = create_next_action_decision_node(
        settings=settings,
        task_router=RouterMustNotRun(),  # type: ignore[arg-type]
        task_planner=AgentTaskPlanner(settings),
    )
    result = await node(state)
    assert result["route"] == "execute_task_plan"
    plan = result["agent_task_plan"]
    assert plan.research_policy.dataset_id == "game_test"
    assert plan.research_policy.nl2sql_action == "report"

    service = Nl2SqlService(
        settings=settings,
        registry=DatasetRegistry(settings),
        session=AsyncSession(),
    )
    try:
        await service.authorize_action(
            user=user,
            dataset_id="real_estate_test",
            action="report",
        )
    except Nl2SqlSensitiveReportForbiddenError:
        pass
    else:
        raise AssertionError("sensitive report was not rejected")
    print("NL2SQL RAG deterministic routing checks passed")


if __name__ == "__main__":
    asyncio.run(main())
