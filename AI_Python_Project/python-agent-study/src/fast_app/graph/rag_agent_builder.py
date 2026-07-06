from langgraph.graph import END, START, StateGraph

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.graph.rag_agent_nodes import (
    create_agent_build_context_node,
    create_agent_error_answer_node,
    create_agent_fail_request_node,
    create_agent_generate_answer_node,
    create_agent_rerank_node,
    create_authorize_tool_call_node,
    create_call_knowledge_retrieval_node,
    create_check_loop_limits_node,
    create_execute_task_plan_node,
    create_next_action_decision_node,
    create_rag_agent_direct_answer_node,
    create_tool_permission_denied_node,
    create_tool_approval_node,
    route_after_loop_check,
    route_after_tool_call,
    route_after_tool_authorization,
)
from fast_app.graph.rag_agent_state import RagAgentState
from fast_app.services.agent_document_action_planner import AgentDocumentActionPlanner
from fast_app.services.agent_task_executor import AgentTaskExecutor
from fast_app.services.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.agent_tool_approval_service import AgentToolApprovalService
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.prompt_guard_service import PromptGuardService


def build_rag_agent_graph(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
    rerank_top_k: int,
    prompt_guard: PromptGuardService | None = None,
    document_action_planner: AgentDocumentActionPlanner | None = None,
    task_planner: AgentTaskPlanner | None = None,
    task_executor: AgentTaskExecutor | None = None,
    document_management_service: KnowledgeDocumentManagementService | None = None,
    tool_permission_service: AgentToolPermissionService | None = None,
    tool_audit_service: AgentToolAuditService | None = None,
    tool_approval_service: AgentToolApprovalService | None = None,
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
            document_action_planner=document_action_planner,
            task_planner=task_planner,
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
    if (
        document_management_service is not None
        and tool_permission_service is not None
        and tool_audit_service is not None
        and tool_approval_service is not None
    ):
        builder.add_node(
            "authorize_tool_call",
            create_authorize_tool_call_node(
                settings=settings,
                document_management_service=document_management_service,
                tool_permission_service=tool_permission_service,
                tool_audit_service=tool_audit_service,
            ),
        )
        builder.add_node(
            "create_tool_approval",
            create_tool_approval_node(
                settings=settings,
                tool_approval_service=tool_approval_service,
            ),
        )
        builder.add_node(
            "tool_permission_denied",
            create_tool_permission_denied_node(settings=settings),
        )
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
        "knowledge_retrieval": "call_knowledge_retrieval",
        "authorize_tool_call": "authorize_tool_call",
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
    if (
        document_management_service is not None
        and tool_permission_service is not None
        and tool_audit_service is not None
        and tool_approval_service is not None
    ):
        builder.add_conditional_edges(
            "authorize_tool_call",
            route_after_tool_authorization,
            {
                "tool_approval_created": "create_tool_approval",
                "tool_permission_denied": "tool_permission_denied",
            },
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
    builder.add_edge("build_context", "generate_answer")
    # 终止路径：直接回答、可解释错误回答、不可恢复错误、正常生成回答。
    builder.add_edge("direct_answer", END)
    if task_executor is not None:
        builder.add_edge("execute_task_plan", END)
    if (
        document_management_service is not None
        and tool_permission_service is not None
        and tool_audit_service is not None
        and tool_approval_service is not None
    ):
        builder.add_edge("create_tool_approval", END)
        builder.add_edge("tool_permission_denied", END)
    builder.add_edge("final_error_answer", END)
    builder.add_edge("fail_request", END)
    builder.add_edge("generate_answer", END)

    return builder.compile()
