from collections.abc import Callable
from time import perf_counter

from fast_app.agents.agent_error_policy import (
    AgentErrorDecision,
    build_agent_error_answer,
    classify_agent_error,
)
from fast_app.agents.agent_loop_control import (
    AgentLoopLimits,
    AgentLoopSnapshot,
    build_agent_loop_limits_from_settings,
    should_continue_agent_loop,
)
from fast_app.agents.rag_agent_tools import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    retrieve_knowledge_docs,
)
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus, AgentToolStepStatus
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    build_rag_langchain_child_config,
    rag_langsmith_state_step_trace,
)
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievedDoc
from fast_app.graph.rag_agent_state import RagAgentRoute, RagAgentState
from fast_app.graph.rag_graph_nodes import (
    DIRECT_ANSWER_TEXT,
    should_retrieve_for_query,
)
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_task_planner import AgentTaskPlanner
from fast_app.services.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
)
from fast_app.services.rag_pipeline_service import build_rag_context, build_top_doc_ids
from fast_app.services.prompt_guard_service import PromptGuardService


logger = get_logger(__name__)


def get_rag_agent_operation(state: RagAgentState) -> str:
    # operation 用于区分同一个节点当前服务于 run / stream / stream_events 哪个入口。
    # 如果旧 state 或测试 state 没传 operation，就默认按 run 处理。
    return state.get("operation", "run")


def get_rag_agent_step_index(operation: str, step_name: str) -> int:
    # stream_events 多一个 emit_sources 步骤，所以 step_index 和 run/stream 不完全相同。
    # LangSmith trace 中保留稳定 index，后续排查时可以按顺序复盘 Agent 链路。
    if operation == "stream_events":
        indexes = {
            "query_rewrite": 0,
            "decide_next_action": 1,
            "check_loop_limits": 2,
            "direct_answer": 3,
            "execute_task_plan": 3,
            "call_knowledge_retrieval": 3,
            "rerank": 4,
            "emit_sources": 5,
            "build_context": 6,
            "stream_generate": 7,
            "generate_answer": 7,
            "final_error_answer": 3,
            "fail_request": 3,
        }
        return indexes[step_name]

    indexes = {
        "query_rewrite": 0,
        "decide_next_action": 1,
        "check_loop_limits": 2,
        "direct_answer": 3,
        "execute_task_plan": 3,
        "call_knowledge_retrieval": 3,
        "rerank": 4,
        "build_context": 5,
        "stream_generate": 6,
        "generate_answer": 6,
        "final_error_answer": 3,
        "fail_request": 3,
    }
    return indexes[step_name]


def build_rag_agent_step_inputs(
    state: RagAgentState,
    **extra: object,
) -> dict[str, object]:
    # 所有节点统一用这个 helper 构造 trace inputs，避免每个节点各自拼字段。
    # extra 用于追加当前节点独有的信息，例如 tool_name、doc_count、error_kind。
    return {
        "session_id": state.get("session_id"),
        "original_query": state.get("original_query"),
        "query": state["query"],
        "rewritten_query": state.get("rewritten_query"),
        "query_rewrite_reason": state.get("query_rewrite_reason"),
        "summary_used": state.get("summary_used", False),
        "summary_version": state.get("summary_version"),
        "summary_source_message_count": state.get("summary_source_message_count", 0),
        "mode": state["mode"],
        "top_k": state["top_k"],
        "candidate_k": state.get("candidate_k"),
        "min_score": state["min_score"],
        "filters": state.get("filters", {}),
        "step_count": state.get("step_count", 0),
        "tool_call_count": state.get("tool_call_count", 0),
        **extra,
    }


def rag_agent_langsmith_step_trace(
    settings: Settings,
    state: RagAgentState,
    step_name: str,
    run_type: str,
    inputs: dict[str, object],
):
    # Agent 节点内部拿到的是 RagAgentState，不是 RagChatRequest。
    # 所以这里使用 from_state 版本的 metadata builder，把 state 转成 LangSmith 可读的 step 元数据。
    operation = get_rag_agent_operation(state)
    return rag_langsmith_state_step_trace(
        settings,
        state,
        "rag_agent",
        operation,
        step_name,
        get_rag_agent_step_index(operation, step_name),
        run_type,
        inputs,
    )


