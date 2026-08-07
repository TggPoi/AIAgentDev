from langgraph.graph import END, START, StateGraph

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.graph.rag_agent.rag_agent_nodes import (
    create_agent_build_context_node,
    create_agent_clarification_node,
    create_agent_error_answer_node,
    create_agent_fail_request_node,
    create_agent_generate_answer_node,
    create_agent_rerank_node,
    create_call_knowledge_retrieval_node,
    create_call_direct_web_node,
    create_call_nl2sql_query_node,
    create_check_loop_limits_node,
    create_execute_task_plan_node,
    create_next_action_decision_node,
    create_rag_agent_direct_answer_node,
    route_after_direct_web,
    route_after_loop_check,
    route_after_tool_call,
)
from fast_app.graph.rag_agent.rag_agent_state import RagAgentState
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.agent_task_router import AgentTaskRouter
from fast_app.services.agent_tasks.agent_task_capability_service import (
    AgentTaskCapabilityService,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.nl2sql.service import Nl2SqlService


def build_rag_agent_graph(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
    rerank_top_k: int,
    prompt_guard: PromptGuardService | None = None,
    parent_expander: MarkdownParentContextExpander | None = None,
    task_router: AgentTaskRouter | None = None,
    task_planner: AgentTaskPlanner | None = None,
    task_executor: AgentTaskExecutor | None = None,
    nl2sql_service: Nl2SqlService | None = None,
    capability_service: AgentTaskCapabilityService | None = None,
):
    # 这是 13-11 新增的独立 Agent graph。
    # 它和现有 build_rag_graph() 并列存在，避免改变 langgraph provider 的稳定行为。
    builder = StateGraph(RagAgentState)

    # =================开始构造节点==========================
    # decide_next_action 是 Agent 的“判断”步骤：先决定是否需要知识库，还是调用工具
    builder.add_node(
        "decide_next_action",
        create_next_action_decision_node(
            settings=settings,
            task_router=task_router,
            task_planner=task_planner,
            capability_service=capability_service,
        ),
    )
    if task_executor is not None:
        builder.add_node(
            "execute_task_plan",
            create_execute_task_plan_node(
                settings=settings,
                task_executor=task_executor,
            ),
        )
    # check_loop_limits 把 13-8 的循环控制层接进 graph。
    # 即使当前最小 Agent 只调用一次工具，也先把控制点放进主链路。
    builder.add_node(
        "check_loop_limits",
        create_check_loop_limits_node(settings=settings),
    )
    # call_knowledge_retrieval 是工具调用节点，底层复用 agents/rag_agent_tools.py。
    builder.add_node(
        "call_knowledge_retrieval",
        create_call_knowledge_retrieval_node(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        ),
    )
    builder.add_node(
        "call_nl2sql_query",
        create_call_nl2sql_query_node(
            settings=settings,
            nl2sql_service=nl2sql_service,
        ),
    )
    builder.add_node("call_direct_web", create_call_direct_web_node(settings=settings))
    builder.add_node(
        "rerank",
        create_agent_rerank_node(
            settings=settings,
            reranker=reranker,
            rerank_top_k=rerank_top_k,
        ),
    )
    builder.add_node(
        "build_context",
        create_agent_build_context_node(
            settings=settings,
            prompt_guard=prompt_guard,
            parent_expander=parent_expander,
        ),
    )
    builder.add_node(
        "generate_answer",
        create_agent_generate_answer_node(
            settings=settings,
            llm_client=llm_client,
            prompt_guard=prompt_guard,
        ),
    )
    builder.add_node(
        "direct_answer",
        create_rag_agent_direct_answer_node(settings=settings),
    )
    builder.add_node(
        "clarification_required",
        create_agent_clarification_node(settings=settings),
    )
    builder.add_node(
        "final_error_answer",
        create_agent_error_answer_node(settings=settings),
    )
    builder.add_node(
        "fail_request",
        create_agent_fail_request_node(settings=settings),
    )

    # =================开始构造图==========================
    builder.add_edge(START, "decide_next_action")
    builder.add_edge("decide_next_action", "check_loop_limits")
    # 条件边只读取 state，不做额外副作用。
    # 这样“判断”和“执行”保持分离，便于 trace 和后续测试。
    next_action_routes = {
        "direct_answer": "direct_answer",
        "clarification_required": "clarification_required",
        "knowledge_retrieval": "call_knowledge_retrieval",
        "structured_data_query": "call_nl2sql_query",
        "direct_web": "call_direct_web",
        "final_error_answer": "final_error_answer",
    }

    # 检查任务执行对象是否被创建，存在则允许路由到plan阶段
    if task_executor is not None:
        next_action_routes["execute_task_plan"] = "execute_task_plan"

    # 循环限制检查完成后，进入next_action_routes选择下一个节点
    builder.add_conditional_edges(
        "check_loop_limits",
        route_after_loop_check,
        next_action_routes,
    )
    # 工具调用后可能成功进入 rerank，也可能根据错误策略进入最终错误回答或请求失败。
    builder.add_conditional_edges(
        "call_knowledge_retrieval",
        route_after_tool_call,
        {
            "knowledge_retrieval": "rerank",
            "final_error_answer": "final_error_answer",
            "fail_request": "fail_request",
        },
    )
    # 成功路径：knowledge_retrieval -> rerank -> build_context -> generate_answer。
    builder.add_edge("rerank", "build_context")
    # direct_web 工具后与 knowledge_retrieval 同样受错误策略管控：
    # 成功进入 build_context，可解释错误进入最终错误回答，不可恢复错误终止请求。
    builder.add_conditional_edges(
        "call_direct_web",
        route_after_direct_web,
        {
            "build_context": "build_context",
            "final_error_answer": "final_error_answer",
            "fail_request": "fail_request",
        },
    )
    builder.add_edge("build_context", "generate_answer")
    # 终止路径：直接回答、可解释错误回答、不可恢复错误、正常生成回答。
    builder.add_edge("direct_answer", END)
    builder.add_edge("call_nl2sql_query", END)

    # 触发clarification_required节点，需要用户明确补充上下文，直接结束
    builder.add_edge("clarification_required", END)
    if task_executor is not None:
        builder.add_edge("execute_task_plan", END)
    builder.add_edge("final_error_answer", END)
    builder.add_edge("fail_request", END)
    builder.add_edge("generate_answer", END)

    return builder.compile()
