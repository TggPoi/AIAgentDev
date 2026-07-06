from typing import Any

from fastapi import APIRouter, Depends

from fast_app.dependencies.rag_dependencies import get_agent_task_plan_store
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_task_executor import AgentTaskPlanStore
from fast_app.services.exceptions import ToolPermissionDeniedError


router = APIRouter(prefix="/agent/task-plans", tags=["agent-task-plans"])


@router.get("/{task_plan_id}")
async def get_agent_task_plan_endpoint(
    task_plan_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
) -> dict[str, Any]:
    """读取 Agent 多步骤任务计划。"""

    plan = task_plan_store.load(task_plan_id)
    if plan.user_id != user.user_id and user.role != "admin":
        raise ToolPermissionDeniedError("只能查看自己创建的 Agent task plan")
    return plan.model_dump(mode="json")


__all__ = ["router"]