def build_rag_agent_retrieval_filters(state: RagAgentState) -> RetrievalFilters:
    # HTTP schema 的 filters 在 initial_state 中已经 model_dump 成 dict。
    # 这里再转回内部 RetrievalFilters，供 knowledge_retrieval helper 使用。
    raw_filters = state.get("filters", {})
    filters = raw_filters if isinstance(raw_filters, dict) else None
    return build_retrieval_filters_from_mapping(filters)


def build_loop_limit_error_decision(reason: str) -> AgentErrorDecision:
    # loop limit 不是底层异常，而是 Agent 控制层主动停止。
    # 因此这里手动构造 AgentErrorDecision，让后续错误回答节点可以统一处理。
    return AgentErrorDecision(
        kind="loop_limit_error",
        action="final_answer",
        error_code="AGENT_LOOP_LIMIT_REACHED",
        error_category="agent_error",
        public_message="本次 Agent 执行已达到步骤上限，已停止继续调用工具。",
        error_node="check_loop_limits",
        is_recoverable=True,
    )


def route_after_loop_check(state: RagAgentState) -> RagAgentRoute:
    # check_loop_limits 之后的条件边：
    # - 有 error_decision：说明已经触发 loop/error 控制，进入错误回答。
    # - route 是 direct_answer：不调用工具。
    # - route 是 knowledge_retrieval：进入知识库工具。
    if state.get("error_decision") is not None:
        return "final_error_answer"

    route = state.get("route")
    if route in (
        "direct_answer",
        "knowledge_retrieval",
        "execute_task_plan",
    ):
        return route

    return "knowledge_retrieval"


def route_after_tool_call(state: RagAgentState) -> RagAgentRoute:
    # 工具节点不会直接抛出所有错误，而是先写入 error_decision。
    # 这里根据 error action 决定是给用户一个可解释最终回答，还是让请求失败。
    decision = state.get("error_decision")
    if decision is not None:
        if decision.action == "final_answer":
            return "final_error_answer"
        return "fail_request"

    return "knowledge_retrieval"


def create_next_action_decision_node(
    settings: Settings,
    task_planner: AgentTaskPlanner | None = None,
) -> Callable[[RagAgentState], dict[str, object]]:
    # decide_next_action 节点是 Agent 的“判断”步骤：先决定是否需要知识库，或是否需要调用工具。
    async def decide_next_action_node(state: RagAgentState) -> dict[str, object]:
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="decide_next_action",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(state),
        ) as trace_run:
            task_plan = None
            if task_planner is not None:
                # 开始判断拆解多步骤任务
                current_user = state.get("current_user")
                operation = get_rag_agent_operation(state)

                def build_planner_config(child_name: str):
                    return build_rag_langchain_child_config(
                        settings=settings,
                        state=state,
                        pipeline_provider="rag_agent",
                        operation=operation,
                        step_name="decide_next_action",
                        step_index=get_rag_agent_step_index(
                            operation,
                            "decide_next_action",
                        ),
                        child_name=child_name,
                        run_name=(
                            f"rag_agent_pipeline.{operation}."
                            f"decide_next_action.{child_name}"
                        ),
                    )

                task_plan = await task_planner.plan(
                    query=state["query"],
                    history=[],
                    user_id=current_user.user_id if current_user is not None else None,
                    langchain_config_factory=build_planner_config,
                )

            if task_plan is not None:
                route: RagAgentRoute = "execute_task_plan"
                step_count = state["step_count"] + 1
                result = {
                    "route": route,
                    "route_reason": "agent_task_plan_detected",
                    "step_count": step_count,
                    "agent_task_plan": task_plan,
                    "agent_task_plan_id": task_plan.task_plan_id,
                }
                logger.info(
                    "rag_agent_decision %s",
                    format_log_fields(
                        event="rag_agent.decide_next_action.task_plan",
                        pipeline_provider="rag_agent",
                        query=state["query"],
                        route=route,
                        task_plan_id=task_plan.task_plan_id,
                        task_kind=task_plan.task_kind,
                        step_count=step_count,
                    ),
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "route": route,
                            "task_plan_id": task_plan.task_plan_id,
                            "task_kind": task_plan.task_kind,
                        }
                    )
                return result

            need_retrieval, route_reason = should_retrieve_for_query(state["query"])
            # 当前最小 Agent 只有两个动作：直接回答，或调用 knowledge_retrieval。
            # 后续多工具 Agent 可以在这里扩展 calculator / web_search / MCP tool 的选择。
            route = (
                "knowledge_retrieval" if need_retrieval else "direct_answer"
            )
            step_count = state["step_count"] + 1

            result = {
                "route": route,
                "route_reason": route_reason,
                "step_count": step_count,
            }

            logger.info(
                "rag_agent_decision %s",
                format_log_fields(
                    event="rag_agent.decide_next_action.finish",
                    pipeline_provider="rag_agent",
                    query=state["query"],
                    route=route,
                    route_reason=route_reason,
                    step_count=step_count,
                ),
            )
            if trace_run is not None:
                trace_run.add_outputs(result)

            return result

    return decide_next_action_node


