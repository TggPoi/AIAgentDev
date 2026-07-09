from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from fast_app.core.config import Settings, get_settings
from fast_app.core.langsmith import (
    build_rag_langchain_pipeline_child_config,
    langsmith_trace,
)
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.dependencies.rag_dependencies import (
    get_agent_task_executor,
    get_agent_task_plan_store,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError


router = APIRouter(prefix="/agent/task-plans", tags=["agent-task-plans"])


class AgentTaskPlanConfirmRequest(BaseModel):
    confirmed: bool = Field(description="必须为 true，表示人工确认执行该 TaskPlan。")


class AgentTaskPlanConfirmResponse(BaseModel):
    task_plan_id: str
    status: str
    executed: bool
    message: str
    task_plan: dict[str, Any]
    request_id: str | None = None
    trace_id: str | None = None


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


@router.post("/{task_plan_id}/confirm", response_model=AgentTaskPlanConfirmResponse)
async def confirm_agent_task_plan_endpoint(
    task_plan_id: str,
    req: AgentTaskPlanConfirmRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanConfirmResponse:
    """确认并执行等待人工确认的 Agent TaskPlan。"""

    if req.confirmed is not True:
        raise AppServiceError("confirmed 必须为 true")

    async with langsmith_trace(
        settings=settings,
        name="agent_task_plan.confirm",
        run_type="chain",
        inputs={"task_plan_id": task_plan_id, "confirmed": req.confirmed},
        metadata={
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
            "app_name": settings.app_name,
            "app_env": settings.app_env,
            "pipeline_provider": "rag_agent",
            "operation": "confirm",
            "task_plan_id": task_plan_id,
            "user_id": user.user_id,
            "trace_level": "pipeline",
        },
        tags=[
            "rag",
            "agent-task-plan",
            "operation:confirm",
            "pipeline:rag_agent",
            "trace-level:pipeline",
            f"env:{settings.app_env}",
            *settings.langsmith_tag_list,
        ],
    ) as trace_run:
        def build_confirm_config(child_name: str):
            return build_rag_langchain_pipeline_child_config(
                settings=settings,
                pipeline_provider="rag_agent",
                operation="confirm",
                child_name=f"task_executor.{child_name}",
                run_name=f"agent_task_plan.confirm.task_executor.{child_name}",
                metadata={
                    "task_plan_id": task_plan_id,
                    "user_id": user.user_id,
                },
            )

        plan = await task_executor.confirm(
            task_plan_id=task_plan_id,
            user=user,
            langchain_config_factory=build_confirm_config,
        )
        if trace_run is not None:
            trace_run.add_outputs(
                {
                    "task_plan_id": plan.task_plan_id,
                    "status": plan.status.value,
                    "executed": True,
                }
            )

    return AgentTaskPlanConfirmResponse(
        task_plan_id=plan.task_plan_id,
        status=plan.status.value,
        executed=True,
        message="Agent task plan 已确认并执行",
        task_plan=plan.model_dump(mode="json"),
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


__all__ = ["router"]
