from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from fast_app.agents.mcp_agent_tools import build_mcp_agent_tools
from fast_app.agents.mcp_client_boundary import McpStdioClientBoundary
from fast_app.agents.mcp_tool_contracts import McpStdioServerConfig
from fast_app.agents.rag_agent_tools import KNOWLEDGE_RETRIEVAL_TOOL_NAME
from fast_app.agents.rag_agent_tools import retrieve_knowledge_docs
from fast_app.agents.web_search_tools import (
    WEB_SEARCH_TOOL_NAME,
    search_web_with_bocha,
)
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskSubQuestion,
    AgentTaskSubQuestionResult,
    AgentTaskToolCallTrace,
    AgentToolStep,
    AgentToolStepStatus,
)
from fast_app.domain.agent_tool_permissions import (
    AgentToolCallContext,
    AgentToolPermissionAction,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_permission_service import (
    AgentToolPermissionService,
    tool_name_for_document_operation,
)
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.rag_pipeline_service import (
    build_content_preview,
    build_rag_context,
    build_top_doc_ids,
)


LangChainConfigFactory = Callable[[str], RunnableConfig]


class AgentTaskToolSelectionPayload(BaseModel):
    """LLM 工具调用不可用时，用结构化 JSON 表达工具选择结果。"""

    selected_tool: str = Field(default="knowledge_retrieval")
    tool_input: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="")


class AgentTaskKnowledgeRetrievalToolInput(BaseModel):
    """传给 knowledge_retrieval 的最小参数 schema。"""

    query: str = Field(description="用于检索知识库的 query")
    mode: str = Field(default="hybrid", description="vector / keyword / hybrid")
    top_k: int = Field(default=5, ge=1, le=20)


class AgentTaskWebSearchToolInput(BaseModel):
    """传给 web_search 的最小参数 schema。"""

    query: str = Field(description="用于搜索公开互联网的 query")
    count: int = Field(default=5, ge=1, le=10)


TASK_TOOL_SELECTION_PROMPT = """你是 Agent TaskPlan 的工具选择器。

你只负责为当前子问题选择一个已绑定工具。
可用工具只来自 bound tools，不允许编造工具名。
每一轮最多选择一个工具；如果已有工具结果足够回答当前子问题，选择 none。
如果当前子问题可以只依赖已有子问题答案进行推理，可以不调用工具。
如果系统进入结构化输出模式，必须返回符合 schema 的 JSON 对象。

选择原则：
- 项目知识库、已有工程实现、内部文档相关问题，优先 knowledge_retrieval。
- 当前知识库可能没有、需要公开互联网或最新资料时，选择 web_search。
- 子问题中已经给出明确 URL，且存在 mcp__fetch 工具时，优先 mcp__fetch 读取网页正文。
- 综合性问题如果已有前置答案足够，可以不调用工具。
"""


class AgentTaskPlanStore:
    """用 runtime JSON 文件保存 TaskPlan 的当前快照。"""

    def __init__(self, settings: Settings) -> None:
        self._task_plan_dir = Path(settings.agent_task_plan_dir)

    def save(self, plan: AgentTaskPlan) -> None:
        """新增或覆盖同一个 task_plan_id 对应的 JSON 文件。"""

        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        plan.updated_at = datetime.now(UTC)
        path = self._path_for_new_plan(plan)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def load(self, task_plan_id: str) -> AgentTaskPlan:
        """按 task_plan_id 读取最近一次保存的计划快照。"""

        # task_plan_id 来自外部确认接口，先做最小格式校验，避免任意 glob 查询。
        if not task_plan_id.startswith("task_plan_"):
            raise AppServiceError("非法 task_plan_id")
        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        matches = sorted(self._task_plan_dir.glob(f"*_{task_plan_id}.json"))
        if not matches:
            raise AppServiceError("Agent task plan 不存在")
        return AgentTaskPlan.model_validate(
            json.loads(matches[-1].read_text(encoding="utf-8"))
        )

    def _path_for_new_plan(self, plan: AgentTaskPlan) -> Path:
        """已有文件继续覆盖，避免同一个 plan 在执行中生成多份快照。"""

        existing = sorted(self._task_plan_dir.glob(f"*_{plan.task_plan_id}.json"))
        if existing:
            return existing[-1]
        created = plan.created_at.strftime("%Y%m%d_%H%M%S")
        return self._task_plan_dir / f"{created}_{plan.task_plan_id}.json"