def create_check_loop_limits_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, object]]:
    async def check_loop_limits_node(state: RagAgentState) -> dict[str, object]:
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="check_loop_limits",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(state, route=state.get("route")),
        ) as trace_run:
            limits = build_agent_loop_limits_from_settings(settings)
            if state.get("route") == "direct_answer":
                # direct_answer 不会调用工具，不应该因为 AGENT_MAX_TOOL_CALLS=0 被误拦截。
                # 这里只对直接回答路径放宽工具调用上限，检索路径仍严格遵守配置。
                limits = AgentLoopLimits(
                    max_steps=limits.max_steps,
                    max_tool_calls=max(limits.max_tool_calls, 1),
                )
            snapshot = AgentLoopSnapshot(
                # AgentLoopSnapshot 是 loop_control 层的纯输入对象。
                # 当前 graph state 先转换成 snapshot，再交给 should_continue_agent_loop 判断。
                step_count=state["step_count"],
                tool_call_count=state["tool_call_count"],
                final_answer_ready=state.get("answer") is not None,
                has_tool_error=state.get("tool_error") is not None,
                has_model_error=False,
            )
            decision = should_continue_agent_loop(snapshot, limits)

            result: dict[str, object] = {
                "loop_decision": decision,
            }
            if not decision.should_continue:
                result["error_decision"] = build_loop_limit_error_decision(
                    decision.reason
                )
                result["final_reason"] = decision.reason

            logger.info(
                "rag_agent_loop %s",
                format_log_fields(
                    event="rag_agent.check_loop_limits.finish",
                    pipeline_provider="rag_agent",
                    route=state.get("route"),
                    should_continue=decision.should_continue,
                    reason=decision.reason,
                    step_count=state["step_count"],
                    tool_call_count=state["tool_call_count"],
                ),
            )
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "should_continue": decision.should_continue,
                        "reason": decision.reason,
                    }
                )

            return result

    return check_loop_limits_node


def create_rag_agent_direct_answer_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, str]]:
    # 直接回答节点用于问候、能力说明等不需要知识库的 query。
    # 它不调用 LLM，避免把简单系统能力说明变成不稳定的模型输出。
    async def direct_answer_node(state: RagAgentState) -> dict[str, str]:
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="direct_answer",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                route=state.get("route"),
                route_reason=state.get("route_reason"),
            ),
        ) as trace_run:
            result = {
                "answer": DIRECT_ANSWER_TEXT,
                "final_reason": "direct_answer",
            }

            logger.info(
                "rag_agent_direct_answer %s",
                format_log_fields(
                    event="rag_agent.direct_answer.finish",
                    pipeline_provider="rag_agent",
                    query=state["query"],
                    answer_length=len(DIRECT_ANSWER_TEXT),
                    route_reason=state.get("route_reason"),
                ),
            )
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "answer_length": len(DIRECT_ANSWER_TEXT),
                        "source_count": 0,
                    }
                )

            return result

    return direct_answer_node


