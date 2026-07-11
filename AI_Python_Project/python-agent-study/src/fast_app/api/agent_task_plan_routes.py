import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from fast_app.core.config import Settings, get_settings
from fast_app.core.langsmith import (
    build_langsmith_metadata,
    build_langsmith_tags,
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


def _agent_task_plan_trace(
    settings: Settings,
    *,
    operation: str,
    task_plan_id: str,
    user_id: str,
):
    """创建普通确认和 SSE 确认共用的 root trace。"""

    return langsmith_trace(
        settings=settings,
        name=f"agent_task_plan.{operation}",
        run_type="chain",
        inputs={
            "task_plan_id": task_plan_id,
            "confirmed": True,
            "stream": operation == "confirm_stream",
        },
        metadata=build_langsmith_metadata(
            settings,
            sensitive_metadata={"user_id": user_id},
            pipeline_provider="rag_agent",
            operation=operation,
            task_plan_id=task_plan_id,
            trace_level="pipeline",
        ),
        tags=build_langsmith_tags(
            settings,
            "rag",
            "agent-task-plan",
            f"operation:{operation}",
            "pipeline:rag_agent",
            "trace-level:pipeline",
        ),
    )


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


@router.get("/{task_plan_id}/markdown", response_class=PlainTextResponse)
async def get_agent_task_plan_markdown_endpoint(
    task_plan_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
) -> str:
    """读取 Agent TaskPlan 的 Markdown 审查视图。"""

    plan = task_plan_store.load(task_plan_id)
    if plan.user_id != user.user_id and user.role != "admin":
        raise ToolPermissionDeniedError("只能查看自己创建的 Agent task plan")
    return task_plan_store.load_markdown(task_plan_id)


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

    async with _agent_task_plan_trace(
        settings,
        operation="confirm",
        task_plan_id=task_plan_id,
        user_id=user.user_id,
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


@router.post("/{task_plan_id}/confirm/stream")
async def confirm_agent_task_plan_stream_endpoint(
    task_plan_id: str,
    req: AgentTaskPlanConfirmRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """确认并执行 TaskPlan，同时用 SSE 输出执行进度。"""

    if req.confirmed is not True:
        raise AppServiceError("confirmed 必须为 true")

    return StreamingResponse(
        _confirm_task_plan_sse_generator(
            task_plan_id=task_plan_id,
            user=user,
            task_executor=task_executor,
            task_plan_store=task_plan_store,
            settings=settings,
        ),
        media_type="text/event-stream",
    )


async def _confirm_task_plan_sse_generator(
    task_plan_id: str,
    user: CurrentUserContext,
    task_executor: AgentTaskExecutor,
    task_plan_store: AgentTaskPlanStore,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """用现有 runtime 快照输出进度，避免给 executor 新增事件总线。"""

    async with _agent_task_plan_trace(
        settings,
        operation="confirm_stream",
        task_plan_id=task_plan_id,
        user_id=user.user_id,
    ) as trace_run:
        def build_confirm_config(child_name: str):
            return build_rag_langchain_pipeline_child_config(
                settings=settings,
                pipeline_provider="rag_agent",
                operation="confirm_stream",
                child_name=f"task_executor.{child_name}",
                run_name=f"agent_task_plan.confirm.task_executor.{child_name}",
                metadata={
                    "task_plan_id": task_plan_id,
                    "user_id": user.user_id,
                },
            )

        seen_sub_questions: set[str] = set()
        yield _format_sse_event(
            "agent_task_execution_started",
            {"task_plan_id": task_plan_id},
        )
        task = asyncio.create_task(
            task_executor.confirm(
                task_plan_id=task_plan_id,
                user=user,
                langchain_config_factory=build_confirm_config,
            )
        )
        try:
            while not task.done():
                try:
                    plan = task_plan_store.load(task_plan_id)
                    for event in _task_plan_progress_events(plan, seen_sub_questions):
                        yield event
                except Exception:
                    pass
                await asyncio.sleep(1)

            plan = await task
            for event in _task_plan_progress_events(plan, seen_sub_questions):
                yield event
            final_answer = plan.final_output.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                yield _format_sse_event(
                    "agent_task_final_synthesis_completed",
                    {
                        "task_plan_id": plan.task_plan_id,
                        "final_answer": final_answer,
                        "used_tools": plan.final_output.get("used_tools", []),
                    },
                )
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "task_plan_id": plan.task_plan_id,
                        "status": plan.status.value,
                        "executed": True,
                    }
                )
            yield _format_sse_event(
                "done",
                {
                    "task_plan_id": plan.task_plan_id,
                    "status": plan.status.value,
                    "task_plan": plan.model_dump(mode="json"),
                },
            )
        except Exception as exc:
            yield _format_sse_event(
                "error",
                {
                    "task_plan_id": task_plan_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )


def _task_plan_progress_events(
    plan: Any,
    seen_sub_questions: set[str],
) -> list[str]:
    """把 TaskPlan 快照转换成前端可消费的进度事件。"""

    events = [
        _format_sse_event(
            "agent_task_status",
            {"task_plan_id": plan.task_plan_id, "status": plan.status.value},
        )
    ]
    results = plan.final_output.get("sub_question_results", [])
    if not isinstance(results, list):
        return events
    for result in results:
        if not isinstance(result, dict):
            continue
        sub_question_id = str(result.get("sub_question_id") or "")
        if not sub_question_id or sub_question_id in seen_sub_questions:
            continue
        seen_sub_questions.add(sub_question_id)
        events.append(
            _format_sse_event(
                "agent_task_sub_question_completed",
                {
                    "task_plan_id": plan.task_plan_id,
                    "sub_question_id": sub_question_id,
                    "question": result.get("question"),
                    "status": result.get("status"),
                    "selected_tool": result.get("selected_tool"),
                    "answer": result.get("answer"),
                    "error": result.get("error"),
                    "tool_calls": result.get("tool_calls", []),
                },
            )
        )
    return events


def _format_sse_event(event: str, data: object) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"
    )


__all__ = ["router"]
