"""TaskPlan 的运行时执行器。

本文件包含两条互不混用的主线：
1. question_decomposition：确认后顺序执行子问题，允许只读工具调用，最后综合答案；
2. knowledge_document_management：LLM 通过原生 ToolCall 收集资料并生成 dry-run，
   停在 waiting_confirmation，只有 confirm() 才会触发真实文档写入。

这里负责流程编排、工具上下文和计划状态；路径安全、ACL、文件及 ES/Milvus
一致性由 KnowledgeDocumentManagementService 负责。
"""

from __future__ import annotations

import asyncio
import json
import re
from difflib import unified_diff
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fast_app.agents.mcp_agent_tools import build_mcp_agent_tools
from fast_app.agents.document_management_tools import (
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_READ_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    KnowledgeDocumentReplacement,
    build_knowledge_document_management_tools,
    build_knowledge_document_read_tool,
)
from fast_app.agents.mcp_client_boundary import McpStdioClientBoundary
from fast_app.agents.mcp_tool_contracts import McpStdioServerConfig
from fast_app.agents.rag_agent_tools import KNOWLEDGE_RETRIEVAL_TOOL_NAME
from fast_app.agents.rag_agent_tools import retrieve_knowledge_docs
from fast_app.agents.web_search_tools import (
    WEB_SEARCH_TOOL_NAME,
    WebSearchToolInput,
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
    PermissionCode,
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

# 同一轮只能并行彼此独立、不会修改共享业务状态的只读工具；是否允许由后端集合裁决，
# 不能只相信 LLM 声称这些调用互不依赖。
# 用于普通的 question_decomposition 任务，普通问题拆解链路允许并行的工具
PARALLEL_SAFE_TASK_TOOL_NAMES = {
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
}
# 用于 knowledge_document_management 任务。文档管理链路允许并行的工具。
# 其他操作文档的tool没有定义在这里，因为它们必须单独一轮串行执行。这里的 create/update/delete 虽然只是 dry-run，但会形成 TaskPlan step、进行冲突预占，并影响后续计划状态，所以不能和其他 ToolCall 混在同一个并行批次中。
PARALLEL_SAFE_DOCUMENT_TOOL_NAMES = {
    *PARALLEL_SAFE_TASK_TOOL_NAMES,
    KNOWLEDGE_DOCUMENT_READ_TOOL_NAME,
}


class AgentTaskToolSelectionPayload(BaseModel):
    """LLM 工具调用不可用时，用结构化 JSON 表达工具选择结果。"""

    selected_tool: str = Field(default="knowledge_retrieval")
    tool_input: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="")


class AgentTaskKnowledgeRetrievalToolInput(BaseModel):
    """传给 knowledge_retrieval 的最小参数 schema。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="用于检索知识库的 query")
    mode: str = Field(default="hybrid", description="vector / keyword / hybrid")
    top_k: int = Field(default=5, ge=1, le=20)


TASK_TOOL_SELECTION_PROMPT = """你是 Agent TaskPlan 的工具选择器。

你只负责为当前子问题选择一个或多个已绑定工具。
可用工具只来自 bound tools，不允许编造工具名。
同一轮可以选择多个彼此独立的只读工具；存在依赖时必须等待上一轮结果。
如果已有工具结果足够回答当前子问题，不再调用工具。
如果当前子问题可以只依赖已有子问题答案进行推理，可以不调用工具。
如果系统进入结构化输出模式，必须返回符合 schema 的 JSON 对象。

选择原则：
- 项目知识库、已有工程实现、内部文档相关问题，优先 knowledge_retrieval。
- 当前知识库可能没有、需要公开互联网或最新资料时，选择 web_search。
- 查询官方资料且已知官方域名时，把不含协议和路径的域名传入 web_search.site。
- 子问题中已经给出明确 URL，且存在 mcp__fetch 工具时，优先 mcp__fetch 读取网页正文。
- 综合性问题如果已有前置答案足够，可以不调用工具。
"""


DOCUMENT_AGENT_SYSTEM_PROMPT = """你是知识库文档管理 Agent。你必须通过绑定工具完成任务。

同一轮可以并行调用多个彼此独立的只读工具，并且必须等待本轮全部 ToolMessage 后再决定下一步。
- 有依赖的工具必须跨轮调用，不要在同一轮组合 retrieval→read 或 read→update。
- 文档 create/update/delete dry-run 和 MCP 工具每轮只能单独调用一个。
- create 可以先调用 knowledge_retrieval、web_search 或 MCP 收集资料，再调用 knowledge_document_create。
- 使用 web_search 查询官方资料且已知官方域名时，必须填写 site；site 不含协议和路径。
- update/delete 必须先调用 knowledge_retrieval 获得候选 doc_id。
- update 还必须调用 knowledge_document_read 读取完整原文，再一次性提交全部精确 replacements。
- 文档工具只生成 dry-run 计划，不会真实写入；不要声称已经执行。
- 同一文档只能提交一个写动作，不得同时 update/delete 或重复调用。

