from collections.abc import Callable
from html import unescape
import re
from time import perf_counter
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from fast_app.agents.runtime.agent_error_policy import (
    AgentErrorDecision,
    build_agent_error_answer,
    classify_agent_error,
)
from fast_app.agents.runtime.agent_loop_control import (
    AgentLoopLimits,
    AgentLoopSnapshot,
    build_agent_loop_limits_from_settings,
    should_continue_agent_loop,
)
from fast_app.agents.tools.rag_agent_tools import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    retrieve_knowledge_docs,
)
from fast_app.agents.tools.web_search_tools import search_web_with_bocha
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlanStatus,
    AgentToolStepStatus,
)
from fast_app.domain.research_task_plan import (
    ResearchTaskPlan,
    ResearchTaskPolicy,
    ResolvedPlanningRequest,
)
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
from fast_app.graph.rag_agent.rag_agent_state import RagAgentRoute, RagAgentState
from fast_app.graph.rag.rag_graph_nodes import (
    DIRECT_ANSWER_TEXT,
    should_retrieve_for_query,
)
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.agent_task_capability_service import (
    AgentTaskCapabilityService,
)
from fast_app.services.agent_tasks.agent_task_router import (
    AgentRouteDecision,
    AgentTaskRouteResult,
    AgentTaskRouter,
)
from fast_app.services.knowledge.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
)
from fast_app.services.rag.rag_pipeline_service import build_top_doc_ids
from fast_app.services.rag.direct_web_search_planner import (
    DirectWebSearchPlan,
    DirectWebSearchPlanner,
)
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.rag.rag_context_assembler import build_context_observation
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.nl2sql.service import Nl2SqlService


logger = get_logger(__name__)


def _matches_direct_web_plan(result, *, plan: DirectWebSearchPlan) -> bool:
    """确定性检查候选网页是否满足规划器声明的域名、版本和主题契约。"""

    parsed = urlparse(result.url)
    hostname = (parsed.hostname or "").lower()
    site = (plan.site or "").lower()
    if site and hostname != site and not hostname.endswith(f".{site}"):
        return False
    lowered_url = result.url.lower()
    if any(item.lower() not in lowered_url for item in plan.required_url_fragments):
        return False
    searchable = " ".join(
        (result.title, result.snippet, result.summary)
    ).lower()
    return all(item.lower() in searchable for item in plan.required_content_terms)


def _official_page_text(raw_html: str) -> str:
    """把受信官方页面转换成供现有 RAG 上下文使用的纯文本。"""

    for tag in ("article", "main", "body"):
        matched = re.search(
            rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>",
            raw_html,
        )
        if matched:
            raw_html = matched.group(1)
            break
    without_scripts = re.sub(
        r"(?is)<(?:script|style|nav|header|footer)\b[^>]*>.*?</(?:script|style|nav|header|footer)>",
        " ",
        raw_html,
    )
    return " ".join(unescape(re.sub(r"(?s)<[^>]+>", " ", without_scripts)).split())


async def _official_sitemap_candidates(
    http_client: httpx.AsyncClient,
    *,
    plan: DirectWebSearchPlan,
) -> list[dict[str, str]]:
    """从官方网站标准 sitemap 提取与当前问题最相关的真实 URL。"""

    if not plan.site:
        return []
    try:
        response = await http_client.get(
            f"https://{plan.site}/sitemap.xml",
            timeout=10.0,
        )
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            return []
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return []

    needles = {
        token.lower()
        for value in (plan.query, *plan.required_content_terms)
        for token in re.findall(r"[A-Za-z0-9]+", value)
        if len(token) >= 2
    }
    ranked: list[tuple[int, str]] = []
    for element in root.iter():
        if not element.tag.endswith("loc") or not element.text:
            continue
        url = element.text.strip()
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or (
            hostname != plan.site.lower()
            and not hostname.endswith(f".{plan.site.lower()}")
        ):
            continue
        compact_url = re.sub(r"[^a-z0-9]", "", url.lower())
        score = sum(token in compact_url for token in needles)
        if score:
            ranked.append((score, url))
    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [
        {"title": url, "url": url, "summary": "official sitemap candidate"}
        for _, url in ranked[:20]
    ]