def create_call_knowledge_retrieval_node(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
) -> Callable[[RagAgentState], dict[str, object]]:
    # 这是 13-11 的核心工具节点。
    # 它不通过 LangChain Tool 字符串摘要，而是直接复用底层 helper 拿结构化 RetrievedDoc。
    async def call_knowledge_retrieval_node(
        state: RagAgentState,
    ) -> dict[str, object]:
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="call_knowledge_retrieval",
            run_type="tool",
            inputs=build_rag_agent_step_inputs(
                state,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
            ),
        ) as trace_run:
            try:
                # pipeline_provider 写成 rag_agent，方便日志和 trace 区分来自哪条执行路线。
                docs = await retrieve_knowledge_docs(
                    settings=settings,
                    vector_retriever=vector_retriever,
                    keyword_retriever=keyword_retriever,
                    query=state["query"],
                    mode=state["mode"],
                    top_k=state["top_k"],
                    candidate_k=state.get("candidate_k"),
                    min_score=state["min_score"],
                    filters=build_rag_agent_retrieval_filters(state),
                    pipeline_provider="rag_agent",
                )
            except Exception as exc:
                # 工具失败先分类成 AgentErrorDecision，而不是马上让整个 graph 中断。
                # NoSearchResultError 会被转成 final_answer，外部服务失败通常会 fail_request。
                decision = classify_agent_error(
                    exc,
                    error_node="call_knowledge_retrieval",
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                )
                result = {
                    "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    "tool_call_count": state["tool_call_count"] + 1,
                    "tool_error": type(exc).__name__,
                    "error_decision": decision,
                    "final_reason": decision.kind,
                }
                logger.warning(
                    "rag_agent_tool %s",
                    format_log_fields(
                        event="rag_agent.call_knowledge_retrieval.failed",
                        pipeline_provider="rag_agent",
                        tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                        error_type=type(exc).__name__,
                        error_kind=decision.kind,
                        error_action=decision.action,
                    ),
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                            "tool_error": type(exc).__name__,
                            "error_kind": decision.kind,
                            "error_action": decision.action,
                        }
                    )
                return result

            result = {
                # 工具成功后把 docs 写回 state，后续 rerank/build_context/generate 节点继续消费。
                "docs": docs,
                "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                "tool_call_count": state["tool_call_count"] + 1,
                "tool_error": None,
                "error_decision": None,
            }
            logger.info(
                "rag_agent_tool %s",
                format_log_fields(
                    event="rag_agent.call_knowledge_retrieval.finish",
                    pipeline_provider="rag_agent",
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    result_count=len(docs),
                    top_doc_ids=build_top_doc_ids(docs),
                ),
            )
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "tool_name": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                        "tool_result_count": len(docs),
                        "top_doc_ids": build_top_doc_ids(docs),
                    }
                )

            return result

    return call_knowledge_retrieval_node


