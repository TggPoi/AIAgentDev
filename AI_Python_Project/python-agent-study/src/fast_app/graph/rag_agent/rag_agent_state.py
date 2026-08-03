from typing import Literal, NotRequired, TypedDict

from fast_app.agents.runtime.agent_error_policy import AgentErrorDecision
from fast_app.agents.runtime.agent_loop_control import AgentLoopDecision
from fast_app.domain.agent_task_plan import AgentTaskPlan
from fast_app.domain.research_task_plan import AgentTaskPlanningTurn, ResearchTaskPlan
from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.nl2sql.models import Nl2SqlQueryResult
from fast_app.services.knowledge.knowledge_permission_policy import (
    merge_permission_scope_into_filter_dict,
)


RagAgentMode = Literal["vector", "keyword", "hybrid"]
RagAgentOperation = Literal["run", "stream", "stream_events"]
# 这里的 route 不是 HTTP route，而是 Agent graph 内部的“下一步动作”。
# 后续 conditional_edges 会读取这个字段决定走哪个节点。
RagAgentRoute = Literal[
    "direct_answer",
    "knowledge_retrieval",
    "structured_data_query",
    "direct_web",
    "execute_task_plan",
    "clarification_required",
    "final_error_answer",
    "fail_request",
]


class RagAgentState(TypedDict):
    # 用户请求输入：来自 RagChatRequest，是 Agent graph 的起点。
    # 这组字段保持和普通 RAG 请求一致，方便复用已有检索、rerank 和 response 转换逻辑。
    # 会话标识；仅在 pipeline 边界读取对话存储时使用，后续节点消费已冻结的上下文文本。
    session_id: str | None
    # 用户本次提交的原始问题；保留不变，供审计、trace 和对比 query rewrite 前后结果使用。
    original_query: str
    # 当前生效查询；query rewrite 成功后会更新它，检索和回答都应优先使用它。
    query: str
    # query rewrite 产生的新查询；未改写时为 None，不能替代 current query 的唯一事实来源。
    rewritten_query: str | None
    # 从 Redis 最近消息窗口冻结出的文本，只供 Planner 和最终回答理解多轮指代。
    history_window_text: str | None
    planning_history: list[AgentTaskPlanningTurn]
    # 记录本次为何改写或保留原 query，便于日志、trace 和问题排查。
    query_rewrite_reason: str | None
    # 从 PostgreSQL 读取的会话摘要；与 recent window 一起构成一次请求固定的对话快照。
    summary_text: str | None
    # 是否实际把摘要用于本次 query rewrite 或最终回答，供前端和 trace 说明上下文来源。
    summary_used: bool
    # 已读取会话摘要的版本号，用于定位本次请求使用的是哪一版持久化摘要。
    summary_version: int | None
    # 生成该摘要时覆盖的消息数量，帮助判断摘要覆盖范围。
    summary_source_message_count: int
    # 生成该摘要时覆盖的消息 ID，供调试时追溯摘要对应的对话事实。
    summary_source_message_ids: list[str]
    # 检索策略：向量、关键词或混合检索。
    mode: RagAgentMode
    # 最终希望返回给 RAG 链路的文档数量。
    top_k: int
    # rerank 前的候选数量；None 时由下游沿用默认策略。
    candidate_k: int | None
    # 检索结果最低分数阈值。
    min_score: float
    # 已合并当前用户知识库权限范围的检索过滤条件；节点不能绕过它重新构造权限事实。
    filters: dict[str, object]
    # 只表达本次请求是否允许公开网络兜底；不代表 Web 服务一定可用。
    allow_web_fallback: bool
    # 用户是否允许明确的 direct Web 任务；与证据不足后的 fallback 独立。
    allow_direct_web: bool
    # 客户端显式请求、API 已鉴权的 Dataset 绑定；只用于确定性报告分流。
    dataset_id: NotRequired[str | None]
    nl2sql_action: NotRequired[str | None]

    # Agent 执行上下文：用于区分 run / stream / stream_events。
    # 同一套 Agent 节点会被三种入口复用，但 trace step index 和流式行为会不同。
    # 当前入口类型；旧 state 缺失时节点按 run 兼容处理。
    operation: NotRequired[RagAgentOperation]
    # 图内下一步动作，由 conditional_edges 据此选择后续节点，不是 HTTP 路由。
    route: RagAgentRoute | None
    # 当前路由的可读解释，例如命中的规则、限制原因或澄清 code。
    route_reason: str | None
    # AgentTaskRouter 给出的结构化业务意图；只用于路由，不能作为授权或工具参数事实。
    route_intent: NotRequired[str | None]
    # 路由器对 route_intent 的置信度，供前端和可观测性展示。
    route_confidence: NotRequired[float | None]
    # 路由结果来源，例如规则或 LLM 路由器。
    route_source: NotRequired[str | None]
    # 本次路由决策实际使用的模型标识；规则路由时通常为空。
    route_model: NotRequired[str | None]
    # 路由节点耗时，单位毫秒。
    route_latency_ms: NotRequired[float | None]
    # 是否由确定性规则直接命中，便于区分规则与模型路由。
    route_rule_matched: NotRequired[bool]
    # 是否应停止执行并向用户追问，而非猜测任务意图。
    clarification_required: NotRequired[bool]
    # 需要澄清的稳定业务 code，前端可据此选择展示方式。
    clarification_code: NotRequired[str | None]
    # 返回给用户的具体澄清问题。
    clarification_question: NotRequired[str | None]
    # 图执行结束的归因，例如正常回答、等待确认或错误收口。
    final_reason: str | None

    # Agent 控制状态：记录步骤数、工具调用数、循环决策和错误决策。
    # 13-11 目前最多调用一次 knowledge_retrieval (所以目前 Agent 决策轮次 step_count=1)，但仍提前把 loop/error 状态放入 state，
    # 这样后续扩展多工具循环时不需要重新设计状态结构。
    # 已经过的 Agent 决策步骤数，用于循环上限判断，不等同于工具调用次数。
    step_count: int
    # 已执行或计划执行的工具调用数，用于限制 Agent 可消耗的外部工具预算。
    tool_call_count: int
    # 最近一次循环上限检查的结果，记录是否允许继续及其原因。
    loop_decision: AgentLoopDecision | None
    # 最近一次错误分类的结果，决定生成可恢复回答还是终止请求。
    error_decision: AgentErrorDecision | None

    # 工具与 RAG 中间产物：后续节点通过这些字段读取上游结果。
    # 当前或最近一次选择的工具名称，主要用于 trace、错误归因和节点间衔接。
    tool_name: str | None
    # 工具调用失败时保存的错误文本；成功时保持 None。
    tool_error: str | None
    # 检索并可能经过 rerank 的文档列表，是构建 RAG context 和 sources 的输入。
    docs: list[RetrievedDoc]
    # 由 query 与 docs 组装的提示词上下文，供最终 LLM 生成答案。
    context: RagContext | None
    # structured_data_query 节点返回的完整受控查询结果；其他路由为空。
    nl2sql_result: NotRequired[Nl2SqlQueryResult | None]
    # 当前图路径产生的最终用户可读答案；尚未生成时为 None。
    answer: str | None

    # 15-7 Agent tool 权限上下文。
    # 当前认证用户的服务端上下文；权限节点以它为输入，不能由对话历史替代。
    current_user: NotRequired[CurrentUserContext | None]
    # 复杂任务规划或文档 dry-run 产生的完整 TaskPlan，供后续执行或响应转换使用。
    agent_task_plan: NotRequired[AgentTaskPlan | ResearchTaskPlan | None]
    # TaskPlan 的稳定 ID；前端据此调用独立的查询、确认或恢复接口。
    agent_task_plan_id: NotRequired[str | None]
    # 当前计划是否必须先由用户通过确认 API 审核，再执行高风险动作。
    requires_confirmation: NotRequired[bool]


