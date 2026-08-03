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
    get_prompt_guard_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.domain.agent_tool_permissions import RoleCode
from fast_app.domain.research_task_plan import (
    ResearchTaskPlan,
    build_research_task_plan_public_view,
)
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.rag.guarded_streaming import (
    GuardedStreamState,
    guarded_answer_delta_events,
    text_to_async_tokens,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService


router = APIRouter(prefix="/agent/task-plans", tags=["agent-task-plans"])


def _public_plan_payload(plan) -> dict[str, Any]:
    """Research 使用安全 Public View；Document 保持现有 API 契约。"""

    if isinstance(plan, ResearchTaskPlan):
        return build_research_task_plan_public_view(plan).model_dump(mode="json")
    return plan.model_dump(mode="json")


class AgentTaskPlanConfirmRequest(BaseModel):
    confirmed: bool = Field(description="必须为 true，表示人工确认执行该 TaskPlan。")


class AgentTaskPlanConfirmResponse(BaseModel):
    task_plan_id: str = Field(description="被确认执行的 TaskPlan ID。")
    status: str = Field(description="确认执行后的 TaskPlan 状态。")
    executed: bool = Field(description="是否已进入并完成真实确认执行。")
    message: str = Field(description="供前端展示的确认执行结果摘要。")
    task_plan: dict[str, Any] = Field(description="确认执行后的完整 TaskPlan 快照。")
    request_id: str | None = Field(default=None, description="本次确认请求 ID。")
    trace_id: str | None = Field(default=None, description="本次确认链路追踪 ID。")


class AgentTaskPlanControlResponse(BaseModel):
    task_plan_id: str = Field(description="被控制的 TaskPlan ID。")
    status: str = Field(description="取消、重试或恢复后的 TaskPlan 状态。")
    message: str = Field(description="供前端展示的控制操作结果摘要。")
    request_id: str | None = Field(default=None, description="本次控制请求 ID。")
    trace_id: str | None = Field(default=None, description="本次控制链路追踪 ID。")


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
            "confirmed": operation.startswith("confirm"),
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
    if plan.user_id != user.user_id and not user.has_global_role(
        RoleCode.SYSTEM_ADMIN.value
    ):
        raise ToolPermissionDeniedError("只能查看自己创建的 Agent task plan")
    return _public_plan_payload(plan)


@router.get("/{task_plan_id}/markdown", response_class=PlainTextResponse)
async def get_agent_task_plan_markdown_endpoint(
    task_plan_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
) -> str:
    """读取 Agent TaskPlan 的 Markdown 审查视图。"""

    plan = task_plan_store.load(task_plan_id)
    if plan.user_id != user.user_id and not user.has_global_role(
        RoleCode.SYSTEM_ADMIN.value
    ):
        raise ToolPermissionDeniedError("只能查看自己创建的 Agent task plan")
    return task_plan_store.load_markdown(task_plan_id)


@router.post("/{task_plan_id}/cancel", response_model=AgentTaskPlanControlResponse)
async def cancel_agent_task_plan_endpoint(
    task_plan_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanControlResponse:
    """取消 TaskPlan；运行中的 Tool Loop 会在当前轮次屏障后停止。"""

    async with _agent_task_plan_trace(
        settings,
        operation="cancel",
        task_plan_id=task_plan_id,
        user_id=user.user_id,
    ) as trace_run:
        plan = await task_executor.cancel(task_plan_id, user=user)
        if trace_run is not None:
            trace_run.add_outputs(
                {"task_plan_id": plan.task_plan_id, "status": plan.status.value}
            )
    return AgentTaskPlanControlResponse(
        task_plan_id=plan.task_plan_id,
        status=plan.status.value,
        message="Agent task plan 已取消",
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.post("/{task_plan_id}/retry", response_model=AgentTaskPlanControlResponse)
async def retry_agent_task_plan_endpoint(
    task_plan_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanControlResponse:
    """恢复可重试的研究任务或文档 Tool Loop。"""

    async with _agent_task_plan_trace(
        settings,
        operation="retry",
        task_plan_id=task_plan_id,
        user_id=user.user_id,
    ) as trace_run:
        plan = await task_executor.resume(task_plan_id, user=user)
        if trace_run is not None:
            trace_run.add_outputs(
                {"task_plan_id": plan.task_plan_id, "status": plan.status.value}
            )
    return AgentTaskPlanControlResponse(
        task_plan_id=plan.task_plan_id,
        status=plan.status.value,
        message="Agent task plan 已按最近完整快照恢复",
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


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
        task_plan=_public_plan_payload(plan),
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
    prompt_guard: PromptGuardService = Depends(get_prompt_guard_service),
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
            prompt_guard=prompt_guard,
            settings=settings,
        ),
        media_type="text/event-stream",
    )


async def _confirm_task_plan_sse_generator(
    task_plan_id: str,
    user: CurrentUserContext,
    task_executor: AgentTaskExecutor,
    task_plan_store: AgentTaskPlanStore,
    prompt_guard: PromptGuardService,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """确认并执行 TaskPlan，同时把执行中的进度转换为 SSE。

    ``task_executor.confirm()`` 本身返回的是最终完成后的 ``plan``，不会逐条
    ``yield`` 子问题结果。执行器每完成一个子问题会先把最新 ``plan`` 保存到
    runtime JSON 快照；本生成器在确认任务运行期间每秒读取一次该快照，将新出现的
    子问题结果发给前端。因此无需为了流式进度额外给执行器设计事件总线。
    """

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

        # 轮询会重复读到已经完成的子问题；用 id 去重，确保前端每题只收到一次完成事件。
        seen_sub_questions: set[str] = set()
        seen_steps: set[str] = set()
        seen_research_events: set[str] = set()
        yield _format_sse_event(
            "agent_task_execution_started",
            {"task_plan_id": task_plan_id},
        )

        # confirm 在后台继续执行，这个生成器才能同时轮询快照并向 HTTP 连接 yield SSE。
        task = asyncio.create_task(
            # 让 `task_executor.confirm(...)` 在后台开始执行，但当前 SSE 函数不等待它完成
            task_executor.confirm(
                task_plan_id=task_plan_id,
                user=user,
                langchain_config_factory=build_confirm_config,
            )
        )
        try:
            while not task.done():
                try:
                    # task_executor 会在 单个子问题 完成时更新 当前任务的json文件 快照；这里读取的是“目前为止”的进度。
                    plan = task_plan_store.load(task_plan_id)

                    # 把当前读取到的 任务快照进度 转换为 sse事件 响应给前端显示任务状态
                    for event in _task_plan_progress_events(
                        plan, seen_sub_questions, seen_steps, seen_research_events
                    ):
                        yield event
                
                # 轮询快照的异常被忽略 例如后台任务刚启动、快照文件还没写好时，`load()` 可能暂时失败。这里不让一次短暂读取失败直接断开 SSE；等一秒后再试。
                except Exception:
                    # 任务刚启动、快照暂不可读等短暂情况不应中断已建立的 SSE 连接；下次轮询重试。
                    pass
                await asyncio.sleep(1)

            # confirm 已结束，await 取得最终 plan，并补发最后一次快照中尚未发送的子问题事件。
            plan = await task

            for event in _task_plan_progress_events(
                plan, seen_sub_questions, seen_steps, seen_research_events
            ):
                yield event

            # prompt_guard 开始校验 最终回答
            if isinstance(plan, ResearchTaskPlan):
                final_answer = plan.final_output.answer if plan.final_output is not None else None
            else:
                final_answer = plan.final_output.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                yield _format_sse_event(
                    "sources",
                    {
                        "sources": (
                            _public_plan_payload(plan).get("evidence", [])
                            if isinstance(plan, ResearchTaskPlan)
                            else plan.final_output.get("sources", [])
                        )
                    },
                )
                stream_state = GuardedStreamState()

                # 开始消费llm生成的token，组装为多个chunk，直到达到最大长度或句号边界时，交给 Prompt Guard 检查。
                async for event in guarded_answer_delta_events(
                    text_to_async_tokens(final_answer),
                    prompt_guard=prompt_guard,
                    source="agent_task_plan.confirm_stream.output",
                    mode="buffer_then_emit",
                    max_chars=settings.prompt_guard_stream_chunk_max_chars,
                    state=stream_state,
                ):
                    yield _format_sse_event(event.event, event.data)

                yield _format_sse_event(
                    "agent_task_final_synthesis_completed",
                    {
                        "task_plan_id": plan.task_plan_id,
                        "status": plan.status.value,
                        "used_tools": (
                            plan.final_output.used_tools
                            if isinstance(plan, ResearchTaskPlan)
                            else plan.final_output.get("used_tools", [])
                        ),
                        "warnings": (
                            plan.final_output.warnings
                            if isinstance(plan, ResearchTaskPlan)
                            else plan.final_output.get("warnings", [])
                        ),
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
    seen_steps: set[str] | None = None,
    seen_research_events: set[str] | None = None,
) -> list[str]:
    """把一次 TaskPlan 快照中可观察到的状态和新增子问题结果转为 SSE。

    每次轮询都发送当前总状态（如 ``running`` 或 ``completed``）；而子问题完成
    事件通过 ``seen_sub_questions`` 去重，只在该 id 第一次出现在快照中时发送。
    """

    events = [
        _format_sse_event(
            "agent_task_status",
            {"task_plan_id": plan.task_plan_id, "status": plan.status.value},
        )
    ]
    seen_steps = seen_steps if seen_steps is not None else set()
    seen_research_events = (
        seen_research_events if seen_research_events is not None else set()
    )
    if isinstance(plan, ResearchTaskPlan):
        research_events = [item.model_dump(mode="json") for item in plan.progress.events]
        for sub_question_id, worker in plan.progress.workers.items():
            if worker.status != "running":
                continue
            event_key = f"sub_question_started:{sub_question_id}:{worker.wave}"
            if event_key in seen_research_events:
                continue
            seen_research_events.add(event_key)
            events.append(
                _format_sse_event(
                    "sub_question_started",
                    {
                        "task_plan_id": plan.task_plan_id,
                        "sub_question_id": sub_question_id,
                        "wave": worker.wave,
                        "attempt": worker.attempt,
                    },
                )
            )
    else:
        progress = plan.final_output.get("research_progress", {})
        research_events = progress.get("events", []) if isinstance(progress, dict) else []
    if isinstance(research_events, list):
        for index, research_event in enumerate(research_events):
            if not isinstance(research_event, dict):
                continue
            event_name = str(research_event.get("event") or "")
            event_key = f"{index}:{event_name}"
            if event_key in seen_research_events or event_name not in {
                "agent_task_research_wave_started",
                "agent_task_evidence_evaluated",
                "agent_task_sub_question_retrying",
            }:
                continue
            seen_research_events.add(event_key)
            events.append(
                _format_sse_event(
                    event_name,
                    {
                        "task_plan_id": plan.task_plan_id,
                        **{
                            key: value
                            for key, value in research_event.items()
                            if key != "event"
                        },
                    },
                )
            )
    document_progress = (
        {}
        if isinstance(plan, ResearchTaskPlan)
        else plan.final_output.get("document_progress", {})
    )
    document_events = (
        document_progress.get("events", [])
        if isinstance(document_progress, dict)
        else []
    )
    # 只把稳定协议中的文档事件暴露给 React；TaskPlan 内部临时字段不会自动变成 SSE。
    allowed_document_events = {
        "agent_task_document_supervised",
        "agent_task_document_subagent_started",
        "agent_task_document_subagent_completed",
        "agent_task_document_subagent_failed",
        "agent_task_document_draft_created",
        "agent_task_document_review_completed",
        "agent_task_document_revision_started",
        "agent_task_document_action_prepared",
    }
    if isinstance(document_events, list):
        for index, document_event in enumerate(document_events):
            if not isinstance(document_event, dict):
                continue
            event_name = str(document_event.get("event") or "")
            # 轮询会重复读取同一 JSON 快照，索引 + 事件名用于避免重复推送。
            event_key = f"document:{index}:{event_name}"
            if (
                event_key in seen_research_events
                or event_name not in allowed_document_events
            ):
                continue
            seen_research_events.add(event_key)
            events.append(
                _format_sse_event(
                    event_name,
                    {
                        "task_plan_id": plan.task_plan_id,
                        **{
                            key: value
                            for key, value in document_event.items()
                            if key != "event"
                        },
                    },
                )
            )
    for step in getattr(plan, "steps", []):
        if step.step_id in seen_steps or step.status.value not in {
            "completed",
            "failed",
        }:
            continue
        seen_steps.add(step.step_id)
        events.append(
            _format_sse_event(
                "agent_task_step_completed"
                if step.status.value == "completed"
                else "agent_task_step_failed",
                {
                    "task_plan_id": plan.task_plan_id,
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "status": step.status.value,
                    "output": step.output,
                    "error": step.error,
                },
            )
        )
    # question_decomposition 执行器将每个已完成子问题的字典追加到这里并保存快照。
    results = (
        [item.model_dump(mode="json") for item in plan.sub_question_results]
        if isinstance(plan, ResearchTaskPlan)
        else plan.final_output.get("sub_question_results", [])
    )

    # 检查当前子任务执行结果的json文件 格式是否正确
    if not isinstance(results, list):
        return events
    
    # 检查单个子任务的格式是否正确
    for result in results:
        if not isinstance(result, dict):
            continue
        sub_question_id = str(result.get("sub_question_id") or "")

        # seen_sub_questions 记录已经发送给前端的子任务id，防止前端收到重复完成事件
        if not sub_question_id or sub_question_id in seen_sub_questions:
            continue
        seen_sub_questions.add(sub_question_id)

        # 将执行结果原样带给前端：页面可据此显示问题、所选工具、答案或单题错误。
        if isinstance(plan, ResearchTaskPlan):
            validation = result.get("evidence_validation") or {}
            safe_result = {
                "task_plan_id": plan.task_plan_id,
                "sub_question_id": sub_question_id,
                "status": result.get("status"),
                "answer": result.get("answer"),
                "error_code": result.get("error_code"),
                "evidence_ids": result.get("evidence_ids", []),
            }
            events.append(
                _format_sse_event(
                    "sub_question_evidence_updated",
                    {
                        "task_plan_id": plan.task_plan_id,
                        "sub_question_id": sub_question_id,
                        "valid_evidence_refs": validation.get("valid_evidence_refs", []),
                        "invalid_evidence_refs": validation.get("invalid_evidence_refs", []),
                        "reason_codes": validation.get("reason_codes", []),
                    },
                )
            )
            events.append(_format_sse_event("sub_question_completed", safe_result))
        else:
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
    if isinstance(plan, ResearchTaskPlan):
        for requirement in plan.requirement_evidence_statuses:
            event_key = f"requirement:{requirement.requirement_id}:{requirement.status}"
            if event_key in seen_research_events:
                continue
            seen_research_events.add(event_key)
            event_name = {
                "satisfied": "requirement_satisfied",
                "partially_satisfied": "requirement_insufficient",
                "failed": "requirement_insufficient",
                "pending": "requirement_evidence_updated",
            }[requirement.status]
            events.append(
                _format_sse_event(
                    event_name,
                    {
                        "task_plan_id": plan.task_plan_id,
                        **requirement.model_dump(mode="json"),
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