def create_call_direct_web_node(
    settings: Settings,
    search_planner: DirectWebSearchPlanner | None = None,
) -> Callable[[RagAgentState], dict[str, object]]:
    """执行 Router 已确认的单步骤公开网络检索，不创建 TaskPlan。"""
    # 先根据用户query 由 llm 规划当前query需要查询哪些站点，不能直接交给bocha搜索引擎，会导致搜索结果很烂
    planner = search_planner or DirectWebSearchPlanner(settings)

    async def call_direct_web_node(state: RagAgentState) -> dict[str, object]:
        operation = get_rag_agent_operation(state)
        # 先根据用户query得出候选url，如果有多个候选，由下面的 planner.select_candidate_url 再进行一次筛选
        plan = await planner.plan(
            question=state["query"],
            count=min(max(state["top_k"], 2), 10),
            langchain_config=build_rag_langchain_child_config(
                settings=settings,
                state=state,
                pipeline_provider="rag_agent",
                operation=operation,
                step_name="call_direct_web",
                step_index=get_rag_agent_step_index(operation, "call_direct_web"),
                child_name="search_plan",
                run_name=f"rag_agent_pipeline.{operation}.call_direct_web.search_plan",
            ),
        )
        direct_doc: RetrievedDoc | None = None
        async with httpx.AsyncClient(follow_redirects=True) as http_client:
            results = []
            raw_results = await search_web_with_bocha(
                settings=settings,
                http_client=http_client,
                query=plan.query,
                count=plan.count,
                site=plan.site,
            )
            # TODO：这里存在设计问题！把所有带站点限制的搜索都当成“官方资料搜索”，更合理的设计应该是 if plan.source_mode == "official": 增加明确的来源模式
            if plan.site:
                strict_results = [
                    item
                    for item in raw_results
                    if _matches_direct_web_plan(item, plan=plan)
                ]
                candidate_payload = [
                    {
                        "title": item.title,
                        "url": item.url,
                        "summary": item.summary or item.snippet,
                    }
                    for item in raw_results
                    if _matches_direct_web_plan(
                        item,
                        plan=plan.model_copy(
                            update={
                                "required_url_fragments": [],
                                "required_content_terms": [],
                            }
                        ),
                    )
                ]
                if not strict_results:
                    candidate_payload.extend(
                        await _official_sitemap_candidates(http_client, plan=plan)
                    )
                if plan.exact_url:
                    candidate_payload.append(
                        {
                            "title": plan.exact_url,
                            "url": plan.exact_url,
                            "summary": "planner candidate",
                        }
                    )
                unique_candidates = list(
                    {item["url"]: item for item in candidate_payload}.values()
                )
                selected_url = await planner.select_candidate_url(
                    question=state["query"],
                    plan=plan,
                    candidates=unique_candidates,
                    langchain_config=build_rag_langchain_child_config(
                        settings=settings,
                        state=state,
                        pipeline_provider="rag_agent",
                        operation=operation,
                        step_name="call_direct_web",
                        step_index=get_rag_agent_step_index(
                            operation, "call_direct_web"
                        ),
                        child_name="candidate_selection",
                        run_name=(
                            f"rag_agent_pipeline.{operation}."
                            "call_direct_web.candidate_selection"
                        ),
                    ),
                )
                if selected_url:
                    try:
                        response = await http_client.get(selected_url, timeout=10.0)
                        response.raise_for_status()
                        direct_doc = RetrievedDoc(
                            id="web:1",
                            content=(
                                f"{selected_url}\n{_official_page_text(response.text)}"
                            ),
                            score=1.0,
                            source="web_search",
                            title=selected_url,
                            metadata={"url": selected_url, "site_name": plan.site},
                            retrieval_sources=["web_search"],
                        )
                    except httpx.HTTPError:
                        direct_doc = None
            if direct_doc is None:
                results = [
                    result
                    for result in raw_results
                    if _matches_direct_web_plan(result, plan=plan)
                ]
        docs = [
            RetrievedDoc(
                id=f"web:{index}",
                content="\n".join(
                    item
                    for item in (result.title, result.snippet, result.summary, result.url)
                    if item
                ),
                score=1.0,
                source="web_search",
                title=result.title,
                metadata={"url": result.url, "site_name": result.site_name},
                retrieval_sources=["web_search"],
            )
            for index, result in enumerate(results, start=1)
        ]
        if direct_doc is not None:
            docs = [direct_doc]
        if not docs:
            raise ExternalServiceError("Web Search 未返回可用结果")
        return {
            "docs": docs,
            "tool_name": "web_search",
            "tool_error": None,
            "tool_call_count": state["tool_call_count"] + 1,
        }

    return call_direct_web_node