def create_execute_task_plan_node(
    settings: Settings,
    task_executor: AgentTaskExecutor,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造 AgentTaskPlan 执行节点。"""

    async def execute_task_plan_node(state: RagAgentState) -> dict[str, object]:
        plan = state.get("agent_task_plan")
        user = state.get("current_user")
        if plan is None or user is None:
            return {
                "answer": "缺少 Agent task plan 或当前用户上下文，无法执行多步骤任务。",
                "final_reason": "agent_task_plan_failed",
            }

        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="execute_task_plan",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                task_plan_id=plan.task_plan_id,
                task_kind=plan.task_kind,
            ),
        ) as trace_run:
            if plan.task_kind == "question_decomposition":
                plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
                plan.final_output = {
                    "status": plan.status.value,
                    "confirm_endpoint": f"/agent/task-plans/{plan.task_plan_id}/confirm",
                }
                task_executor.save_plan(plan)
                answer = build_task_plan_answer(plan)
                result = {
                    "agent_task_plan": plan,
                    "agent_task_plan_id": plan.task_plan_id,
                    "answer": answer,
                    "final_reason": "agent_task_waiting_confirmation",
                    "requires_confirmation": True,
                }
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "task_plan_id": plan.task_plan_id,
                            "status": plan.status.value,
                            "task_kind": plan.task_kind,
                            "requires_confirmation": True,
                        }
                    )
                return result

            operation = get_rag_agent_operation(state)

            def build_executor_config(child_name: str):
                return build_rag_langchain_child_config(
                    settings=settings,
                    state=state,
                    pipeline_provider="rag_agent",
                    operation=operation,
                    step_name="execute_task_plan",
                    step_index=get_rag_agent_step_index(operation, "execute_task_plan"),
                    child_name=f"task_executor.{child_name}",
                    run_name=(
                        f"rag_agent_pipeline.{operation}."
                        f"execute_task_plan.task_executor.{child_name}"
                    ),
                )

            executed_plan = await task_executor.execute(
                plan=plan,
                user=user,
                mode=state["mode"],
                top_k=state["top_k"],
                candidate_k=state.get("candidate_k"),
                min_score=state["min_score"],
                filters=build_rag_agent_retrieval_filters(state),
                langchain_config_factory=build_executor_config,
            )
            answer = build_task_plan_answer(executed_plan)
            result = {
                "agent_task_plan": executed_plan,
                "agent_task_plan_id": executed_plan.task_plan_id,
                "answer": answer,
                "final_reason": "agent_task_waiting_confirmation"
                if executed_plan.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
                else f"agent_task_{executed_plan.status.value}",
                "requires_confirmation": executed_plan.status
                == AgentTaskPlanStatus.WAITING_CONFIRMATION,
            }

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "task_plan_id": executed_plan.task_plan_id,
                        "status": executed_plan.status.value,
                        "requires_confirmation": result["requires_confirmation"],
                    }
                )
            return result

    return execute_task_plan_node


def build_task_plan_answer(plan) -> str:
    # 这里的文本是 chat 回答；结构化字段仍通过 response.agent_task_plan
    # 和 stream_events 的 agent_task_plan_created 给前端消费。
    lines = [
        "已生成 Agent 多步骤任务计划。",
        "",
        f"- task_plan_id: {plan.task_plan_id}",
        f"- task_kind: {plan.task_kind}",
        f"- status: {plan.status.value}",
        f"- task_type: {plan.task_type}",
        f"- objective: {plan.objective}",
        f"- source_query: {plan.source_query}",
    ]
    if plan.target_path:
        lines.append(f"- target_path: {plan.target_path}")
    if plan.sub_questions:
        lines.append("")
        lines.append("问题拆解：")
        for item in plan.sub_questions:
            depends_on = f" depends_on={item.depends_on}" if item.depends_on else ""
            lines.append(f"- {item.sub_question_id}: {item.question}{depends_on}")
        lines.append("")
        lines.append(f"最终整合策略：{plan.final_synthesis_instruction}")
    if plan.status == AgentTaskPlanStatus.WAITING_CONFIRMATION:
        lines.append(f"- confirm_endpoint: /agent/task-plans/{plan.task_plan_id}/confirm")
        lines.append("")
        if plan.task_kind == "question_decomposition":
            lines.append("TaskPlan 已等待人工确认，尚未开始执行子问题。")
        elif plan.task_kind == "knowledge_document_management":
            lines.append(
                f"已解析 {len(plan.steps)} 个文档动作，尚未修改源文件、ES 或 Milvus。"
            )
        else:
            lines.append("文档创建步骤已停在 TaskPlan 人工确认，尚未执行真实写入。")
        lines.append(
            f"请通过 `POST /agent/task-plans/{plan.task_plan_id}/confirm` 完成人工确认。"
        )
    final_answer = plan.final_output.get("final_answer")
    if isinstance(final_answer, str) and final_answer.strip():
        lines.extend(["", "最终答案：", final_answer.strip()])
    return "\n".join(lines)


def create_agent_rerank_node(
    settings: Settings,
    reranker: BaseReranker,
    rerank_top_k: int,
) -> Callable[[RagAgentState], dict[str, object]]:
    # rerank 是质量增强层，不是唯一事实来源。
    # 所以 rerank 的 ExternalServiceError 会降级为 fallback docs，而不是直接中断 Agent。
    async def rerank_node(state: RagAgentState) -> dict[str, object]:
        docs = state["docs"]
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="rerank",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                input_doc_count=len(docs),
                top_doc_ids=build_top_doc_ids(docs),
            ),
        ) as trace_run:
            if not docs:
                return {"docs": []}

            start_time = perf_counter()
            top_k = min(rerank_top_k, len(docs))
            try:
                reranked_docs = await reranker.rerank(
                    query=state["query"],
                    docs=docs,
                    top_k=top_k,
                )
                latency_ms = (perf_counter() - start_time) * 1000
                logger.info(
                    "rag_agent_rerank %s",
                    format_log_fields(
                        event="rag_agent.rerank.finish",
                        pipeline_provider="rag_agent",
                        candidate_count=len(docs),
                        result_count=len(reranked_docs),
                        top_k=top_k,
                        latency_ms=round(latency_ms, 2),
                        fallback=False,
                        top_doc_ids=build_top_doc_ids(reranked_docs),
                    ),
                )
                log_slow_operation(
                    logger=logger,
                    event="rag_agent.rerank.slow",
                    latency_ms=latency_ms,
                    threshold_ms=settings.slow_rerank_threshold_ms,
                    slow_component="rerank",
                    pipeline_provider="rag_agent",
                    candidate_count=len(docs),
                    result_count=len(reranked_docs),
                    top_k=top_k,
                    fallback=False,
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": len(reranked_docs),
                            "top_doc_ids": build_top_doc_ids(reranked_docs),
                            "fallback": False,
                        }
                    )
                return {"docs": reranked_docs}

            except ExternalServiceError as exc:
                fallback_docs = docs[:rerank_top_k]
                # classify_agent_error(error_node="rerank") 会把错误标记成可恢复的 rerank_error。
                decision = classify_agent_error(exc, error_node="rerank")
                latency_ms = (perf_counter() - start_time) * 1000
                logger.warning(
                    "rag_agent_rerank %s",
                    format_log_fields(
                        event="rag_agent.rerank.fallback",
                        pipeline_provider="rag_agent",
                        candidate_count=len(docs),
                        result_count=len(fallback_docs),
                        top_k=top_k,
                        latency_ms=round(latency_ms, 2),
                        fallback=True,
                        error_kind=decision.kind,
                        top_doc_ids=build_top_doc_ids(fallback_docs),
                    ),
                )
                log_slow_operation(
                    logger=logger,
                    event="rag_agent.rerank.slow",
                    latency_ms=latency_ms,
                    threshold_ms=settings.slow_rerank_threshold_ms,
                    slow_component="rerank",
                    pipeline_provider="rag_agent",
                    candidate_count=len(docs),
                    result_count=len(fallback_docs),
                    top_k=top_k,
                    fallback=True,
                    error_type=type(exc).__name__,
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "output_doc_count": len(fallback_docs),
                            "top_doc_ids": build_top_doc_ids(fallback_docs),
                            "fallback": True,
                            "error_kind": decision.kind,
                            "error_action": decision.action,
                        }
                    )
                return {
                    "docs": fallback_docs,
                    "error_decision": decision,
                    "final_reason": decision.kind,
                }

    return rerank_node


def create_agent_build_context_node(
    settings: Settings,
    prompt_guard: PromptGuardService | None = None,
) -> Callable[[RagAgentState], dict[str, object]]:
    # build_context 是 RAG 和 LLM 之间的适配层：
    # 输入是结构化 docs，输出是 LLM client 能消费的 RagContext。
    async def build_context_node(state: RagAgentState) -> dict[str, object]:
        docs = state["docs"]
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="build_context",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                doc_count=len(docs),
                top_doc_ids=build_top_doc_ids(docs),
            ),
        ) as trace_run:
            if prompt_guard is not None:
                docs = await prompt_guard.filter_retrieved_docs(
                    docs,
                    source="rag_agent.build_context",
                )

            context = build_rag_context(state["query"], docs)
            logger.info(
                "rag_agent_context %s",
                format_log_fields(
                    event="rag_agent.build_context.finish",
                    pipeline_provider="rag_agent",
                    doc_count=len(docs),
                    context_length=len(context.context_text),
                ),
            )
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "context_doc_count": len(context.docs),
                        "context_length": len(context.context_text),
                    }
                )
            return {
                "docs": docs,
                "context": context,
            }

    return build_context_node


def create_agent_generate_answer_node(
    settings: Settings,
    llm_client: BaseLLMClient,
    prompt_guard: PromptGuardService | None = None,
) -> Callable[[RagAgentState], dict[str, str]]:
    # 非流式 run 使用这个节点一次性生成完整 answer。
    # stream / stream_events 为了保持 token-only，会在 service 层手写到 llm_client.stream。
    async def generate_answer_node(state: RagAgentState) -> dict[str, str]:
        context = state["context"]
        if context is None:
            raise ExternalServiceError("RAG Agent 上下文为空，无法生成回答")

        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="generate_answer",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                context_doc_count=len(context.docs),
                context_length=len(context.context_text),
            ),
        ) as trace_run:
            try:
                answer = await llm_client.generate(
                    query=state["query"],
                    context=context,
                    langchain_config=build_rag_langchain_child_config(
                        settings=settings,
                        state=state,
                        pipeline_provider="rag_agent",
                        operation=get_rag_agent_operation(state),
                        step_name="generate_answer",
                        step_index=get_rag_agent_step_index(
                            get_rag_agent_operation(state),
                            "generate_answer",
                        ),
                        child_name="generate_answer.llm",
                        run_name=(
                            f"rag_agent_pipeline.{get_rag_agent_operation(state)}."
                            "generate_answer.llm"
                        ),
                    ),
                )
                if prompt_guard is not None:
                    answer = await prompt_guard.ensure_output_allowed(
                        answer,
                        source="rag_agent.generate_answer",
                    )
            except Exception as exc:
                # 生成失败通常不能构造可靠答案，所以这里只记录分类结果，再交给外层错误链路处理。
                decision = classify_agent_error(exc, error_node="generate_answer")
                logger.exception(
                    "rag_agent_generate %s",
                    format_log_fields(
                        event="rag_agent.generate_answer.failed",
                        pipeline_provider="rag_agent",
                        error_type=type(exc).__name__,
                        error_kind=decision.kind,
                        error_action=decision.action,
                    ),
                )
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "error_type": type(exc).__name__,
                            "error_kind": decision.kind,
                            "error_action": decision.action,
                        }
                    )
                raise

            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "answer_length": len(answer),
                        "source_count": len(context.docs),
                    }
                )
            logger.info(
                "rag_agent_generate %s",
                format_log_fields(
                    event="rag_agent.generate_answer.finish",
                    pipeline_provider="rag_agent",
                    answer_length=len(answer),
                    source_count=len(context.docs),
                ),
            )
            return {
                "answer": answer,
                "final_reason": "generated_answer",
            }

    return generate_answer_node


def create_agent_error_answer_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, str]]:
    # 可恢复或可解释的错误会进入这里，例如知识库无结果、loop 达上限。
    # 这个节点把错误决策转换成面向用户的最终回答。
    async def error_answer_node(state: RagAgentState) -> dict[str, str]:
        decision = state.get("error_decision")
        if decision is None:
            raise ExternalServiceError("RAG Agent 错误分支缺少错误决策")

        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="final_error_answer",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                error_kind=decision.kind,
                error_action=decision.action,
            ),
        ) as trace_run:
            answer = build_agent_error_answer(decision)
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "answer_length": len(answer),
                        "error_kind": decision.kind,
                        "error_action": decision.action,
                    }
                )
            return {
                "answer": answer,
                "final_reason": decision.kind,
            }

    return error_answer_node


def create_agent_fail_request_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, object]]:
    # 不可恢复错误进入这里，并继续抛 AppServiceError 体系内的异常。
    # 这样 HTTP / SSE 层仍然复用现有全局错误响应和 error event 包装。
    async def fail_request_node(state: RagAgentState) -> dict[str, object]:
        decision = state.get("error_decision")
        if decision is None:
            raise ExternalServiceError("RAG Agent 请求失败")

        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="fail_request",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                error_kind=decision.kind,
                error_action=decision.action,
            ),
        ) as trace_run:
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "error_kind": decision.kind,
                        "error_action": decision.action,
                        "error_code": decision.error_code,
                    }
                )
        raise ExternalServiceError(decision.public_message)

    return fail_request_node