资料足够且所有文档 dry-run 动作已经提交后，直接返回简短说明，不再调用工具。
"""


class _DocumentActionConflictError(AppServiceError):
    """同一 TaskPlan 出现相互冲突的文档写动作。"""


class _TaskPlanCancelledError(AppServiceError):
    """当前轮次屏障检测到用户已经取消 TaskPlan。"""


_ACTIVE_DOCUMENT_TASK_PLAN_IDS: set[str] = set()


class AgentTaskPlanStore:
    """用 runtime JSON 文件保存 TaskPlan 的当前快照。"""

    def __init__(self, settings: Settings) -> None:
        self._task_plan_dir = Path(settings.agent_task_plan_dir)

    def save(self, plan: AgentTaskPlan) -> None:
        """新增或覆盖同一个 task_plan_id 对应的 JSON 文件。"""

        # JSON 是接口读取的事实快照；Markdown 是同一份事实的人类可读视图。
        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        plan.updated_at = datetime.now(UTC)
        path = self._path_for_new_plan(plan)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        path.with_suffix(".md").write_text(_render_task_plan_markdown(plan), encoding="utf-8")

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

    def load_markdown(self, task_plan_id: str) -> str:
        """读取面向人工审查的 Markdown；没有旧文件时按 JSON 现场渲染。"""

        plan = self.load(task_plan_id)
        matches = sorted(self._task_plan_dir.glob(f"*_{task_plan_id}.md"))
        if matches:
            return matches[-1].read_text(encoding="utf-8")
        return _render_task_plan_markdown(plan)

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
    - knowledge_document_management：原生 ToolCall 生成 dry-run，确认后真实写入。
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
        # Executor 只编排已有依赖，不自行创建数据库、检索器或权限服务，便于请求级依赖注入。
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

    def cancel(self, task_plan_id: str, user: CurrentUserContext) -> AgentTaskPlan:
        """取消尚未完成的 TaskPlan；运行中任务会在下一轮屏障停止。"""

        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能取消自己创建的 Agent task plan")
        if plan.status in {AgentTaskPlanStatus.COMPLETED, AgentTaskPlanStatus.CANCELLED}:
            raise AppServiceError("已完成或已取消的 Agent task plan 不能再次取消")
        plan.status = AgentTaskPlanStatus.CANCELLED
        plan.error = None
        for step in plan.steps:
            if step.status in {
                AgentToolStepStatus.PENDING,
                AgentToolStepStatus.RUNNING,
                AgentToolStepStatus.WAITING_CONFIRMATION,
            }:
                step.status = AgentToolStepStatus.SKIPPED
                step.requires_confirmation = False
                step.error = "TaskPlan 已由用户取消"
        plan.final_output.update(
            {
                "status": plan.status.value,
                "cancelled_at": datetime.now(UTC).isoformat(),
            }
        )
        self._task_plan_store.save(plan)
        return plan

    def _sync_cancelled_state(self, plan: AgentTaskPlan) -> bool:
        """把控制 API 写入的 cancelled 快照同步到当前执行对象。"""

        latest = self._task_plan_store.load(plan.task_plan_id)
        if latest.status != AgentTaskPlanStatus.CANCELLED:
            return False
        plan.status = latest.status
        plan.steps = latest.steps
        plan.final_output = {**plan.final_output, **latest.final_output}
        plan.error = None
        return True

    async def _generate_with_trace(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> str:
        """调用 LLM；兼容测试中仍使用旧签名的 fake client。"""

        try:
            # 真实 LangChain client 使用 langchain_config 透传 LangSmith 子 run 名称。
            answer = await self._llm_client.generate(
                query=query,
                context=context,
                langchain_config=langchain_config,
            )
            return _as_text(answer)
        except TypeError as exc:
            if "langchain_config" not in str(exc):
                raise
            answer = await self._llm_client.generate(query=query, context=context)
            return _as_text(answer)

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

        # 保存running状态快照
        self._task_plan_store.save(plan)

        results: list[AgentTaskSubQuestionResult] = []
        try:
            # sub_questions 是规划事实；执行结果单独写入 final_output，避免污染 plan。
            for sub_question in sorted(plan.sub_questions, key=lambda item: item.order):
                if self._sync_cancelled_state(plan):
                    self._task_plan_store.save(plan)
                    return plan
                # 开始执行子任务
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
                if self._sync_cancelled_state(plan):
                    self._task_plan_store.save(plan)
                    return plan
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
                # 保存一次已完成的子任务的 任务快照
                self._task_plan_store.save(plan)

            # 允许单个子问题失败，但不能在完全没有有效答案时继续综合。
            if not any(item.status == "completed" for item in results):
                raise AppServiceError("所有子问题都执行失败，无法整合最终答案")

            final_answer = await self._synthesize_final_answer(
                plan,
                results,
                langchain_config_factory=langchain_config_factory,
            )
            # 所有任务完成后，保存最终结果的 任务快照
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
        call_count = 0
        round_index = 0

        try:
            while call_count < max_tool_calls:
                round_index += 1
                # 让 LLM 基于原始问题、当前子问题、前置子问题答案、当前子问题已调用过的工具，
                # 判断下一步是否还需要工具；同一轮返回的只读工具可以并行执行。
                selected = await self._select_tool_for_sub_question(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=previous_results,
                    default_mode=mode,
                    default_top_k=top_k,
                    available_tools=available_tools,
                    tool_calls=tool_calls,
                    langchain_config_factory=langchain_config_factory,
                )
                selections = selected if isinstance(selected, list) else [selected]
                # 兼容 JSON fallback 的单个字典和原生 Tool Calling 的多个字典；
                # ``none`` 不是实际调用，过滤后为空即表示本轮不再需要工具。
                selections = [item for item in selections if isinstance(item, dict)]
                selections = [
                    item
                    for item in selections
                    if str(item.get("selected_tool") or "none") != "none"
                ]
                if not selections:
                    break

                batch_size = len(selections)
                # 一个批次中的每个 ToolCall 都计入总预算，即使该批次随后因不安全而被拒绝，
                # 也避免模型反复提交同一非法批次而无限消耗轮次。
                call_count += batch_size
                # 先整体校验再启动协程：未知工具、超额调用或含串行工具时，本轮一个也不执行。
                batch_error = _parallel_batch_error(
                    tool_names=[
                        str(item.get("selected_tool") or "") for item in selections
                    ],
                    registered_tool_names={tool.name for tool in available_tools},
                    parallel_safe_tool_names=PARALLEL_SAFE_TASK_TOOL_NAMES,
                    max_parallel_calls=self._settings.agent_max_parallel_tool_calls,
                    remaining_calls=max_tool_calls - (call_count - batch_size),
                )
                if batch_error:
                    # 被拒绝的调用仍写入 trace，供下一轮模型根据 ToolMessage/轨迹调整方案。
                    tool_calls.extend(
                        _failed_batch_traces(
                            selections=selections,
                            sub_question_id=sub_question.sub_question_id,
                            round_index=round_index,
                            error=batch_error,
                        )
                    )
                    continue

                async def run_selection(
                    selection: dict[str, Any],
                    index: int,
                ) -> AgentTaskToolCallTrace:
                    """负责执行“一个”问题拆解工具调用，并把成功或失败转换成一条 AgentTaskToolCallTrace"""

                    # 每个协程只返回自己的 trace，不并发修改外层 tool_calls，避免共享列表写入竞态。
                    selected_tool = str(selection.get("selected_tool") or "")
                    tool_input = _normalize_tool_input(selection.get("tool_input"))
                    call_id = str(
                        selection.get("call_id")
                        or f"{sub_question.sub_question_id}_tool_{round_index}_{index}"
                    )
                    reason = str(selection.get("reason") or "")
                    try:
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
                        return AgentTaskToolCallTrace(
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
                    except Exception as exc:
                        return AgentTaskToolCallTrace(
                            call_id=call_id,
                            round=round_index,
                            tool_name=selected_tool,
                            tool_input=tool_input,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                            reason=reason,
                        )

                # --------------------------------------------------开始普通任务 并行tool 执行--------------------------------------------------
                # 校验通过的只读调用同时开始；gather 按输入顺序返回，即使工具完成先后不同，
                tool_calls.extend(
                    await asyncio.gather(
                        *(
                            run_selection(selection, index)
                            for index, selection in enumerate(selections, start=1)
                        )
                    )
                )

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
    ) -> list[dict[str, Any]]:
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
            return []

        if self._settings.openai_api_key:
            # 获取 llm 根据子问题 选择要使用的tool
            selections = await self._select_tool_with_bound_tools(
                tools=available_tools,
                plan=plan,
                sub_question=sub_question,
                previous_results=previous_results,
                tool_calls=tool_calls,
                langchain_config_factory=langchain_config_factory,
            )
            if selections is None:
                selection = await self._select_tool_with_json(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=previous_results,
                    tool_calls=tool_calls,
                    langchain_config_factory=langchain_config_factory,
                )
                selections = [selection] if selection is not None else None

            # 当前模型明确需要调用tool，判断question里面有没有包含明确的url，如果有，强制绑定 mcp__fetch 调用
            # 避免 子问题里已经有明确 URL ，但 LLM 没有选 fetch，或者选了 fetch 但没把 url 参数填好
            if selections is not None:
                validated = [
                    _validate_tool_selection(selection, available_tools)
                    for selection in selections
                    if isinstance(selection, dict)
                ]
                if not tool_calls and _extract_first_url(sub_question.question):
                    return [
                        _repair_fetch_tool_selection(
                            selection={"selected_tool": "none", "tool_input": {}},
                            sub_question=sub_question,
                            tools=available_tools,
                        )
                    ]
                return validated

        # LLM 不可用时的兜底，不作为正常企业场景的主判断器。
        if tool_calls:
            return []
        fallback_tool = sub_question.information_source_hint
        if fallback_tool not in {tool.name for tool in available_tools}:
            fallback_tool = KNOWLEDGE_RETRIEVAL_TOOL_NAME
        return [
            _repair_fetch_tool_selection(
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
        ]

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
            async def web_search(
                query: str,
                count: int = 5,
                site: str | None = None,
            ) -> str:
                # 同上：这里只参与 LLM tool calling，不直接承载业务执行。
                return ""

            tools.append(
                StructuredTool.from_function(
                    coroutine=web_search,
                    name=WEB_SEARCH_TOOL_NAME,
                    description="搜索公开互联网；查询官方资料时应在 site 中传入已知官方域名。",
                    args_schema=WebSearchToolInput,
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
    ) -> list[dict[str, Any]] | None:
        """返回 LLM 本轮选择的全部原生 ToolCall。"""

        try:
            model = ChatOpenAI(
                model=self._settings.llm_model_name,
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                temperature=0.0,
            ).bind_tools(tools, parallel_tool_calls=True)
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
            return []

        return [
            {
                "call_id": call.get("id"),
                "selected_tool": call.get("name"),
                "tool_input": call.get("args") or {},
            }
            for call in tool_calls
            if isinstance(call, dict)
        ]

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
        site = str(tool_input.get("site") or "").strip() or None
        async with httpx.AsyncClient() as http_client:
            results = await search_web_with_bocha(
                settings=self._settings,
                http_client=http_client,
                query=query,
                count=count,
                site=site,
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
        answer = await self._generate_with_trace(
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
        return answer.strip() or _fallback_final_answer(plan, results)

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
        """运行原生文档 Tool loop，并停在人工确认前。"""

        # 文档任务不能复用问题拆解执行器：前者要冻结可确认的写操作，后者只生成答案。
        if plan.task_kind != "knowledge_document_management":
            raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")
        return await self._execute_document_tool_loop(
            plan=plan,
            user=user,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            filters=filters,
            langchain_config_factory=langchain_config_factory,
        )

    async def resume(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """从最近完整轮次继续确认前的文档 Tool Loop。"""

        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能恢复自己创建的 Agent task plan")
        if plan.task_kind != "knowledge_document_management":
            raise AppServiceError("当前只支持恢复文档管理 Tool Loop")
        if plan.status not in {AgentTaskPlanStatus.RUNNING, AgentTaskPlanStatus.FAILED}:
            raise AppServiceError("只有 running 或 failed 的文档 TaskPlan 可以恢复")
        checkpoint = plan.final_output.get("checkpoint")
        if not isinstance(checkpoint, dict) or checkpoint.get("completed") is True:
            raise AppServiceError("Agent task plan 没有可恢复的轮次检查点")
        if task_plan_id in _ACTIVE_DOCUMENT_TASK_PLAN_IDS:
            raise AppServiceError("Agent task plan 当前仍在执行，不能重复恢复")
        # ponytail: runtime 文件快照没有跨进程租约；部署多 worker 时升级为 PostgreSQL lease。
        return await self._execute_document_tool_loop(
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
            resume=True,
        )

    async def _execute_document_tool_loop(
        self,
        *,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None,
        resume: bool = False,
    ) -> AgentTaskPlan:
        """执行支持安全只读并行、多轮 ToolMessage 的文档 Agent，产出待确认步骤。"""

        if not self._settings.openai_api_key:
            raise AppServiceError("文档管理任务需要配置 LLM 原生 Tool Calling")

        plan.user_id = plan.user_id or user.user_id
        checkpoint = plan.final_output.get("checkpoint") if resume else None
        if resume:
            if not isinstance(checkpoint, dict):
                raise AppServiceError("文档 TaskPlan 缺少可恢复检查点")
            try:
                candidates = {
                    str(key): dict(value)
                    for key, value in dict(checkpoint.get("candidates") or {}).items()
                }
                read_doc_ids = {str(item) for item in checkpoint.get("read_doc_ids", [])}
                document_actions = {
                    str(key): str(value)
                    for key, value in dict(
                        checkpoint.get("document_actions") or {}
                    ).items()
                }
                messages = list(messages_from_dict(checkpoint.get("messages") or []))
                traces = [
                    AgentTaskToolCallTrace.model_validate(item)
                    for item in plan.final_output.get("tool_calls", [])
                ]
                call_count = int(checkpoint.get("call_count", 0))
                round_index = int(checkpoint.get("round", 0))
            except (TypeError, ValueError, ValidationError) as exc:
                raise AppServiceError("文档 TaskPlan 检查点结构无效") from exc
            if len(messages) < 2:
                raise AppServiceError("文档 TaskPlan 检查点缺少模型消息")
            plan.status = AgentTaskPlanStatus.RUNNING
            plan.error = None
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
        else:
            plan.status = AgentTaskPlanStatus.RUNNING
            plan.steps = []
            plan.final_output = {"tool_calls": [], "used_tools": []}
            # 这三个集合是一次 Agent loop 的服务端事实，不交给模型维护：
            # candidates 限定 update/delete 可选 doc_id；read_doc_ids 强制 update 先读原文；
            # document_actions 防止同一文档出现重复 update、update+delete 等冲突动作。
            candidates: dict[str, dict[str, Any]] = {}
            read_doc_ids: set[str] = set()
            document_actions: dict[str, str] = {}
            messages: list[object] = [
                SystemMessage(content=DOCUMENT_AGENT_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "original_query": plan.original_query,
                            "objective": plan.objective,
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
            traces: list[AgentTaskToolCallTrace] = []
            call_count = 0
            round_index = 0
            self._task_plan_store.save(plan)
        tools = await self._build_document_agent_tools(
            plan=plan,
            user=user,
            default_mode=mode,
            default_top_k=top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            filters=filters,
            candidates=candidates,
            read_doc_ids=read_doc_ids,
            document_actions=document_actions,
        )
        tools_by_name = {tool.name: tool for tool in tools}
        # 模型可以同轮返回多个调用；后端仍按白名单和轮次开始时的状态强制校验。
        model = ChatOpenAI(
            model=self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.0,
        ).bind_tools(tools, parallel_tool_calls=True)
        max_calls = max(self._settings.agent_max_tool_calls, 0)
        if call_count >= max_calls:
            raise AppServiceError("文档 Agent 已达到最大工具调用次数")
        self._save_document_tool_progress(
            plan,
            traces,
            round_index=round_index,
            call_count=call_count,
            messages=messages,
            candidates=candidates,
            read_doc_ids=read_doc_ids,
            document_actions=document_actions,
        )

        if plan.task_plan_id in _ACTIVE_DOCUMENT_TASK_PLAN_IDS:
            raise AppServiceError("Agent task plan 当前仍在执行")
        _ACTIVE_DOCUMENT_TASK_PLAN_IDS.add(plan.task_plan_id)
        try:
            while True:
                # 每轮上下文都包含此前 AIMessage 和 ToolMessage，因此依赖工具必须跨轮顺序产生。
                round_index += 1
                response = await model.ainvoke(
                    messages,
                    config=(
                        langchain_config_factory(
                            f"document.tool_loop.round_{round_index}.model"
                        )
                        if langchain_config_factory is not None
                        else None
                    ),
                )
                messages.append(response)
                raw_calls = getattr(response, "tool_calls", None) or []
                invalid_calls = getattr(response, "invalid_tool_calls", None) or []
                if invalid_calls:
                    # 同轮只要存在无法解析的调用，就拒绝该轮全部调用；错误 ToolMessage 会让模型下一轮修正。
                    call_count += len(invalid_calls) + len(raw_calls)
                    for invalid_call in invalid_calls:
                        call = invalid_call if isinstance(invalid_call, dict) else {}
                        call_id = str(call.get("id") or f"invalid_{round_index}")
                        tool_name = str(call.get("name") or "unknown")
                        error = str(call.get("error") or "ToolCall 参数不是合法结构")
                        messages.append(
                            ToolMessage(
                                content=error,
                                tool_call_id=call_id,
                                name=tool_name,
                                status="error",
                            )
                        )
                        traces.append(
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=tool_name,
                                status="failed",
                                error=error,
                            )
                        )
                    for raw_call in raw_calls:
                        call = raw_call if isinstance(raw_call, dict) else {}
                        call_id = str(call.get("id") or f"invalid_{round_index}")
                        tool_name = str(call.get("name") or "unknown")
                        error = "同一轮包含非法 ToolCall，本轮所有调用均不执行"
                        messages.append(
                            ToolMessage(
                                content=error,
                                tool_call_id=call_id,
                                name=tool_name,
                                status="error",
                            )
                        )
                        traces.append(
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=tool_name,
                                tool_input=_normalize_tool_input(call.get("args")),
                                status="failed",
                                error=error,
                            )
                        )
                    self._save_document_tool_progress(
                        plan,
                        traces,
                        round_index=round_index,
                        call_count=call_count,
                        messages=messages,
                        candidates=candidates,
                        read_doc_ids=read_doc_ids,
                        document_actions=document_actions,
                    )
                    if call_count >= max_calls:
                        raise AppServiceError("文档 Agent 已达到最大工具调用次数")
                    continue
                if not raw_calls:
                    # 没有 ToolCall 表示模型认为工作已结束；循环外仍会校验至少生成一个文档 dry-run。
                    break

                calls = [call if isinstance(call, dict) else {} for call in raw_calls]
                batch_size = len(calls)
                # 先记录本轮开始时还可用的总预算；当前批次无论执行或拒绝都消耗 batch_size。
                remaining_calls = max_calls - call_count
                call_count += batch_size

                # 判断目前模型选择的多个并行工具 能不能允许 并行执行
                # 如果不行，返回error实例
                batch_error = _parallel_batch_error(
                    tool_names=[str(call.get("name") or "") for call in calls],
                    registered_tool_names=set(tools_by_name),
                    parallel_safe_tool_names=PARALLEL_SAFE_DOCUMENT_TOOL_NAMES,
                    max_parallel_calls=self._settings.agent_max_parallel_tool_calls,
                    remaining_calls=remaining_calls,
                ) or _document_batch_dependency_error( # 校验工具之间是否存在依赖关系
                    calls=calls,
                    candidates=set(candidates), # set(candidates)：哪些文档已经被检索确认过，存此前 knowledge_retrieval 找到的候选文档及其 metadata。
                    read_doc_ids=set(read_doc_ids), # set(read_doc_ids)：哪些候选文档已经读过完整原文；表示此前已经执行过：knowledge_document_read(doc_001)
                )
                if batch_error:
                    # 整批拒绝但为每个原生 ToolCall 补一条失败 ToolMessage，模型下一轮可据此改正。
                    for index, call in enumerate(calls, start=1):
                        call_id = str(call.get("id") or f"invalid_{round_index}_{index}")
                        tool_name = str(call.get("name") or "unknown")
                        tool_input = _normalize_tool_input(call.get("args"))
                        messages.append(
                            ToolMessage(
                                content=batch_error,
                                tool_call_id=call_id,
                                name=tool_name,
                                status="error",
                            )
                        )
                        traces.append(
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=tool_name,
                                tool_input=tool_input,
                                status="failed",
                                error=batch_error,
                            )
                        )
                    self._save_document_tool_progress(
                        plan,
                        traces,
                        round_index=round_index,
                        call_count=call_count,
                        messages=messages,
                        candidates=candidates,
                        read_doc_ids=read_doc_ids,
                        document_actions=document_actions,
                    )
                    if call_count >= max_calls:
                        raise AppServiceError("文档 Agent 已达到最大工具调用次数")
                    continue

                async def run_call(
                    call: dict[str, Any],
                    index: int,
                ) -> tuple[ToolMessage, AgentTaskToolCallTrace, dict[str, Any] | None]:
                    """负责 文档管理任务的并行 tool； 只有批次校验已经确认的并行安全工具会走到这里。"""

                    call_id = str(call.get("id") or f"tool_{round_index}_{index}")
                    tool_name = str(call.get("name") or "")
                    tool_input = _normalize_tool_input(call.get("args"))
                    tool = tools_by_name[tool_name]
                    try:
                        tool_message = await tool.ainvoke(
                            call,
                            config=(
                                langchain_config_factory(
                                    f"document.tool_loop.round_{round_index}.{tool_name}.{call_id}"
                                )
                                if langchain_config_factory is not None
                                else None
                            ),
                        )
                        if not isinstance(tool_message, ToolMessage):
                            raise AppServiceError("文档工具未返回 ToolMessage")
                        output = _parse_tool_message_content(tool_message.content)
                        return (
                            tool_message,
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=tool_name,
                                tool_input=tool_input,
                                tool_output=output,
                                status="completed",
                            ),
                            output,
                        )
                    except (_DocumentActionConflictError, ToolPermissionDeniedError):
                        raise
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        return (
                            ToolMessage(
                                content=error,
                                tool_call_id=call_id,
                                name=tool_name,
                                status="error",
                            ),
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=tool_name,
                                tool_input=tool_input,
                                status="failed",
                                error=error,
                            ),
                            None,
                        )

                # --------------------------文档管理任务的并行tool位置--------------------------

                # 并行执行整批独立只读调用；return_exceptions=True 让冲突/权限这类终态错误
                # 在所有已启动协程结束后集中处理，而普通工具错误已在 run_call 中转为 ToolMessage。
                batch_results = await asyncio.gather(
                    *(run_call(call, index) for index, call in enumerate(calls, start=1)),
                    return_exceptions=True,
                )
                for result in batch_results:
                    if isinstance(result, BaseException):
                        raise result
                    tool_message, trace, output = result
                    messages.append(tool_message)
                    traces.append(trace)
                    if output is not None and trace.tool_name in {
                        KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
                        KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
                        KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
                    }:
                        plan.steps.append(
                            _document_step_from_tool_result(
                                call_id=trace.call_id,
                                tool_name=trace.tool_name,
                                tool_input=trace.tool_input,
                                output=output,
                                index=len(plan.steps) + 1,
                            )
                        )
                # 所有同批结果先汇总，再保存进度；这些新状态只会在下一轮成为可依赖的事实。
                self._save_document_tool_progress(
                    plan,
                    traces,
                    round_index=round_index,
                    call_count=call_count,
                    messages=messages,
                    candidates=candidates,
                    read_doc_ids=read_doc_ids,
                    document_actions=document_actions,
                )

            if not plan.steps:
                raise AppServiceError("LLM 未调用任何文档 dry-run 工具")
            # 到这里仍没有真实写入；TaskPlan 保存了用户确认时需要看到的全部冻结事实。
            plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
            plan.final_output.update(
                {
                    "status": plan.status.value,
                    "confirm_endpoint": f"/agent/task-plans/{plan.task_plan_id}/confirm",
                    "document_action_count": len(plan.steps),
                }
            )
            plan.final_output["checkpoint"]["completed"] = True
            self._task_plan_store.save(plan)
            return plan
        except _TaskPlanCancelledError:
            plan.status = AgentTaskPlanStatus.CANCELLED
            plan.error = None
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
            return plan
        except asyncio.CancelledError:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = "AgentTaskInterrupted: 文档 Agent 在完整轮次边界外中断"
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
            raise
        except Exception as exc:
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = f"{type(exc).__name__}: {exc}"
            plan.final_output["status"] = plan.status.value
            self._task_plan_store.save(plan)
            raise
        finally:
            _ACTIVE_DOCUMENT_TASK_PLAN_IDS.discard(plan.task_plan_id)

    def _save_document_tool_progress(
        self,
        plan: AgentTaskPlan,
        traces: list[AgentTaskToolCallTrace],
        *,
        round_index: int,
        call_count: int,
        messages: list[object],
        candidates: dict[str, dict[str, Any]],
        read_doc_ids: set[str],
        document_actions: dict[str, str],
    ) -> None:
        """将每轮原生工具轨迹写回 TaskPlan，供 SSE、页面和 LangSmith 对照查看。"""

        if self._sync_cancelled_state(plan):
            raise _TaskPlanCancelledError("Agent task plan 已取消")
        plan.final_output["tool_calls"] = [
            item.model_dump(mode="json") for item in traces
        ]
        plan.final_output["used_tools"] = list(
            dict.fromkeys(
                item.tool_name for item in traces if item.status == "completed"
            )
        )
        plan.final_output["checkpoint"] = {
            "version": 1,
            "round": round_index,
            "call_count": call_count,
            "messages": messages_to_dict(messages),
            "candidates": candidates,
            "read_doc_ids": sorted(read_doc_ids),
            "document_actions": document_actions,
            "completed": False,
        }
        self._task_plan_store.save(plan)

    async def _build_document_agent_tools(
        self,
        *,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        default_mode: str,
        default_top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        candidates: dict[str, dict[str, Any]],
        read_doc_ids: set[str],
        document_actions: dict[str, str],
    ) -> list[BaseTool]:
        """构造文档 Agent 的真实只读工具和只生成预览的写工具。"""

        # 闭包共享本轮候选和读取状态，使安全约束由后端状态保证，而不是依赖 Prompt 自觉。
        async def knowledge_retrieval(
            query: str,
            mode: str = default_mode,
            top_k: int = default_top_k,
        ) -> str:
            docs = await retrieve_knowledge_docs(
                settings=self._settings,
                vector_retriever=self._vector_retriever,
                keyword_retriever=self._keyword_retriever,
                query=query,
                mode=mode,  # type: ignore[arg-type]
                top_k=top_k,
                candidate_k=candidate_k,
                min_score=min_score,
                filters=filters,
                pipeline_provider="rag_agent_document_tool",
            )
            found = _document_candidates(docs)
            # 多轮检索结果按 doc_id 累积；后续 read/update/delete 只能从这个映射取目标。
            candidates.update({item["doc_id"]: item for item in found})
            return json.dumps(
                {
                    "candidates": found,
                    "evidence": [_doc_to_evidence(doc) for doc in docs],
                },
                ensure_ascii=False,
            )

        async def read_document(doc_id: str) -> str:
            # 候选校验先于文件读取，防止模型用猜测的 doc_id/path 读取任意知识库文档。
            candidate = _require_document_candidate(doc_id, candidates)
            content = self._document_management_service.read_document_content(
                candidate["source_path"]
            )
            read_doc_ids.add(doc_id)
            return json.dumps(
                {
                    "doc_id": doc_id,
                    "source_path": candidate["source_path"],
                    "content": content,
                },
                ensure_ascii=False,
            )

        async def create_document(filename: str, content: str, reason: str) -> str:
            # LLM 只建议文件名；后端会把它收敛到当前用户可管理的默认目录。
            target_path = _create_target_path(filename, user, plan.task_plan_id)
            return await self._prepare_document_dry_run(
                user=user,
                operation=KnowledgeDocumentOperation.CREATE,
                target_path=target_path,
                content=content,
                reason=reason,
                candidate=None,
                selection_reason="用户要求创建新文档",
                replacements=[],
                document_actions=document_actions,
            )

        async def update_document(
            doc_id: str,
            replacements: list[KnowledgeDocumentReplacement],
            reason: str,
            selection_reason: str,
        ) -> str:
            candidate = _require_document_candidate(doc_id, candidates)
            # update 必须基于本轮刚读取的完整原文，不能只根据检索摘要自由重写。
            if doc_id not in read_doc_ids:
                raise AppServiceError("update 前必须先调用 knowledge_document_read")
            before = self._document_management_service.read_document_content(
                candidate["source_path"]
            )
            after = _apply_unique_replacements(before, replacements)
            # diff 是确认页面的审查材料；真正执行仍使用确定性替换后的完整 content。
            diff = "\n".join(
                unified_diff(
                    before.splitlines(),
                    after.splitlines(),
                    fromfile=candidate["source_path"],
                    tofile=candidate["source_path"],
                    lineterm="",
                )
            )
            return await self._prepare_document_dry_run(
                user=user,
                operation=KnowledgeDocumentOperation.UPDATE,
                target_path=candidate["source_path"],
                content=after,
                reason=reason,
                candidate=candidate,
                selection_reason=selection_reason,
                replacements=[item.model_dump(mode="json") for item in replacements],
                document_actions=document_actions,
                diff=diff,
            )

        async def delete_document(
            doc_id: str,
            reason: str,
            selection_reason: str,
        ) -> str:
            # delete 同样只能选择权限过滤后的候选；工具参数中没有自由 target_path。
            candidate = _require_document_candidate(doc_id, candidates)
            return await self._prepare_document_dry_run(
                user=user,
                operation=KnowledgeDocumentOperation.DELETE,
                target_path=candidate["source_path"],
                content=None,
                reason=reason,
                candidate=candidate,
                selection_reason=selection_reason,
                replacements=[],
                document_actions=document_actions,
            )

        tools: list[BaseTool] = [
            StructuredTool.from_function(
                coroutine=knowledge_retrieval,
                name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                description=(
                    "检索当前用户有权读取的知识库资料，并返回可用于 update/delete 的候选 doc_id。"
                ),
                args_schema=AgentTaskKnowledgeRetrievalToolInput,
            ),
            build_knowledge_document_read_tool(read_document),
            *build_knowledge_document_management_tools(
                create=create_document,
                update=update_document,
                delete=delete_document,
            ),
        ]
        # 外部资料工具只有在服务已配置且当前用户有权限时才暴露给模型。
        if self._settings.bocha_api_key and _user_has_permission(
            user,
            PermissionCode.AGENT_TOOL_WEB_SEARCH,
        ):
            async def web_search(
                query: str,
                count: int = 5,
                site: str | None = None,
            ) -> str:
                async with httpx.AsyncClient() as http_client:
                    results = await search_web_with_bocha(
                        settings=self._settings,
                        http_client=http_client,
                        query=query,
                        count=count,
                        site=site,
                    )
                return json.dumps(
                    [item.model_dump(mode="json") for item in results],
                    ensure_ascii=False,
                )

            tools.append(
                StructuredTool.from_function(
                    coroutine=web_search,
                    name=WEB_SEARCH_TOOL_NAME,
                    description="搜索公开互联网；查询官方资料时应在 site 中传入已知官方域名。",
                    args_schema=WebSearchToolInput,
                )
            )
        if _user_has_permission(user, PermissionCode.AGENT_TOOL_MCP):
            tools.extend(await self._build_mcp_task_tools())
        return tools

    async def _prepare_document_dry_run(
        self,
        *,
        user: CurrentUserContext,
        operation: KnowledgeDocumentOperation,
        target_path: str,
        content: str | None,
        reason: str,
        candidate: dict[str, Any] | None,
        selection_reason: str,
        replacements: list[dict[str, Any]],
        document_actions: dict[str, str],
        diff: str = "",
    ) -> str:
        """校验一个写动作并返回可冻结进 TaskPlan 的 dry-run ToolMessage 内容。"""

        # LLM 工具 schema 不包含 ACL、dry_run 或执行开关；这些安全字段只能由后端补齐。
        request = KnowledgeDocumentActionRequest(
            operation=operation,
            target_path=target_path,
            content=content,
            reason=reason,
            dry_run=True,
            expected_department_codes=(
                [user.primary_department_code]
                if operation == KnowledgeDocumentOperation.CREATE
                and user.primary_department_code
                else []
            ),
        )
        result = await self._document_management_service.plan_action(request, user=user)
        preview = result.preview
        doc_id = str(preview.affected_doc_id or "")
        if not doc_id:
            raise AppServiceError("文档 dry-run 未返回 doc_id")
        previous = document_actions.get(doc_id)
        # 以最终 preview 的 doc_id 判冲突，而不是相信 LLM 提供的路径或候选描述。
        if previous is not None:
            raise _DocumentActionConflictError(
                f"同一文档不能重复或冲突操作: doc_id={doc_id}, {previous}+{operation.value}"
            )
        context = AgentToolCallContext(
            tool_name=f"knowledge_document_{operation.value}",
            operation=operation,
            risk_level=preview.risk_level,
            target_path=target_path,
            target_department_codes=list(
                preview.permission_metadata.get("allowed_departments", []) or []
            ),
            requires_confirmation=True,
            metadata={"source": "rag_agent.document_native_tool"},
        )
        decision = await self._tool_permission_service.authorize(user=user, context=context)
        # dry-run 也记录权限决策，便于审计“谁尝试规划了什么高风险操作”。
        await self._tool_audit_service.record_decision(
            user=user,
            context=context,
            decision=decision,
        )
        if decision.action == AgentToolPermissionAction.DENY:
            raise ToolPermissionDeniedError(decision.reason)
        document_actions[doc_id] = operation.value
        # 返回值会成为 ToolMessage，并在成功后转换为 WAITING_CONFIRMATION step。
        return json.dumps(
            {
                "operation": operation.value,
                "target_path": target_path,
                "action_request": request.model_dump(mode="json"),
                "preview": preview.model_dump(mode="json"),
                "permission_decision": decision.model_dump(mode="json"),
                "candidate": candidate,
                "selection_reason": selection_reason,
                "replacements": replacements,
                "diff": diff,
            },
            ensure_ascii=False,
        )

    async def confirm(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """用户确认 TaskPlan 后的统一入口。

        question_decomposition 在确认后开始执行子问题；文档任务执行冻结的 dry-run。
        """

        plan = self._task_plan_store.load(task_plan_id)
        # 管理员可代为确认；普通用户只能确认自己创建且仍等待确认的计划。
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

        if plan.task_kind == "knowledge_document_management":
            return await self._confirm_document_management_plan(
                plan=plan,
                user=user,
            )

        raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

    async def _confirm_document_management_plan(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
    ) -> AgentTaskPlan:
        """重新鉴权全部文档步骤，再交给 service 做整批执行和补偿。"""

        actions: list[tuple[KnowledgeDocumentActionRequest, str | None]] = []
        contexts: list[AgentToolCallContext] = []
        try:
            # 先完成整批事实解析和二次鉴权，任何一步失败都不会调用真实写入 Service。
            for step in plan.steps:
                if step.status != AgentToolStepStatus.WAITING_CONFIRMATION:
                    raise AppServiceError("文档管理步骤状态不是 waiting_confirmation")
                action_payload = step.output.get("action_request")
                preview_payload = step.output.get("preview")
                if not isinstance(action_payload, dict) or not isinstance(
                    preview_payload, dict
                ):
                    raise AppServiceError("文档管理步骤缺少 dry-run 事实")
                request = KnowledgeDocumentActionRequest.model_validate(
                    # dry-run 标志不沿用模型结果；只有 confirm 路径能在本地改为 False。
                    {**action_payload, "dry_run": False}
                )
                target_departments = list(
                    preview_payload.get("permission_metadata", {}).get(
                        "allowed_departments", []
                    )
                    or []
                )
                context = AgentToolCallContext(
                    tool_name=step.tool_name,
                    operation=request.operation,
                    risk_level=KnowledgeDocumentRiskLevel(
                        preview_payload["risk_level"]
                    ),
                    target_path=request.target_path,
                    target_department_codes=target_departments,
                    requires_confirmation=False,
                    confirmation_text="confirmed",
                    metadata={
                        "source": "agent_task_plan.confirm",
                        "task_plan_id": plan.task_plan_id,
                    },
                )
                decision = await self._tool_permission_service.authorize(
                    user=user,
                    context=context,
                )
                await self._tool_audit_service.record_decision(
                    user=user,
                    context=context,
                    decision=decision,
                )
                if decision.action != AgentToolPermissionAction.EXECUTE_ALLOWED:
                    raise ToolPermissionDeniedError(decision.reason)
                # before_hash 把确认页面看到的旧版本带入 Service，执行前会再次比较。
                actions.append((request, preview_payload.get("before_hash")))
                contexts.append(context)

            results = await self._document_management_service.execute_confirmed_actions(
                actions=actions,
                user=user,
            )
            for step, result, context in zip(
                plan.steps, results, contexts, strict=True
            ):
                # Service 整批成功后才统一把步骤标记完成，避免页面看到部分成功状态。
                step.status = AgentToolStepStatus.COMPLETED
                step.requires_confirmation = False
                step.output["execution_result"] = result.model_dump(mode="json")
                await self._tool_audit_service.record_execution(
                    user=user,
                    task_plan_id=plan.task_plan_id,
                    tool_name=context.tool_name,
                    executed=True,
                    message=result.message,
                )
            plan.status = AgentTaskPlanStatus.COMPLETED
            plan.final_output = {
                **plan.final_output,
                "status": plan.status.value,
                "executed": True,
                "document_action_count": len(results),
                "affected_doc_ids": [
                    result.preview.affected_doc_id for result in results
                ],
            }
            self._task_plan_store.save(plan)
            return plan
        except Exception as exc:
            # Service 会负责数据补偿；Executor 只持久化计划失败状态和可展示的回滚摘要。
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = f"{type(exc).__name__}: {exc}"
            plan.final_output = {
                **plan.final_output,
                "status": plan.status.value,
                "rollback_status": "completed"
                if "已完成补偿回滚" in str(exc)
                else "not_required_or_failed",
            }
            self._task_plan_store.save(plan)
            raise


def _parse_tool_message_content(content: object) -> dict[str, Any]:
    """把 ToolMessage 的字符串或结构化正文统一收敛成可保存的字典。"""

    if isinstance(content, str):
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return {"content": content}
        return value if isinstance(value, dict) else {"content": value}
    return {"content": content}


def _user_has_permission(
    user: CurrentUserContext,
    permission: PermissionCode,
) -> bool:
    """判断用户是否可看到某个可选工具；真正执行时仍会经过权限服务。"""

    return user.role in {"admin", "system_admin"} or permission.value in user.permissions


def _require_document_candidate(
    doc_id: str,
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """只允许选择本轮权限过滤检索产生的 doc_id。"""

    candidate = candidates.get(doc_id)
    if candidate is None:
        raise AppServiceError("doc_id 不在本轮权限过滤后的检索候选中")
    return candidate


def _document_step_from_tool_result(
    *,
    call_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    output: dict[str, Any],
    index: int,
) -> AgentToolStep:
    """把成功的原生文档 ToolCall 冻结成一个待人工确认步骤。"""

    preview = output.get("preview")
    action_request = output.get("action_request")
    if not isinstance(preview, dict) or not isinstance(action_request, dict):
        raise AppServiceError("文档 dry-run ToolMessage 缺少 preview 或 action_request")
    operation = str(output.get("operation") or "")
    return AgentToolStep(
        step_id=f"step_{index}_{operation}_document",
        tool_name=tool_name,
        status=AgentToolStepStatus.WAITING_CONFIRMATION,
        input={**tool_input, "target_path": output.get("target_path")},
        output={
            "tool_call_id": call_id,
            "action_request": action_request,
            "preview": preview,
            "permission_decision": output.get("permission_decision", {}),
            "candidate": output.get("candidate"),
            "selection_reason": output.get("selection_reason", ""),
            "replacements": output.get("replacements", []),
            "diff": output.get("diff", ""),
        },
        risk_level=str(preview.get("risk_level") or "high"),
        requires_confirmation=True,
    )


def _document_candidates(docs: list[RetrievedDoc]) -> list[dict[str, Any]]:
    """把 chunk 命中按 doc_id 收敛成 LLM 可选择的文档候选。"""

    candidates: dict[str, dict[str, Any]] = {}
    for doc in docs:
        doc_id = str(doc.metadata.get("doc_id") or "").strip()
        source_path = str(doc.metadata.get("source_path") or "").strip()
        if not doc_id or not source_path:
            continue
        item = candidates.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "source_path": source_path,
                "title": doc.title,
                "chunk_count": 0,
                "matched_chunks": [],
                "permission_metadata": {
                    "visibility": doc.metadata.get("visibility"),
                    "allowed_departments": doc.metadata.get(
                        "allowed_departments", []
                    ),
                    "allowed_users": doc.metadata.get("allowed_users", []),
                    "permission_source": doc.metadata.get("permission_source"),
                },
            },
        )
        item["chunk_count"] += 1
        item["matched_chunks"].append(build_content_preview(doc.content))
    return list(candidates.values())


def _apply_unique_replacements(
    content: str,
    replacements: list[KnowledgeDocumentReplacement],
) -> str:
    """只应用在当前文本中唯一出现的精确替换。"""

    updated = content
    for replacement in replacements:
        count = updated.count(replacement.old_text)
        if count != 1:
            raise AppServiceError(
                "精确修改片段必须在目标文档中唯一出现: "
                f"matches={count} old_text={replacement.old_text[:80]!r}"
            )
        updated = updated.replace(
            replacement.old_text,
            replacement.new_text,
            1,
        )
    if updated == content:
        raise AppServiceError("文档修改计划没有产生内容变化")
    return updated


def _create_target_path(
    requested_path: str,
    user: CurrentUserContext,
    task_plan_id: str,
) -> str:
    """把 LLM 建议文件名限制在当前用户默认作用域目录。"""

    requested_name = Path(requested_path).name if requested_path else ""
    if not requested_name.endswith((".md", ".txt")):
        requested_name = f"agent-{task_plan_id.rsplit('_', 1)[-1]}.md"
    directory = user.primary_department_code or f"users/{user.user_id}"
    return f"{directory}/{requested_name}"


def _as_text(value: object) -> str:
    """把 LLM 返回值收敛成字符串，避免 None 被保存成 JSON null。"""

    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _fallback_final_answer(
    plan: AgentTaskPlan,
    results: list[AgentTaskSubQuestionResult],
) -> str:
    """LLM 最终综合返回空值时，用已完成子问题答案生成可读兜底结果。"""

    lines = [
        f"# {plan.objective}",
        "",
        "最终综合模型没有返回有效正文，以下为基于子问题结果生成的兜底答案。",
    ]
    for result in results:
        if result.status != "completed" or not result.answer.strip():
            continue
        lines.extend(["", f"## {result.question}", "", result.answer.strip()])
    return "\n".join(lines)


def _render_task_plan_markdown(plan: AgentTaskPlan) -> str:
    """把 TaskPlan JSON 快照渲染成更适合人工审查的 Markdown。"""

    lines = [
        f"# Agent TaskPlan: {plan.task_plan_id}",
        "",
        f"- 状态: `{plan.status.value}`",
        f"- 任务类型: `{plan.task_kind}` / `{plan.task_type}`",
        f"- 用户目标: {plan.objective}",
        f"- 原始问题: {plan.original_query}",
        f"- 检索 query: `{plan.source_query}`",
        f"- 查询接口: `/agent/task-plans/{plan.task_plan_id}`",
        f"- 确认接口: `/agent/task-plans/{plan.task_plan_id}/confirm`",
        f"- 取消接口: `/agent/task-plans/{plan.task_plan_id}/cancel`",
        f"- 重试接口: `/agent/task-plans/{plan.task_plan_id}/retry`",
    ]

    if plan.task_kind == "question_decomposition":
        lines.extend(["", "## 子问题拆解"])
        for item in sorted(plan.sub_questions, key=lambda sub: sub.order):
            depends_on = ", ".join(item.depends_on) if item.depends_on else "无"
            lines.extend(
                [
                    "",
                    f"### {item.order}. {item.question}",
                    "",
                    f"- sub_question_id: `{item.sub_question_id}`",
                    f"- 目的: {item.purpose}",
                    f"- 依赖: {depends_on}",
                    f"- 建议信息来源: `{item.information_source_hint}`",
                    f"- 拆解原因: {item.reason}",
                    f"- 期望证据: {item.expected_evidence or '无'}",
                ]
            )
        lines.extend(["", "## 最终整合要求", "", plan.final_synthesis_instruction])

        results = plan.final_output.get("sub_question_results", [])
        if isinstance(results, list) and results:
            lines.extend(["", "## 执行结果"])
            for result in results:
                if not isinstance(result, dict):
                    continue
                lines.extend(
                    [
                        "",
                        f"### {result.get('sub_question_id')} - {result.get('question')}",
                        "",
                        f"- 状态: `{result.get('status')}`",
                        f"- 使用工具: `{result.get('selected_tool')}`",
                        "",
                        result.get("answer") or result.get("error") or "",
                    ]
                )

        final_answer = plan.final_output.get("final_answer")
        if isinstance(final_answer, str) and final_answer.strip():
            lines.extend(["", "## 最终答案", "", final_answer.strip()])
    else:
        checkpoint = plan.final_output.get("checkpoint")
        if isinstance(checkpoint, dict):
            lines.extend(
                [
                    "",
                    "## Tool Loop 检查点",
                    "",
                    f"- 版本: `{checkpoint.get('version', '')}`",
                    f"- 最近完整轮次: `{checkpoint.get('round', 0)}`",
                    f"- 已消耗 ToolCall: `{checkpoint.get('call_count', 0)}`",
                    f"- 候选 doc_id: `{json.dumps(list((checkpoint.get('candidates') or {}).keys()), ensure_ascii=False)}`",
                    f"- 已读取 doc_id: `{json.dumps(checkpoint.get('read_doc_ids', []), ensure_ascii=False)}`",
                    f"- Tool Loop 已完成: `{checkpoint.get('completed', False)}`",
                ]
            )
        lines.extend(["", "## 文档动作"])
        for step in plan.steps:
            preview = step.output.get("preview")
            preview = preview if isinstance(preview, dict) else {}
            action_request = step.output.get("action_request")
            action_request = action_request if isinstance(action_request, dict) else {}
            operation = str(action_request.get("operation") or "")
            target_path = action_request.get("target_path") or step.input.get("target_path")
            warnings = preview.get("warnings")
            warnings = warnings if isinstance(warnings, list) else []
            lines.extend(
                [
                    "",
                    f"### {step.tool_name}: {target_path}",
                    "",
                    f"- 状态: `{step.status.value}`",
                    f"- tool_call_id: `{step.output.get('tool_call_id', '')}`",
                    f"- 操作: `{operation}`",
                    f"- 目标路径: `{target_path}`",
                    f"- doc_id: `{preview.get('affected_doc_id', '')}`",
                    f"- 风险等级: `{step.risk_level}`",
                    f"- 需要确认: `{step.requires_confirmation}`",
                    f"- 选择理由: {step.output.get('selection_reason') or '用户明确指定或创建任务'}",
                    f"- 操作原因: {action_request.get('reason') or '无'}",
                    f"- 权限: `{json.dumps(preview.get('permission_metadata', {}), ensure_ascii=False)}`",
                    f"- 影响 chunk 数: `{preview.get('affected_chunk_count', 0)}`",
                    f"- before_hash: `{preview.get('before_hash') or ''}`",
                    f"- after_hash: `{preview.get('after_hash') or ''}`",
                    f"- warnings: `{json.dumps(warnings, ensure_ascii=False)}`",
                ]
            )

            content = action_request.get("content")
            if operation == KnowledgeDocumentOperation.CREATE.value and isinstance(content, str):
                lines.extend(["", "#### 候选正文", "", *_markdown_fenced_block(content, "markdown")])

            replacements = step.output.get("replacements")
            if operation == KnowledgeDocumentOperation.UPDATE.value and isinstance(replacements, list):
                for index, replacement in enumerate(replacements, start=1):
                    if not isinstance(replacement, dict):
                        continue
                    lines.extend(
                        [
                            "",
                            f"#### 精确替换 {index}",
                            "",
                            "##### old_text",
                            "",
                            *_markdown_fenced_block(str(replacement.get("old_text") or ""), "text"),
                            "",
                            "##### new_text",
                            "",
                            *_markdown_fenced_block(str(replacement.get("new_text") or ""), "text"),
                        ]
                    )

            diff = step.output.get("diff")
            if isinstance(diff, str) and diff.strip():
                lines.extend(["", "#### 差异", "", *_markdown_fenced_block(diff, "diff")])

            candidate = step.output.get("candidate")
            if operation == KnowledgeDocumentOperation.DELETE.value and isinstance(candidate, dict):
                lines.extend(
                    [
                        "",
                        "#### 删除候选证据",
                        "",
                        f"- 标题: {candidate.get('title') or '无'}",
                        f"- source_path: `{candidate.get('source_path') or ''}`",
                    ]
                )
                matched_chunks = candidate.get("matched_chunks")
                if isinstance(matched_chunks, list):
                    for index, chunk in enumerate(matched_chunks, start=1):
                        lines.extend(
                            [
                                "",
                                f"##### 匹配片段 {index}",
                                "",
                                *_markdown_fenced_block(str(chunk), "text"),
                            ]
                        )

            execution_result = step.output.get("execution_result")
            if isinstance(execution_result, dict):
                lines.extend(
                    [
                        "",
                        "#### 执行结果",
                        "",
                        f"- executed: `{execution_result.get('executed', False)}`",
                        f"- message: {execution_result.get('message') or '无'}",
                    ]
                )
            elif step.error:
                lines.extend(["", "#### 执行错误", "", step.error])

    if plan.status == AgentTaskPlanStatus.FAILED and plan.error:
        lines.extend(["", "## 计划错误", "", plan.error])
    return "\n".join(lines) + "\n"


def _markdown_fenced_block(text: str, language: str) -> list[str]:
    """生成不会被正文内部反引号提前闭合的 Markdown 代码块。"""

    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return [f"{fence}{language}", text, fence]


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
    """规范化 LLM 工具选择；未知名称留给批次校验生成明确错误。"""

    del tools
    selected_tool = str(selection.get("selected_tool") or "none").strip()
    return {
        "call_id": selection.get("call_id"),
        "selected_tool": selected_tool,
        "tool_input": _normalize_tool_input(selection.get("tool_input")),
        "reason": str(selection.get("reason") or ""),
    }


def _parallel_batch_error(
    *,
    tool_names: list[str],
    registered_tool_names: set[str],
    parallel_safe_tool_names: set[str],
    max_parallel_calls: int,
    remaining_calls: int,
) -> str | None:
    """校验一轮 ToolCall 是否能作为独立只读批次并行执行。

    单调用无需并行限制；多个调用则必须都已注册、未超预算/并行上限，且全部位于
    ``parallel_safe_tool_names``。调用之间的业务依赖由调用方追加的专用校验处理。
    """

    if len(tool_names) > remaining_calls:
        return f"本轮 ToolCall 数超过剩余总调用预算: {len(tool_names)}>{remaining_calls}"
    unknown = [name for name in tool_names if name not in registered_tool_names]
    if unknown:
        return "本轮包含未注册工具: " + ", ".join(unknown)
    if len(tool_names) <= 1:
        return None
    if len(tool_names) > max_parallel_calls:
        return f"本轮 ToolCall 数超过并行上限: {len(tool_names)}>{max_parallel_calls}"
    serial = [name for name in tool_names if name not in parallel_safe_tool_names]
    if serial:
        return "同轮包含必须串行执行的工具，请按依赖分轮重试: " + ", ".join(serial)
    return None


def _failed_batch_traces(
    *,
    selections: list[dict[str, Any]],
    sub_question_id: str,
    round_index: int,
    error: str,
) -> list[AgentTaskToolCallTrace]:
    """把整轮拒绝转换成顺序稳定的失败轨迹。"""

    return [
        AgentTaskToolCallTrace(
            call_id=str(
                selection.get("call_id")
                or f"{sub_question_id}_tool_{round_index}_{index}"
            ),
            round=round_index,
            tool_name=str(selection.get("selected_tool") or "unknown"),
            tool_input=_normalize_tool_input(selection.get("tool_input")),
            status="failed",
            error=error,
            reason=str(selection.get("reason") or ""),
        )
        for index, selection in enumerate(selections, start=1)
    ]


def _document_batch_dependency_error(
    *,
    calls: list[dict[str, Any]],
    candidates: set[str],
    read_doc_ids: set[str],
) -> str | None:
    """校验要并行的tool 之间是否存在依赖。只使用本轮开始前的状态校验文档工具依赖。

    因为同批工具会并发运行，不能让本批 ``retrieval`` 的输出立即授权本批 ``read``，
    也不能让本批 ``read`` 立即授权本批 ``update``；否则执行顺序不确定且会绕过审查链。
    """

    for call in calls:
        tool_name = str(call.get("name") or "")
        tool_input = _normalize_tool_input(call.get("args"))
        doc_id = str(tool_input.get("doc_id") or "")

        # 如果触发 read 工具的调用，必须保证 阅读的这个 doc_id 是通过 knowledge_retrieval检索出来的，不能允许随意编造一个id
        if tool_name == KNOWLEDGE_DOCUMENT_READ_TOOL_NAME and doc_id not in candidates:
            return "knowledge_document_read 依赖前一轮 knowledge_retrieval 候选"
        # 更新文档操作 和上面同理
        if tool_name == KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME:
            if doc_id not in candidates:
                return "knowledge_document_update 依赖前一轮 knowledge_retrieval 候选"
            if doc_id not in read_doc_ids:
                return "knowledge_document_update 依赖前一轮 knowledge_document_read 结果"
        if tool_name == KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME and doc_id not in candidates:
            return "knowledge_document_delete 依赖前一轮 knowledge_retrieval 候选"
    return None


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