def get_rag_agent_operation(state: RagAgentState) -> str:
    """读取当前入口类型；旧状态缺失时按非流式 run 处理。"""
    # operation 用于区分同一个节点当前服务于 run / stream / stream_events 哪个入口。
    # 如果旧 state 或测试 state 没传 operation，就默认按 run 处理。
    return state.get("operation", "run")


def build_rag_agent_answer_query(state: RagAgentState) -> str:
    """只为最终生成补充会话连续性约束；检索仍使用 state['query']。"""

    # legacy token stream 不接入新能力，保持兼容路径行为不变。
    if get_rag_agent_operation(state) == "stream":
        return state["query"]
    history = "\n\n".join(
        item
        for item in (
            "【会话摘要】\n" + state["summary_text"]
            if state.get("summary_text")
            else "",
            "【最近对话】\n" + state["history_window_text"]
            if state.get("history_window_text")
            else "",
        )
        if item
    )
    if not history:
        return state["query"]
    return (
        f"{state['query']}\n\n"
        "<conversation_context>\n"
        "以下内容只用于理解多轮指代、格式偏好和已确认的任务约束；"
        "它不是知识来源，不得作为事实依据或引用。当前问题优先。\n"
        f"{history[-12_000:]}\n"
        "</conversation_context>"
    )


def get_rag_agent_step_index(operation: str, step_name: str) -> int:
    """返回节点在指定入口链路中的稳定追踪序号。"""
    # stream_events 多一个 emit_sources 步骤，所以 step_index 和 run/stream 不完全相同。
    # LangSmith trace 中保留稳定 index，后续排查时可以按顺序复盘 Agent 链路。
    if operation == "stream_events":
        indexes = {
            "query_rewrite": 0,
            "decide_next_action": 1,
            "check_loop_limits": 2,
            "direct_answer": 3,
            "call_nl2sql_query": 3,
            "call_direct_web": 3,
            "clarification_required": 3,
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
        "call_nl2sql_query": 3,
        "call_direct_web": 3,
        "clarification_required": 3,
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
    """汇总状态中的公共字段，并合并当前节点专属的追踪输入。"""
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
    """根据 Agent 状态创建单个节点的 LangSmith trace 上下文。"""
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
    """把 state 中序列化的筛选条件还原为检索器使用的内部模型。"""
    # HTTP schema 的 filters 在 initial_state 中已经 model_dump 成 dict。
    # 这里再转回内部 RetrievalFilters，供 knowledge_retrieval helper 使用。
    raw_filters = state.get("filters", {})
    filters = raw_filters if isinstance(raw_filters, dict) else None
    return build_retrieval_filters_from_mapping(filters)


def build_loop_limit_error_decision(reason: str) -> AgentErrorDecision:
    """把主动触发的循环上限转换为统一的可恢复错误决策。"""
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
    """根据循环检查结果，选择直接回答、任务执行、澄清或检索分支。"""
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
        "structured_data_query",
        "direct_web",
        "execute_task_plan",
        "clarification_required",
    ):
        return route

    return "knowledge_retrieval"