def build_rag_agent_initial_state(
    req: RagChatRequest,
    operation: RagAgentOperation,
    current_user: CurrentUserContext | None = None,
) -> RagAgentState:
    # LangGraph 要求每次请求都从一份新的 state 开始，避免跨请求共享 docs/context/answer。
    # 这里集中初始化所有字段，比在各个 node 里临时补默认值更容易排查状态流转。
    return {
        "session_id": req.session_id,
        "original_query": req.query,
        "query": req.query,
        "rewritten_query": None,
        "history_window_text": None,
        "planning_history": [],
        "query_rewrite_reason": None,
        "summary_text": None,
        "summary_used": False,
        "summary_version": None,
        "summary_source_message_count": 0,
        "summary_source_message_ids": [],
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "filters": merge_permission_scope_into_filter_dict(
            filters=req.filters.model_dump(),
            permission_scope=req._retrieval_permission_scope,
            knowledge_version=req._knowledge_version,
        ),
        "allow_web_fallback": req.allow_web_fallback,
        "allow_direct_web": req.allow_direct_web,
        "dataset_id": req.dataset_id,
        "nl2sql_action": req.nl2sql_action,
        "operation": operation,
        "route": None,
        "route_reason": None,
        "route_intent": None,
        "route_confidence": None,
        "route_source": None,
        "route_model": None,
        "route_latency_ms": None,
        "route_rule_matched": False,
        "clarification_required": False,
        "clarification_code": None,
        "clarification_question": None,
        "final_reason": None,
        "step_count": 0,
        "tool_call_count": 0,
        "loop_decision": None,
        "error_decision": None,
        "tool_name": None,
        "tool_error": None,
        "docs": [],
        "context": None,
        "nl2sql_result": None,
        "answer": None,
        "current_user": current_user,
        "agent_task_plan": None,
        "agent_task_plan_id": None,
        "requires_confirmation": False,
    }