class AgentTaskExecutor:
    """执行 TaskPlan。

    当前保留两条链路：
    - question_decomposition：确认后按子问题顺序选工具、回答并整合。
    - knowledge_report_to_document：旧报告生成链路，写文件前仍走权限和确认。
    """

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        document_management_service: KnowledgeDocumentManagementService,
        tool_permission_service: AgentToolPermissionService,
        tool_audit_service: AgentToolAuditService,
        task_plan_store: AgentTaskPlanStore,
    ) -> None:
        self._settings = settings
        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        self._llm_client = llm_client
        self._document_management_service = document_management_service
        self._tool_permission_service = tool_permission_service
        self._tool_audit_service = tool_audit_service
        self._task_plan_store = task_plan_store

    def save_plan(self, plan: AgentTaskPlan) -> None:
        """保存等待用户确认的 TaskPlan，不在 chat 请求里直接推进执行。"""

        self._task_plan_store.save(plan)

    async def _generate_with_trace(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> str:
        """调用 LLM；兼容测试中仍使用旧签名的 fake client。"""

        try:
            # 真实 LangChain client 使用 langchain_config 透传 LangSmith 子 run 名称。
            return await self._llm_client.generate(
                query=query,
                context=context,
                langchain_config=langchain_config,
            )
        except TypeError as exc:
            if "langchain_config" not in str(exc):
                raise
            return await self._llm_client.generate(query=query, context=context)

    async def execute_question_decomposition_plan(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """按顺序回答问题拆解计划的子问题，并把结果整合成最终答案。"""

        if plan.task_kind != "question_decomposition":
            raise AppServiceError(f"不支持的问题拆解 task kind: {plan.task_kind}")

        # 执行入口会被确认接口调用，所以这里重新绑定 user_id 并落盘运行态快照。
        plan.user_id = plan.user_id or user.user_id
        plan.status = AgentTaskPlanStatus.RUNNING
        plan.final_output = {
            "sub_question_results": [],
            "used_tools": [],
        }
        self._task_plan_store.save(plan)

        results: list[AgentTaskSubQuestionResult] = []
        try:
            # sub_questions 是规划事实；执行结果单独写入 final_output，避免污染 plan。
            for sub_question in sorted(plan.sub_questions, key=lambda item: item.order):
                result = await self._execute_sub_question(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=results,
                    mode=mode,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    min_score=min_score,
                    filters=filters,
                    langchain_config_factory=langchain_config_factory,
                )
                results.append(result)
                # 每完成一个子问题就保存一次，便于接口或页面看到中间进度。
                plan.final_output["sub_question_results"] = [
                    item.model_dump(mode="json") for item in results
                ]
                plan.final_output["used_tools"] = sorted(
                    {
                        tool_name
                        for item in results
                        for tool_name in _result_used_tools(item)
                    }
                )
                self._task_plan_store.save(plan)

            # 允许单个子问题失败，但不能在完全没有有效答案时继续综合。
            if not any(item.status == "completed" for item in results):
                raise AppServiceError("所有子问题都执行失败，无法整合最终答案")

            final_answer = await self._synthesize_final_answer(
                plan,
                results,
                langchain_config_factory=langchain_config_factory,
            )
            plan.status = AgentTaskPlanStatus.COMPLETED
            plan.final_output.update(
                {
                    "final_answer": final_answer,
                    "status": plan.status.value,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            self._task_plan_store.save(plan)
            return plan
        except Exception as exc:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = f"{type(exc).__name__}: {exc}"
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
            raise

    async def _execute_sub_question(
        self,
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskSubQuestionResult:
        """执行一个子问题：让 LLM 进行有限多轮工具选择，再生成子问题答案。

        previous_results 是已经完成的前置子问题答案，用来支持“后一个子问题依赖前一个
        子问题结论”的场景；tool_calls 只记录当前子问题内部的多轮工具调用轨迹。
        """

        available_tools = await self._build_available_task_tools()
        max_tool_calls = max(self._settings.agent_max_tool_calls, 0)
        tool_calls: list[AgentTaskToolCallTrace] = []

        try:
            # 每个子问题最多调用 agent_max_tool_calls 次工具；每轮只允许一个工具，
            # 这样 trace 和 runtime JSON 都能清楚表达“第几轮调用了什么”。
            for round_index in range(1, max_tool_calls + 1):
                # 让 LLM 基于原始问题、当前子问题、前置子问题答案、当前子问题已调用过的工具，
                # 判断下一步是否还需要工具。selected_tool="none" 表示信息已足够，可以收口。
                selection = await self._select_tool_for_sub_question(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=previous_results,
                    default_mode=mode,
                    default_top_k=top_k,
                    available_tools=available_tools,
                    tool_calls=tool_calls,
                    langchain_config_factory=langchain_config_factory,
                )
                selected_tool = str(selection.get("selected_tool") or "none")
                tool_input = _normalize_tool_input(selection.get("tool_input"))
                reason = str(selection.get("reason") or "")
                
                # 已经不需要调用tool时，退出循环
                if selected_tool == "none":
                    break

                call_id = f"{sub_question.sub_question_id}_tool_{round_index}"
                try:
                    # 工具真正执行前会再次通过后端白名单查找；LLM 只能“建议”工具名和参数，
                    # 不能绕过 _run_task_tool_for_sub_question 里的本地校验和工具分发。
                    tool_output, answer, evidence = await self._run_task_tool_for_sub_question(
                        selected_tool=selected_tool,
                        tool_input=tool_input,
                        available_tools=available_tools,
                        sub_question=sub_question,
                        previous_results=previous_results,
                        mode=mode,
                        top_k=top_k,
                        candidate_k=candidate_k,
                        min_score=min_score,
                        filters=filters,
                        tool_call_round=round_index,
                        langchain_config_factory=langchain_config_factory,
                    )
                    tool_calls.append(
                        AgentTaskToolCallTrace(
                            call_id=call_id,
                            round=round_index,
                            tool_name=selected_tool,
                            tool_input=tool_input,
                            tool_output={
                                **tool_output,
                                "answer": answer,
                                "evidence": evidence,
                            },
                            status="completed",
                            reason=reason,
                        )
                    )
                except Exception as exc:
                    # 单轮工具失败只结束当前子问题的 tool loop，不直接终止整个 TaskPlan。
                    # 外层 execute_question_decomposition_plan 会继续尝试后续子问题。
                    tool_calls.append(
                        AgentTaskToolCallTrace(
                            call_id=call_id,
                            round=round_index,
                            tool_name=selected_tool,
                            tool_input=tool_input,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            reason=reason,
                        )
                    )
                    break

            completed_calls = [item for item in tool_calls if item.status == "completed"]
            if completed_calls:
                # 多轮工具的原始输出只作为证据和上下文；最终子问题答案统一由 LLM
                # 基于所有成功工具调用生成，避免直接把工具原文当成用户可读答案。
                answer = await self._answer_from_tool_calls(
                    sub_question=sub_question,
                    previous_results=previous_results,
                    tool_calls=completed_calls,
                    langchain_config_factory=langchain_config_factory,
                )
                # 抽取支撑该子问题回答的证据摘要
                evidence = _collect_tool_call_evidence(completed_calls)
                last_call = completed_calls[-1]
                return AgentTaskSubQuestionResult(
                    sub_question_id=sub_question.sub_question_id,
                    question=sub_question.question,
                    selected_tool=last_call.tool_name,
                    tool_input=last_call.tool_input,
                    tool_output=last_call.tool_output,
                    tool_calls=tool_calls,
                    answer=answer,
                    evidence=evidence,
                    status="completed",
                )

            if tool_calls:
                # 到这里说明 LLM 选择过工具，但没有任何一轮成功；记录失败结果，
                # 让最终 plan 能展示失败原因，而不是静默丢掉这个子问题。
                last_call = tool_calls[-1]
                return AgentTaskSubQuestionResult(
                    sub_question_id=sub_question.sub_question_id,
                    question=sub_question.question,
                    selected_tool=last_call.tool_name,
                    tool_input=last_call.tool_input,
                    tool_output=last_call.tool_output,
                    tool_calls=tool_calls,
                    status="failed",
                    error=last_call.error,
                )

            # LLM 一开始就判断不需要工具，或者 agent_max_tool_calls=0 时，走纯推理分支。
            # 这个分支只能使用 previous_results，不会主动检索或访问外部工具。
            tool_output, answer, evidence = await self._answer_without_tool(
                sub_question=sub_question,
                previous_results=previous_results,
                langchain_config_factory=langchain_config_factory,
            )
            return AgentTaskSubQuestionResult(
                sub_question_id=sub_question.sub_question_id,
                question=sub_question.question,
                selected_tool="none",
                tool_input={},
                tool_output=tool_output,
                tool_calls=[],
                answer=answer,
                evidence=evidence,
                status="completed",
            )
        except Exception as exc:
            # 子问题失败不立刻中断整个计划，让后续子问题仍有机会完成。
            return AgentTaskSubQuestionResult(
                sub_question_id=sub_question.sub_question_id,
                question=sub_question.question,
                selected_tool=tool_calls[-1].tool_name if tool_calls else "none",
                tool_input=tool_calls[-1].tool_input if tool_calls else {},
                tool_calls=tool_calls,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _select_tool_for_sub_question(
        self,
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        default_mode: str,
        default_top_k: int,
        available_tools: list[BaseTool] | None = None,
        tool_calls: list[AgentTaskToolCallTrace] | None = None,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> dict[str, Any]:
        """选择子问题需要调用的 tool 工具。

        优先级：
        1. bound tools tool_call；
        2. 结构化 JSON；
        3. LLM 不可用时按 information_source_hint 兜底。
        """

        # available_tools 可以由外层传入，避免同一个子问题多轮选择时重复构造工具列表。
        available_tools = available_tools if available_tools is not None else await self._build_available_task_tools()
        tool_calls = tool_calls or []
        if not available_tools:
            return {"selected_tool": "none", "tool_input": {}}

        if self._settings.openai_api_key:
            # 获取 llm 根据子问题 选择要使用的tool
            selection = await self._select_tool_with_bound_tools(
                tools=available_tools,
                plan=plan,
                sub_question=sub_question,
                previous_results=previous_results,
                tool_calls=tool_calls,
                langchain_config_factory=langchain_config_factory,
            )
            if selection is None:
                selection = await self._select_tool_with_json(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=previous_results,
                    tool_calls=tool_calls,
                    langchain_config_factory=langchain_config_factory,
                )
            
            # 当前模型明确需要调用tool，判断question里面有没有包含明确的url，如果有，强制绑定 mcp__fetch 调用
            # 避免 子问题里已经有明确 URL ，但 LLM 没有选 fetch，或者选了 fetch 但没把 url 参数填好
            if selection is not None:
                return _repair_fetch_tool_selection(
                    selection=_validate_tool_selection(selection, available_tools),
                    sub_question=sub_question,
                    tools=available_tools,
                )

        # LLM 不可用时的兜底，不作为正常企业场景的主判断器。
        if tool_calls:
            return {"selected_tool": "none", "tool_input": {}}
        fallback_tool = sub_question.information_source_hint
        if fallback_tool not in {tool.name for tool in available_tools}:
            fallback_tool = KNOWLEDGE_RETRIEVAL_TOOL_NAME
        return _repair_fetch_tool_selection(
            selection={
                "selected_tool": fallback_tool,
                "tool_input": {
                    "query": sub_question.question,
                    "mode": default_mode,
                    "top_k": default_top_k,
                },
            },
            sub_question=sub_question,
            tools=available_tools,
        )

    async def _build_available_task_tools(self) -> list[BaseTool]:
        """构造本阶段允许 LLM 选择的工具白名单。"""

        async def knowledge_retrieval(query: str, mode: str = "hybrid", top_k: int = 5) -> str:
            # 这里只给 bind_tools 暴露 schema；真正执行发生在本服务自己的方法里。
            return ""

        tools: list[BaseTool] = [
            StructuredTool.from_function(
                coroutine=knowledge_retrieval,
                name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                description="检索项目知识库，适合回答内部文档、工程实现、知识库事实相关子问题。",
                args_schema=AgentTaskKnowledgeRetrievalToolInput,
            )
        ]

        if self._settings.bocha_api_key:
            # Bocha 未配置时不把 web_search 暴露给 LLM，避免模型选择不可执行工具。
            async def web_search(query: str, count: int = 5) -> str:
                # 同上：这里只参与 LLM tool calling，不直接承载业务执行。
                return ""

            tools.append(
                StructuredTool.from_function(
                    coroutine=web_search,
                    name=WEB_SEARCH_TOOL_NAME,
                    description="搜索公开互联网，适合回答知识库缺失、需要公开网页或较新信息的子问题。",
                    args_schema=AgentTaskWebSearchToolInput,
                )
            )
        tools.extend(await self._build_mcp_task_tools())
        return tools

    async def _build_mcp_task_tools(self) -> list[BaseTool]:
        """按配置发现 MCP stdio server，并包装成 Agent 可选择的工具。"""

        if not self._settings.agent_task_mcp_enabled:
            return []

        tools: list[BaseTool] = []

        # 读取 .env 中配置的 MCP stdio server，并只暴露 allowed_tool_names 白名单工具。
        for config in _load_mcp_stdio_server_configs(
            self._settings.agent_task_mcp_stdio_servers_json
        ):
            client = McpStdioClientBoundary(
                server_config=McpStdioServerConfig(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env"),
                ),
                allowed_tool_names=set(config.get("allowed_tool_names") or []),
            )
            tools.extend(await build_mcp_agent_tools(client))
        return tools

    async def _select_tool_with_bound_tools(
        self,
        tools: list[BaseTool],
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        tool_calls: list[AgentTaskToolCallTrace],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> dict[str, Any] | None:
        """给llm绑定bind_tools，让llm根据 query 选择要调用哪些tool完成任务，每次默认只获取 tool_calls 数组中的第一个tool"""

        try:
            model = ChatOpenAI(
                model=self._settings.llm_model_name,
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                temperature=0.0,
            ).bind_tools(tools)
            response = await model.ainvoke(
                # 开始由llm选择当前任务需要调用哪些tool
                _build_tool_selection_messages(
                    plan,
                    sub_question,
                    previous_results,
                    tool_calls,
                ),
                config=(
                    langchain_config_factory(
                        f"sub_question.{sub_question.sub_question_id}.tool_selection.bound_tools"
                    )
                    if langchain_config_factory is not None
                    else None
                ),
            )
        except Exception:
            return None

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # 模型明确不调用工具时，允许子问题走已有答案推理。
            return {"selected_tool": "none", "tool_input": {}}
        
        # 这里只取第一条 tool call，保证“每轮最多一个工具”的执行边界。
        first_call = tool_calls[0]
        if not isinstance(first_call, dict):
            return None
        
        return {
            "selected_tool": first_call.get("name"),
            "tool_input": first_call.get("args") or {},
        }

    async def _select_tool_with_json(
        self,
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        tool_calls: list[AgentTaskToolCallTrace],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> dict[str, Any] | None:
        """provider 不稳定支持 tool calling 时，退到结构化输出。"""

        try:
            model = ChatOpenAI(
                model=self._settings.llm_model_name,
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                temperature=0.0,
            ).with_structured_output(AgentTaskToolSelectionPayload)
            response = await model.ainvoke(
                _build_tool_selection_messages(
                    plan,
                    sub_question,
                    previous_results,
                    tool_calls,
                ),
                config=(
                    langchain_config_factory(
                        f"sub_question.{sub_question.sub_question_id}.tool_selection.json"
                    )
                    if langchain_config_factory is not None
                    else None
                ),
            )
        except Exception:
            return None
        if isinstance(response, AgentTaskToolSelectionPayload):
            return response.model_dump(mode="json")
        return response if isinstance(response, dict) else None

    async def _run_task_tool_for_sub_question(
        self,
        selected_tool: str,
        tool_input: dict[str, Any],
        available_tools: list[BaseTool],
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        tool_call_round: int = 1,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """执行本地工具或 MCP 工具，并统一返回摘要、答案和证据。"""

        # 内置工具走本服务的强类型方法，方便复用权限、检索参数和证据格式。
        if selected_tool == KNOWLEDGE_RETRIEVAL_TOOL_NAME:
            return await self._run_knowledge_retrieval_for_sub_question(
                sub_question=sub_question,
                tool_input=tool_input,
                mode=mode,
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                filters=filters,
                langchain_config_factory=langchain_config_factory,
            )
        if selected_tool == WEB_SEARCH_TOOL_NAME:
            return await self._run_web_search_for_sub_question(
                sub_question=sub_question,
                tool_input=tool_input,
                previous_results=previous_results,
                langchain_config_factory=langchain_config_factory,
            )

        # 走到这里的是 MCP 等外部工具：先按白名单取工具，再由 LangChain tool 执行。
        tool = _find_registered_tool(selected_tool, available_tools)
        content = await tool.ainvoke(
            tool_input,
            config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.tool.{selected_tool}.round_{tool_call_round}"
                )
                if langchain_config_factory is not None
                else None
            ),
        )
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        answer = await self._generate_with_trace(
            query=f"请基于 MCP 工具结果回答子问题：{sub_question.question}",
            context=RagContext(
                query=sub_question.question,
                docs=[],
                context_text=_append_text(
                    text,
                    _format_previous_answers(previous_results),
                    title="前置子问题答案",
                ),
            ),
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.mcp_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )
        return (
            {"content": text, "content_preview": build_content_preview(text)},
            answer,
            [
                {
                    "id": f"{selected_tool}_result",
                    "source": selected_tool,
                    "title": selected_tool,
                    "content_preview": build_content_preview(text),
                }
            ],
        )

    async def _run_knowledge_retrieval_for_sub_question(
        self,
        sub_question: AgentTaskSubQuestion,
        tool_input: dict[str, Any],
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """执行知识库检索，并基于检索结果回答当前子问题。"""

        # LLM 可能给出不完整或越界参数；这里用后端默认值和范围做最后收敛。
        query = str(tool_input.get("query") or sub_question.question).strip()
        selected_mode = str(tool_input.get("mode") or mode).strip()
        if selected_mode not in {"vector", "keyword", "hybrid"}:
            selected_mode = mode
        selected_top_k = _coerce_int(tool_input.get("top_k"), default=top_k, minimum=1, maximum=20)
        docs = await retrieve_knowledge_docs(
            settings=self._settings,
            vector_retriever=self._vector_retriever,
            keyword_retriever=self._keyword_retriever,
            query=query,
            mode=selected_mode,  # type: ignore[arg-type]
            top_k=selected_top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            filters=filters,
            pipeline_provider="rag_agent_task_sub_question",
        )
        # 子问题回答复用现有 RAG context 构造，避免新建一套上下文格式。
        answer = await self._generate_with_trace(
            query=f"请回答子问题：{sub_question.question}",
            context=build_rag_context(sub_question.question, docs),
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.knowledge_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )
        evidence = [_doc_to_evidence(doc) for doc in docs]
        return (
            {
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
            answer,
            evidence,
        )

    async def _run_web_search_for_sub_question(
        self,
        sub_question: AgentTaskSubQuestion,
        tool_input: dict[str, Any],
        previous_results: list[AgentTaskSubQuestionResult],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """执行网页搜索，并把搜索结果临时转成 RetrievedDoc 供 LLM 消费。"""

        query = str(tool_input.get("query") or sub_question.question).strip()
        count = _coerce_int(tool_input.get("count"), default=5, minimum=1, maximum=10)
        async with httpx.AsyncClient() as http_client:
            results = await search_web_with_bocha(
                settings=self._settings,
                http_client=http_client,
                query=query,
                count=count,
            )
        docs = [
            RetrievedDoc(
                id=f"web_{index}",
                content=" ".join(
                    part
                    for part in [item.title, item.snippet, item.summary, item.url]
                    if part
                ),
                score=1.0,
                source=WEB_SEARCH_TOOL_NAME,
                title=item.title,
                metadata={"url": item.url, "site_name": item.site_name},
            )
            for index, item in enumerate(results, start=1)
        ]
        context = build_rag_context(sub_question.question, docs)
        # web 结果可能需要结合前置子问题答案做综合判断。
        answer = await self._generate_with_trace(
            query=f"请回答子问题：{sub_question.question}",
            context=_append_previous_answers(context, previous_results),
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.web_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )
        evidence = [_doc_to_evidence(doc) for doc in docs]
        return (
            {"result_count": len(results), "top_urls": [item.url for item in results[:5]]},
            answer,
            evidence,
        )

    async def _answer_without_tool(
        self,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """不调用工具，只用已完成的前置子问题答案推理。"""

        context = RagContext(
            query=sub_question.question,
            docs=[],
            context_text=_format_previous_answers(previous_results) or "无前置子问题答案。",
        )
        answer = await self._generate_with_trace(
            query=f"请基于已有子问题答案回答：{sub_question.question}",
            context=context,
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.no_tool_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )
        return ({"reason": "no_tool_selected"}, answer, [])

    async def _synthesize_final_answer(
        self,
        plan: AgentTaskPlan,
        results: list[AgentTaskSubQuestionResult],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> str:
        """把所有子问题答案和证据整合成面向用户的最终回答。"""

        context = RagContext(
            query=plan.original_query,
            docs=[],
            context_text=_format_sub_question_results(results),
        )
        return await self._generate_with_trace(
            query=(
                f"请回答原始复杂问题：{plan.original_query}\n"
                f"最终目标：{plan.objective}\n"
                f"整合要求：{plan.final_synthesis_instruction}"
            ),
            context=context,
            langchain_config=(
                langchain_config_factory("final_synthesis")
                if langchain_config_factory is not None
                else None
            ),
        )

    async def _answer_from_tool_calls(
        self,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
        tool_calls: list[AgentTaskToolCallTrace],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> str:
        """用当前子问题的多轮工具结果生成最终子问题答案。"""

        context_text = "\n\n".join(
            json.dumps(call.model_dump(mode="json"), ensure_ascii=False)
            for call in tool_calls
        )
        previous = _format_previous_answers(previous_results)
        if previous:
            context_text = _append_text(context_text, previous, title="前置子问题答案")
        return await self._generate_with_trace(
            query=f"请综合这些工具结果回答子问题：{sub_question.question}",
            context=RagContext(
                query=sub_question.question,
                docs=[],
                context_text=context_text,
            ),
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.tool_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )

    async def execute(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """执行报告生成并保存到知识库的固定任务链路。"""

        if plan.task_kind != "knowledge_report_to_document":
            raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

        # 旧报告链路是固定三步：检索 -> 生成报告 -> 准备文档写入。
        plan.user_id = plan.user_id or user.user_id
        plan.status = AgentTaskPlanStatus.RUNNING
        self._task_plan_store.save(plan)

        try:
            # 第一步：用 planner 生成的 condensed source_query 做一次知识库检索。
            docs_step = _find_step(plan, "knowledge_retrieval")
            docs_step.status = AgentToolStepStatus.RUNNING
            self._task_plan_store.save(plan)
            docs = await retrieve_knowledge_docs(
                settings=self._settings,
                vector_retriever=self._vector_retriever,
                keyword_retriever=self._keyword_retriever,
                query=plan.source_query,
                mode=mode,  # type: ignore[arg-type]
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                filters=filters,
                pipeline_provider="rag_agent_task",
            )
            docs_step.status = AgentToolStepStatus.COMPLETED
            docs_step.output = {
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            }
            self._task_plan_store.save(plan)

            # 第二步：基于检索资料生成报告正文。正文来源在这里产生，不来自 planner。
            report_step = _find_step(plan, "summarize_report")
            report_step.status = AgentToolStepStatus.RUNNING
            self._task_plan_store.save(plan)
            context = build_rag_context(plan.source_query, docs)
            report_body = await self._generate_with_trace(
                query=f"请根据检索资料生成报告：{plan.report_title}",
                context=context,
                langchain_config=(
                    langchain_config_factory("report.summarize")
                    if langchain_config_factory is not None
                    else None
                ),
            )
            report_content = f"# {plan.report_title}\n\n{report_body.strip()}\n"
            report_step.status = AgentToolStepStatus.COMPLETED
            report_step.output = {
                "content": report_content,
                "content_length": len(report_content),
            }
            self._task_plan_store.save(plan)

            # 第三步：文档写入先 dry-run，再交给权限网关决定是否等待确认。
            await self._prepare_document_create_step(
                plan=plan,
                user=user,
                report_content=report_content,
            )
            self._task_plan_store.save(plan)
            return plan
        except Exception as exc:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = f"{type(exc).__name__}: {exc}"
            self._task_plan_store.save(plan)
            raise

    async def _prepare_document_create_step(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        report_content: str,
    ) -> None:
        """准备文档创建步骤：dry-run、权限裁决、必要时进入等待确认。"""

        step = _find_step(plan, "knowledge_document_create")
        step.status = AgentToolStepStatus.RUNNING
        action_request = KnowledgeDocumentActionRequest(
            operation=KnowledgeDocumentOperation.CREATE,
            target_path=plan.target_path,
            content=report_content,
            reason=f"AgentTaskPlan {plan.task_plan_id} 生成知识库报告",
            dry_run=True,
            expected_department_codes=_infer_departments_from_path(plan.target_path),
        )
        action_result = await self._document_management_service.plan_action(
            request=action_request,
            user=user,
        )
        # dry-run preview 是确认阶段重建真实写入请求的事实来源。
        # 这里还没有写文件，只生成 preview、风险等级和权限元数据。
        target_departments = list(
            action_result.preview.permission_metadata.get("allowed_departments", [])
            or []
        )
        requires_confirmation = _requires_confirmation(
            policy=self._settings.agent_tool_execution_policy,
            risk_level=action_result.preview.risk_level,
        ) or self._settings.agent_document_tools_dry_run_only
        context = AgentToolCallContext(
            tool_name=tool_name_for_document_operation(action_request.operation),
            operation=action_request.operation,
            risk_level=action_result.preview.risk_level,
            target_path=action_request.target_path,
            target_department_codes=target_departments,
            requires_confirmation=requires_confirmation,
            metadata={"source": "rag_agent.task_executor"},
        )
        decision = await self._tool_permission_service.authorize(user=user, context=context)
        await self._tool_audit_service.record_decision(
            user=user,
            context=context,
            decision=decision,
        )
        # 权限网关返回三类结果：拒绝、等待确认、允许执行；下面按终态分别写回 plan。
        if decision.action == AgentToolPermissionAction.DENY:
            # 权限拒绝是终态，不进入确认。
            step.status = AgentToolStepStatus.FAILED
            step.error = decision.reason
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = decision.reason
            return

        if decision.action in {
            AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            AgentToolPermissionAction.REQUIRE_CONFIRMATION,
        }:
            # 保存 dry-run 事实；用户确认后 confirm() 会重新鉴权再真实写入。
            step.status = AgentToolStepStatus.WAITING_CONFIRMATION
            step.requires_confirmation = True
            step.output = {
                "target_path": plan.target_path,
                "content": report_content,
                "action_request": action_request.model_dump(mode="json"),
                "preview": action_result.preview.model_dump(mode="json"),
                "permission_decision": decision.model_dump(mode="json"),
            }
            plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
            plan.final_output = {
                "target_path": plan.target_path,
                "status": plan.status.value,
                "confirm_endpoint": f"/agent/task-plans/{plan.task_plan_id}/confirm",
            }
            return

        if (
            self._settings.agent_tool_execution_policy == "risk_based"
            and not self._settings.agent_document_tools_dry_run_only
        ):
            # risk_based 且权限允许时可以直接执行，其余策略统一等待确认。
            executed = await self._document_management_service.execute_confirmed_action(
                request=KnowledgeDocumentActionRequest(
                    **{**action_request.model_dump(), "dry_run": False},
                ),
                user=user,
            )
            step.status = AgentToolStepStatus.COMPLETED
            step.output = executed.model_dump(mode="json")
            plan.status = AgentTaskPlanStatus.COMPLETED
            plan.final_output = {"target_path": plan.target_path, "executed": True}
            return

        step.status = AgentToolStepStatus.WAITING_CONFIRMATION
        step.requires_confirmation = True
        step.output = {
            "target_path": plan.target_path,
            "content": report_content,
            "action_request": action_request.model_dump(mode="json"),
            "preview": action_result.preview.model_dump(mode="json"),
            "permission_decision": decision.model_dump(mode="json"),
        }
        plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
        plan.final_output = {
            "target_path": plan.target_path,
            "status": plan.status.value,
            "confirm_endpoint": f"/agent/task-plans/{plan.task_plan_id}/confirm",
        }

    async def confirm(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """用户确认 TaskPlan 后的统一入口。

        question_decomposition 在确认后开始执行子问题；
        knowledge_report_to_document 在确认后执行 dry-run 中冻结的文档写入。
        """

        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能确认自己创建的 Agent task plan")
        if plan.status != AgentTaskPlanStatus.WAITING_CONFIRMATION:
            raise AppServiceError("Agent task plan 状态不是 waiting_confirmation，拒绝执行")

        if plan.task_kind == "question_decomposition":
            # 复杂问题拆解计划：确认的是“开始执行这个计划”，不是写入文件。
            return await self.execute_question_decomposition_plan(
                plan=plan,
                user=user,
                mode="hybrid",
                top_k=self._settings.rag_default_top_k,
                candidate_k=None,
                min_score=self._settings.rag_default_min_score,
                filters=RetrievalFilters(
                    user_id=user.user_id,
                    department_codes=user.department_codes,
                    can_read_all="knowledge:read_all" in user.permissions,
                    allow_public=True,
                ),
                langchain_config_factory=langchain_config_factory,
            )

        step = _find_step(plan, "knowledge_document_create")
        if step.status != AgentToolStepStatus.WAITING_CONFIRMATION:
            raise AppServiceError("文档创建步骤状态不是 waiting_confirmation，拒绝执行")

        action_payload = step.output.get("action_request")
        preview_payload = step.output.get("preview")
        if not isinstance(action_payload, dict) or not isinstance(preview_payload, dict):
            raise AppServiceError("Agent task plan 缺少确认执行所需的 dry-run 事实")

        # 确认阶段不信任旧裁决结果，必须用当前用户和当前权限重新鉴权。
        # 这样可以覆盖“用户权限在确认前发生变化”的场景。
        action_request = KnowledgeDocumentActionRequest.model_validate(
            {
                **action_payload,
                "dry_run": False,
            }
        )
        target_departments = list(
            preview_payload.get("permission_metadata", {}).get("allowed_departments", [])
            or []
        )
        context = AgentToolCallContext(
            tool_name=tool_name_for_document_operation(action_request.operation),
            operation=action_request.operation,
            risk_level=KnowledgeDocumentRiskLevel(preview_payload["risk_level"]),
            target_path=action_request.target_path,
            target_department_codes=target_departments,
            requires_confirmation=False,
            confirmation_text="confirmed",
            metadata={"source": "agent_task_plan.confirm", "task_plan_id": task_plan_id},
        )
        decision = await self._tool_permission_service.authorize(user=user, context=context)
        await self._tool_audit_service.record_decision(
            user=user,
            context=context,
            decision=decision,
        )
        if decision.action != AgentToolPermissionAction.EXECUTE_ALLOWED:
            raise ToolPermissionDeniedError(decision.reason)

        # expected_before_hash 防止确认到执行之间文件内容被别人改过。
        # 如果目标文件已变化，document_management_service 会拒绝基于旧 preview 写入。
        result = await self._document_management_service.execute_confirmed_action(
            request=action_request,
            user=user,
            expected_before_hash=preview_payload.get("before_hash"),
        )
        step.status = AgentToolStepStatus.COMPLETED
        step.requires_confirmation = False
        step.output = {
            **step.output,
            "execution_result": result.model_dump(mode="json"),
        }
        plan.status = AgentTaskPlanStatus.COMPLETED
        plan.final_output = {
            "target_path": plan.target_path,
            "status": plan.status.value,
            "executed": True,
        }

        # 日志记录 任务执行操作
        await self._tool_audit_service.record_execution(
            user=user,
            task_plan_id=plan.task_plan_id,
            tool_name=context.tool_name,
            executed=True,
            message=result.message,
        )
        self._task_plan_store.save(plan)
        return plan


def _find_step(plan: AgentTaskPlan, tool_name: str) -> AgentToolStep:
    """按工具名找到固定任务链路中的步骤。"""

    for step in plan.steps:
        if step.tool_name == tool_name:
            return step
    raise AppServiceError(f"Agent task plan 缺少步骤: {tool_name}")


def _infer_departments_from_path(target_path: str) -> list[str]:
    """用知识库路径第一段推断目标部门编码。"""

    first = target_path.replace("\\", "/").split("/", 1)[0].strip()
    return [first] if first else []


def _requires_confirmation(
    policy: str,
    risk_level: KnowledgeDocumentRiskLevel,
) -> bool:
    """根据执行策略和风险等级判断是否必须人工确认。"""

    if policy in {"confirmation_required", "dry_run_only"}:
        return True
    return risk_level in {
        KnowledgeDocumentRiskLevel.HIGH,
        KnowledgeDocumentRiskLevel.CRITICAL,
    }


def _build_tool_selection_messages(
    plan: AgentTaskPlan,
    sub_question: AgentTaskSubQuestion,
    previous_results: list[AgentTaskSubQuestionResult],
    tool_calls: list[AgentTaskToolCallTrace] | None = None,
) -> list[SystemMessage | HumanMessage]:
    """构造给【工具选择 LLM】 的上下文，只暴露当前子问题和已完成答案。"""

    tool_calls = tool_calls or []
    return [
        SystemMessage(content=TASK_TOOL_SELECTION_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "original_query": plan.original_query,
                    "objective": plan.objective,
                    "current_sub_question": sub_question.model_dump(mode="json"),
                    "current_tool_calls": [
                        item.model_dump(mode="json") for item in tool_calls
                    ],
                    "previous_answers": [
                        {
                            "sub_question_id": item.sub_question_id,
                            "question": item.question,
                            "answer": item.answer,
                            "status": item.status,
                        }
                        for item in previous_results
                    ],
                },
                ensure_ascii=False,
            )
        ),
    ]


def _validate_tool_selection(
    selection: dict[str, Any],
    tools: list[BaseTool],
) -> dict[str, Any]:
    """本地校验 LLM 工具选择，未知工具一律降级为 none。"""

    available = {tool.name for tool in tools}
    selected_tool = str(selection.get("selected_tool") or "none").strip()
    if selected_tool not in available and selected_tool != "none":
        return {"selected_tool": "none", "tool_input": {}}
    return {
        "selected_tool": selected_tool,
        "tool_input": _normalize_tool_input(selection.get("tool_input")),
        "reason": str(selection.get("reason") or ""),
    }


# 【URL 场景下的稳定性补丁】LLM tool calling 不稳定
# 有时模型看到 https://example.com，却选择 knowledge_retrieval 或 none。但这个场景最确定的动作其实是 fetch URL 正文
# Fetch MCP 的参数很机械
# mcp__fetch 需要 url 参数。URL 已经在子问题文本里，本地正则提取比再依赖 LLM 填参数更稳。
def _repair_fetch_tool_selection(
    selection: dict[str, Any],
    sub_question: AgentTaskSubQuestion,
    tools: list[BaseTool],
) -> dict[str, Any]:
    """【URL 场景下的稳定性补丁】判断拆解后的subquestion中是否包含明确的 URL，如果有则强制使用 Fetch MCP 工具读取网页正文"""

    if "mcp__fetch" not in {tool.name for tool in tools}:
        return selection

    # 提取question中的 URL，为空时，直接返回原始选择
    url = _extract_first_url(sub_question.question)
    if not url:
        return selection

    tool_input = _normalize_tool_input(selection.get("tool_input"))
    if selection.get("selected_tool") == "mcp__fetch":
        return {
            **selection,
            "tool_input": {"url": tool_input.get("url") or url, **tool_input},
        }

    return {
        "selected_tool": "mcp__fetch",
        "tool_input": {"url": url},
        "reason": "子问题包含明确 URL，使用 Fetch MCP 读取网页正文。",
    }


def _extract_first_url(text: str) -> str | None:
    """从子问题中提取第一个 http/https URL。"""

    match = re.search(r"https?://[^\s，。；、）)]+", text)
    return match.group(0) if match else None


def _normalize_tool_input(value: object) -> dict[str, Any]:
    """把非 dict 的 tool_input 收敛为空参数。"""

    if isinstance(value, dict):
        return value
    return {}


def _coerce_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """把 LLM 输出的整数参数限制在后端允许范围内。"""

    try:
        number = int(value) if value is not None else default
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _load_mcp_stdio_server_configs(raw_value: str) -> list[dict[str, Any]]:
    """解析 AGENT_TASK_MCP_STDIO_SERVERS_JSON。"""

    try:
        payload = json.loads(raw_value or "[]")
    except json.JSONDecodeError as exc:
        raise AppServiceError("AGENT_TASK_MCP_STDIO_SERVERS_JSON 不是合法 JSON") from exc
    if not isinstance(payload, list):
        raise AppServiceError("AGENT_TASK_MCP_STDIO_SERVERS_JSON 必须是数组")

    configs: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise AppServiceError("MCP stdio server 配置项必须是对象")
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            raise AppServiceError("MCP stdio server 缺少 command")
        args = item.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise AppServiceError("MCP stdio server args 必须是字符串数组")
        env = item.get("env")
        if env is not None and (
            not isinstance(env, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items())
        ):
            raise AppServiceError("MCP stdio server env 必须是字符串字典")
        allowed = item.get("allowed_tool_names", [])
        if not isinstance(allowed, list) or not all(isinstance(name, str) for name in allowed):
            raise AppServiceError("MCP stdio server allowed_tool_names 必须是字符串数组")
        configs.append(
            {
                "name": str(item.get("name") or command),
                "command": command,
                "args": args,
                "env": env,
                "allowed_tool_names": allowed,
            }
        )
    return configs


def _find_registered_tool(tool_name: str, tools: list[BaseTool]) -> BaseTool:
    """从白名单工具中按名称取工具，未知工具不执行。"""

    for tool in tools:
        if tool.name == tool_name:
            return tool
    raise AppServiceError(f"LLM 选择了未注册工具: {tool_name}")


def _collect_tool_call_evidence(
    tool_calls: list[AgentTaskToolCallTrace],
) -> list[dict[str, Any]]:
    """从多轮 tool call 输出中抽取 evidence。"""

    evidence: list[dict[str, Any]] = []
    for call in tool_calls:
        raw_evidence = call.tool_output.get("evidence")
        if isinstance(raw_evidence, list):
            evidence.extend(item for item in raw_evidence if isinstance(item, dict))
    return evidence


def _result_used_tools(result: AgentTaskSubQuestionResult) -> list[str]:
    """提取一个子问题实际使用过的工具。"""

    if result.tool_calls:
        return [
            item.tool_name
            for item in result.tool_calls
            if item.status == "completed" and item.tool_name and item.tool_name != "none"
        ]
    if result.selected_tool and result.selected_tool != "none":
        return [result.selected_tool]
    return []


def _doc_to_evidence(doc: RetrievedDoc) -> dict[str, Any]:
    """把检索结果压缩成可保存到 TaskPlan JSON 的证据摘要。"""

    return {
        "id": doc.id,
        "source": doc.source,
        "title": doc.title,
        "score": doc.score,
        "metadata": doc.metadata,
        "content_preview": build_content_preview(doc.content),
    }


def _format_previous_answers(results: list[AgentTaskSubQuestionResult]) -> str:
    """格式化已完成子问题答案，供后续子问题引用。"""

    lines: list[str] = []
    for result in results:
        if result.status != "completed":
            continue
        lines.append(f"[{result.sub_question_id}] {result.question}\n{result.answer}")
    return "\n\n".join(lines)


def _format_sub_question_results(results: list[AgentTaskSubQuestionResult]) -> str:
    """格式化全部子问题结果，供最终综合回答使用。"""

    lines: list[str] = []
    for result in results:
        lines.append(
            "\n".join(
                [
                    f"子问题 {result.sub_question_id}: {result.question}",
                    f"状态: {result.status}",
                    f"工具: {result.selected_tool}",
                    f"工具调用: {json.dumps([call.model_dump(mode='json') for call in result.tool_calls], ensure_ascii=False)}",
                    f"回答: {result.answer}",
                    f"证据: {json.dumps(result.evidence, ensure_ascii=False)}",
                    f"错误: {result.error or ''}",
                ]
            )
        )
    return "\n\n".join(lines)


def _append_text(base_text: str, extra_text: str, title: str) -> str:
    """把额外上下文附加到文本后。"""

    if not extra_text:
        return base_text
    return f"{base_text}\n\n【{title}】\n{extra_text}"


def _append_previous_answers(
    context: RagContext,
    previous_results: list[AgentTaskSubQuestionResult],
) -> RagContext:
    """在 RAG context 后附加前置答案，保持 docs 不变。"""

    previous = _format_previous_answers(previous_results)
    if not previous:
        return context
    return RagContext(
        query=context.query,
        docs=context.docs,
        context_text=f"{context.context_text}\n\n【前置子问题答案】\n{previous}",
    )


__all__ = ["AgentTaskExecutor", "AgentTaskPlanStore"]