def route_after_tool_call(state: RagAgentState) -> RagAgentRoute:
    """根据工具调用产生的错误决策，选择错误回答或请求失败分支。"""
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
    task_router: AgentTaskRouter | None = None,
    task_planner: AgentTaskPlanner | None = None,
    capability_service: AgentTaskCapabilityService | None = None,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造意图路由节点：Router 定意图，Planner 为复杂任务创建计划。"""
    # Router 只选择业务意图；Planner 只为已确定的分支创建 TaskPlan。
    async def decide_next_action_node(state: RagAgentState) -> dict[str, object]:
        """读取查询和冻结会话上下文，返回下一条 Graph 路由及其状态更新。"""
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="decide_next_action",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(state),
        ) as trace_run:
            operation = get_rag_agent_operation(state)

            def build_child_config(child_name: str):
                """为 Router 或 Planner 的 LLM 子调用继承当前节点的追踪上下文。"""
                return build_rag_langchain_child_config(
                    settings=settings,
                    state=state,
                    pipeline_provider="rag_agent",
                    operation=operation,
                    step_name="decide_next_action",
                    step_index=get_rag_agent_step_index(operation, "decide_next_action"),
                    child_name=child_name,
                    run_name=(
                        f"rag_agent_pipeline.{operation}."
                        f"decide_next_action.{child_name}"
                    ),
                )

            # 组装历史对话的上下文
            history = [
                item
                for item in (
                    (
                        "【会话摘要】\n" + state["summary_text"]
                        if state.get("summary_text")
                        else None
                    ),
                    (
                        "【最近对话】\n" + state["history_window_text"]
                        if state.get("history_window_text")
                        else None
                    ),
                )
                if item is not None
            ]
            # Router 仅消费冻结的摘要和最近窗口，不能自行读取会话存储。
            if task_router is None:
                raise RuntimeError("AgentTaskRouter 未配置")

            if state.get("dataset_id") and state.get("nl2sql_action") == "report":
                route_result = AgentTaskRouteResult(
                    decision=AgentRouteDecision(
                        intent="knowledge_document_management",
                        confidence=1.0,
                        reason="server_bound_nl2sql_report",
                    ),
                    source="rule",
                    latency_ms=0.0,
                )
            else:
                route_result = await task_router.route(
                    query=state["query"],
                    history=history,
                    langchain_config_factory=build_child_config,
                    dataset_query_bound=bool(
                        state.get("dataset_id")
                        and state.get("nl2sql_action") == "query"
                    ),
                )
            decision = route_result.decision
            route_fields: dict[str, object] = {
                "route_intent": decision.intent,
                "route_confidence": decision.confidence,
                "route_source": route_result.source,
                "route_model": settings.agent_router_model_name,
                "route_latency_ms": round(route_result.latency_ms, 2),
                "route_rule_matched": route_result.source == "rule",
            }
            # 需要用户补充query信息
            if decision.intent == "clarification_required":
                result = {
                    "route": "clarification_required",
                    "route_reason": route_result.clarification_code
                    or "ambiguous_intent",
                    "clarification_required": True,
                    "clarification_code": route_result.clarification_code
                    or "ambiguous_intent",
                    "clarification_question": decision.clarification_question,
                    "step_count": state["step_count"] + 1,
                    **route_fields,
                }
                if trace_run is not None:
                    trace_run.add_outputs(result)
                return result

            current_user = state.get("current_user")
            user_id = current_user.user_id if current_user is not None else None
            task_plan = None
            # 只冻结本次请求选择的检索参数和联网许可；ACL 必须在 confirm 时重建。
            research_policy = AgentResearchPolicy(
                mode=state["mode"],
                top_k=state["top_k"],
                candidate_k=state["candidate_k"],
                min_score=state["min_score"],
                source_path=(
                    str(state["filters"].get("source_path"))
                    if state["filters"].get("source_path")
                    else None
                ),
                section_path=[
                    str(item) for item in state["filters"].get("section_path", [])
                ],
                web_policy=(
                    "fallback" if state.get("allow_web_fallback", False) else "disabled"
                ),
                dataset_id=(
                    str(state["dataset_id"]) if state.get("dataset_id") else None
                ),
                nl2sql_action=(
                    str(state["nl2sql_action"])
                    if state.get("dataset_id")
                    and state.get("nl2sql_action") in {"query", "report"}
                    else None
                ),
            )

            if decision.intent == "structured_data_query":
                result = {
                    "route": "structured_data_query",
                    "route_reason": "router_selected_structured_data_query",
                    "step_count": state["step_count"] + 1,
                    **route_fields,
                }
                if trace_run is not None:
                    trace_run.add_outputs(result)
                return result

            # 进入需要 Planner 拆解的复杂任务
            if decision.intent == "question_decomposition":
                if task_planner is None or capability_service is None or current_user is None:
                    raise RuntimeError("Research Planner 或 Capability Service 未配置")
                capability = await capability_service.resolve_research(
                    user=current_user,
                    dataset_id=(str(state["dataset_id"]) if state.get("dataset_id") else None),
                    allow_direct_web=state.get("allow_direct_web", True),
                    allow_web_fallback=state.get("allow_web_fallback", False),
                )
                task_plan = await task_planner.plan_question_decomposition(
                    request=ResolvedPlanningRequest(
                        current_query=state["original_query"],
                        relevant_history=state.get("planning_history", []),
                        resolved_query=state["query"],
                    ),
                    user_id=current_user.user_id,
                    capability_snapshot=capability,
                    research_policy=ResearchTaskPolicy(
                        mode=state["mode"],
                        top_k=state["top_k"],
                        candidate_k=state["candidate_k"],
                        min_score=state["min_score"],
                        source_path=(
                            str(state["filters"].get("source_path"))
                            if state["filters"].get("source_path")
                            else None
                        ),
                        section_path=[
                            str(item) for item in state["filters"].get("section_path", [])
                        ],
                        dataset_id=(str(state["dataset_id"]) if state.get("dataset_id") else None),
                        nl2sql_action=("query" if state.get("dataset_id") else None),
                        allow_direct_web=state.get("allow_direct_web", True),
                        allow_web_fallback=state.get("allow_web_fallback", False),
                    ),
                    langchain_config_factory=build_child_config,
                )

            # 进入Planner文档操作任务
            elif decision.intent == "knowledge_document_management":
                if task_planner is None:
                    raise RuntimeError("AgentTaskPlanner 未配置")
                task_plan = task_planner.build_document_management_plan(
                    query=state["query"],
                    user_id=user_id,
                    research_policy=research_policy,
                )
            # 简单纯 Web 请求不创建 TaskPlan；执行节点会做统一 Web 能力校验。
            elif decision.intent == "web_research":
                if capability_service is None or current_user is None:
                    raise RuntimeError("Direct Web Capability Service 未配置")
                capability_service.resolve_direct_web(
                    user=current_user,
                    allow_direct_web=state.get("allow_direct_web", True),
                )
                result = {
                    "route": "direct_web",
                    "route_reason": "router_selected_direct_web",
                    "step_count": state["step_count"] + 1,
                    **route_fields,
                }
                if trace_run is not None:
                    trace_run.add_outputs(result)
                return result

            # 任务已生成，开始执行 拆解后的子任务
            if task_plan is not None:
                route: RagAgentRoute = "execute_task_plan"
                step_count = state["step_count"] + 1
                result = {
                    "route": route,
                    "route_reason": "agent_task_plan_detected",
                    "step_count": step_count,
                    "agent_task_plan": task_plan,
                    "agent_task_plan_id": task_plan.task_plan_id,
                    **route_fields,
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
                            **route_fields,
                        }
                    )
                return result

            # 上面的复杂节点都没有触发，表示当前任务为简单的检索任务，判断是直接回答，还是检索知识库
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
                **route_fields,
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


def create_call_nl2sql_query_node(
    settings: Settings,
    nl2sql_service: Nl2SqlService | None,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造结构化数据查询节点；Dataset 和用户身份都来自服务端状态。"""

    async def call_nl2sql_query_node(
        state: RagAgentState,
    ) -> dict[str, object]:
        if nl2sql_service is None:
            raise RuntimeError("NL2SQL 服务未配置")
        user = state.get("current_user")
        dataset_id = state.get("dataset_id")
        if user is None or not dataset_id:
            raise RuntimeError("NL2SQL 查询缺少服务端用户或 Dataset 绑定")
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="call_nl2sql_query",
            run_type="tool",
            inputs=build_rag_agent_step_inputs(
                state,
                tool_name="nl2sql_query",
                dataset_id=dataset_id,
            ),
        ) as trace_run:
            result = await nl2sql_service.query(
                user=user,
                dataset_id=dataset_id,
                question=state["query"],
            )
            update = {
                "answer": result.summary,
                "nl2sql_result": result,
                "tool_name": "nl2sql_query",
                "tool_call_count": state["tool_call_count"] + 1,
                "final_reason": "structured_data_query_completed",
            }
            if trace_run is not None:
                trace_run.add_outputs(
                    {
                        "query_id": result.query_id,
                        "dataset_id": result.dataset_id,
                        "row_count": result.row_count,
                        "status": "completed",
                    }
                )
            return update

    return call_nl2sql_query_node


def create_agent_clarification_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, object]]:
    """把 Router 的澄清决定转换成正常回答，要求用户补充上下文，不触发 Planner 或 Tool。"""

    async def clarification_node(state: RagAgentState) -> dict[str, object]:
        """将 Router 给出的澄清问题写为最终回答，并标记正常结束原因。"""
        question = state.get("clarification_question") or (
            "请明确希望进行普通问答、复杂分析、联网检索，"
            "还是创建、修改或删除知识库文档。"
        )
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="clarification_required",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(
                state,
                clarification_code=state.get("clarification_code"),
            ),
        ) as trace_run:
            result = {
                "answer": question,
                "final_reason": state.get("clarification_code")
                or "ambiguous_intent",
            }
            if trace_run is not None:
                trace_run.add_outputs(result)
            return result

    return clarification_node


def create_check_loop_limits_node(
    settings: Settings,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造把循环次数和工具调用次数限制到配置范围内的节点。"""
    async def check_loop_limits_node(state: RagAgentState) -> dict[str, object]:
        """将当前状态投影为循环快照，并在到达上限时写入错误决策。"""
        async with rag_agent_langsmith_step_trace(
            settings=settings,
            state=state,
            step_name="check_loop_limits",
            run_type="chain",
            inputs=build_rag_agent_step_inputs(state, route=state.get("route")),
        ) as trace_run:
            limits = build_agent_loop_limits_from_settings(settings)
            if state.get("route") in {"direct_answer", "clarification_required"}:
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
    """构造无需检索或 LLM 的固定直接回答节点。"""
    # 直接回答节点用于问候、能力说明等不需要知识库的 query。
    # 它不调用 LLM，避免把简单系统能力说明变成不稳定的模型输出。
    async def direct_answer_node(state: RagAgentState) -> dict[str, str]:
        """写入固定系统回答和结束原因，供 Graph 直接结束本次请求。"""
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
    """构造调用向量/关键词检索工具并把结果写回状态的节点。"""
    # 这是 13-11 的核心工具节点。
    # 它不通过 LangChain Tool 字符串摘要，而是直接复用底层 helper 拿结构化 RetrievedDoc。
    async def call_knowledge_retrieval_node(
        state: RagAgentState,
    ) -> dict[str, object]:
        """执行知识检索；将成功文档或分类后的工具错误更新写入 state。"""
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
        """执行已生成的计划，或把需要人工确认的计划保存后返回。"""
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
                if not isinstance(plan, ResearchTaskPlan):
                    raise RuntimeError("question_decomposition 必须使用 ResearchTaskPlan v2")
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
                """为 TaskExecutor 的每次模型调用建立当前任务的子 trace 配置。"""
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
    """把结构化任务计划渲染为聊天兼容的摘要文本。"""
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
    if getattr(plan, "target_path", None):
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
    if isinstance(plan, ResearchTaskPlan):
        final_answer = plan.final_output.answer if plan.final_output is not None else None
    else:
        final_answer = plan.final_output.get("final_answer")
    if isinstance(final_answer, str) and final_answer.strip():
        lines.extend(["", "最终答案：", final_answer.strip()])
    return "\n".join(lines)


def create_agent_rerank_node(
    settings: Settings,
    reranker: BaseReranker,
    rerank_top_k: int,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造对检索候选文档重排序，并在服务异常时降级的节点。"""
    # rerank 是质量增强层，不是唯一事实来源。
    # 所以 rerank 的 ExternalServiceError 会降级为 fallback docs，而不是直接中断 Agent。
    async def rerank_node(state: RagAgentState) -> dict[str, object]:
        """重排 state 中的文档，或保留截断候选文档作为可恢复降级结果。"""
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
    parent_expander: MarkdownParentContextExpander | None = None,
) -> Callable[[RagAgentState], dict[str, object]]:
    """构造将安全检索文档转换为 LLM 上下文的节点。"""
    # build_context 是 RAG 和 LLM 之间的适配层：
    # 输入是结构化 docs，输出是 LLM client 能消费的 RagContext。
    async def build_context_node(state: RagAgentState) -> dict[str, object]:
        """过滤不安全文档并生成包含查询与文档的 RagContext。"""
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
            context = await assemble_rag_context(
                settings=settings,
                query=state["query"],
                docs=docs,
                filters=state["filters"],
                source="rag_agent.build_context",
                parent_expander=(
                    parent_expander
                    if state.get("operation", "run") != "stream"
                    else None
                ),
                prompt_guard=prompt_guard,
            )
            docs = context.docs
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
                        **build_context_observation(context),
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
    """构造非流式最终回答生成节点。"""
    # 非流式 run 使用这个节点一次性生成完整 answer。
    # stream / stream_events 为了保持 token-only，会在 service 层手写到 llm_client.stream。
    async def generate_answer_node(state: RagAgentState) -> dict[str, str]:
        """调用 LLM 生成完整回答，完成输出 Guard 后写入最终状态。"""
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
                    query=build_rag_agent_answer_query(state),
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
    """构造把可解释错误决策转换为用户可见回答的节点。"""
    # 可恢复或可解释的错误会进入这里，例如知识库无结果、loop 达上限。
    # 这个节点把错误决策转换成面向用户的最终回答。
    async def error_answer_node(state: RagAgentState) -> dict[str, str]:
        """读取错误决策，生成安全的最终回答并标记结束原因。"""
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
    """构造把不可恢复错误继续抛给 API 或 SSE 错误层的节点。"""
    # 不可恢复错误进入这里，并继续抛 AppServiceError 体系内的异常。
    # 这样 HTTP / SSE 层仍然复用现有全局错误响应和 error event 包装。
    async def fail_request_node(state: RagAgentState) -> dict[str, object]:
        """记录不可恢复错误的 trace 后抛出统一服务异常。"""
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
