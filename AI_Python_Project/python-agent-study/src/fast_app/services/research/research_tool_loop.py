"""单个 Research attempt 的工具选择、执行与候选答案生成。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from fast_app.agents.tools.rag_agent_tools import KNOWLEDGE_RETRIEVAL_TOOL_NAME, retrieve_knowledge_docs
from fast_app.agents.tools.web_search_tools import WEB_SEARCH_TOOL_NAME, WebSearchToolInput, search_web_with_bocha
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskSubQuestion, AgentTaskSubQuestionResult, AgentTaskToolCallTrace
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_tool_support import (
    build_mcp_task_tools, coerce_int, doc_to_evidence, extract_first_url,
    find_registered_tool, normalize_tool_input, parallel_batch_error,
)
from fast_app.services.exceptions import (
    AppServiceError,
    ExternalServiceError,
    ToolPermissionDeniedError,
)
from fast_app.services.rag.rag_pipeline_service import build_content_preview, build_top_doc_ids
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
from fast_app.services.rag.enhanced_web_search import execute_enhanced_web_search
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.nl2sql.service import Nl2SqlService

logger = get_logger(__name__)

LangChainConfigFactory = Callable[[str], RunnableConfig]
NL2SQL_QUERY_TOOL_NAME = "nl2sql_query"
MCP_FETCH_TOOL_NAME = "mcp__fetch"
PARALLEL_SAFE_TASK_TOOL_NAMES = {
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
    NL2SQL_QUERY_TOOL_NAME,
    MCP_FETCH_TOOL_NAME,
}


class AgentTaskToolSelectionPayload(BaseModel):
    """LLM 工具调用不可用时，用结构化 JSON 表达工具选择结果。"""

    selected_tool: str = Field(
        default="knowledge_retrieval",
        description="本轮选择的已注册只读工具名；none 表示不调用工具。",
    )
    tool_input: dict[str, Any] = Field(
        default_factory=dict,
        description="传给 selected_tool 的 JSON 参数；不得包含权限或 ACL 字段。",
    )
    reason: str = Field(default="", description="选择该工具和参数的简短理由。")


class AgentTaskKnowledgeRetrievalToolInput(BaseModel):
    """传给 knowledge_retrieval 的最小参数 schema。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, description="用于检索知识库的 query")
    mode: str = Field(default="hybrid", description="vector / keyword / hybrid")
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="本轮知识库检索最终保留的文档数量。",
    )


class AgentTaskNl2SqlToolInput(BaseModel):
    """服务端已绑定 Dataset 的结构化数据查询参数。"""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(
        min_length=1,
        max_length=1000,
        description="需要从已绑定业务 Dataset 查询的自然语言问题；不能提供 dataset_id 或 scope。",
    )
    max_rows: int = Field(
        default=100,
        ge=1,
        le=200,
        description="本轮最多返回的数据库结果行数。",
    )


@dataclass(slots=True)
class ToolExecutionResult:
    """一次工具执行产生的持久化摘要、证据摘要和内存上下文。"""

    tool_output: dict[str, Any]
    evidence: list[dict[str, Any]]
    context_docs: list[RetrievedDoc]


@dataclass(slots=True)
class ResearchAttemptOutcome:
    """Tool Loop 的公开结果以及不得写入 TaskPlan 的完整上下文分组。"""

    result: AgentTaskSubQuestionResult
    context_doc_groups: list[list[RetrievedDoc]]


TASK_TOOL_SELECTION_PROMPT = """你是 Agent TaskPlan 的工具选择器。

你只负责为当前子问题选择一个或多个已绑定工具。
可用工具只来自 bound tools，不允许编造工具名。
同一轮只有 knowledge_retrieval、web_search、nl2sql_query 和 mcp__fetch
可以组成多个彼此独立的只读 ToolCall；存在依赖时必须等待上一轮结果。
可以为多个互不依赖的 URL 同轮选择多个 mcp__fetch。
除 mcp__fetch 外，任何其他 mcp__* 工具每轮只能选择一个，且不能与其他工具混合。
如果已有工具结果足够回答当前子问题，不再调用工具。
如果当前子问题可以只依赖已有子问题答案进行推理，可以不调用工具。
如果系统进入结构化输出模式，必须返回符合 schema 的 JSON 对象。

选择原则：
- 项目知识库、已有工程实现、内部文档相关问题，优先 knowledge_retrieval。
- 资产、费用、库存、数量等业务数据库事实，选择 nl2sql_query。
- 同时需要知识库规则和数据库事实时，可以在同一轮并行选择 knowledge_retrieval 与 nl2sql_query。
- 当前知识库可能没有、需要公开互联网或最新资料时，选择 web_search。
- 查询官方资料且已知官方域名时，把不含协议和路径的域名传入 web_search.site。
- 子问题中已经给出明确 URL，且存在 mcp__fetch 工具时，优先 mcp__fetch 读取网页正文。
- 多个独立网页需要读取时，可以同轮返回多个 mcp__fetch，每个调用只包含自己的 URL。
- 综合性问题如果已有前置答案足够，可以不调用工具。
"""


class ResearchToolLoop:
    """完成一次子问题候选答案生成，不负责证据充分性纠正。"""

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker | None = None,
        prompt_guard: PromptGuardService | None = None,
        parent_expander: MarkdownParentContextExpander | None = None,
        nl2sql_service: Nl2SqlService | None = None,
        web_planner: DirectWebSearchPlanner | None = None,
    ) -> None:
        self._settings = settings
        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        self._llm_client = llm_client
        self._reranker = reranker
        self._prompt_guard = prompt_guard
        self._parent_expander = parent_expander
        self._nl2sql_service = nl2sql_service
        self._web_planner = web_planner

    async def _generate_with_trace(
        self,
        query: str,
        context: RagContext,
        langchain_config: RunnableConfig | None = None,
    ) -> str:
        """调用 LLM 根据tool执行结果和query生成独立回答；兼容测试中仍使用旧签名的 fake client。"""

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

    async def run_attempt(
        self,
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
        max_tool_calls_override: int | None = None,
        allow_web_search: bool = True,
        safe_web_query: str | None = None,
        attempt: int = 1,
        prior_tool_calls: list[AgentTaskToolCallTrace] | None = None,
        prior_evidence: list[dict[str, Any]] | None = None,
        prior_context_doc_groups: list[list[RetrievedDoc]] | None = None,
        retry_missing_points: list[str] | None = None,
        user: CurrentUserContext | None = None,
    ) -> ResearchAttemptOutcome:
        """执行一个子问题：让 LLM 进行有限多轮工具选择，再生成子问题答案。

        dependency_results 是已完成的前置子问题答案；prior_* 是当前 Worker 之前
        attempt 的历史。当前 attempt 只在全部工具执行完成后生成一次候选答案。
        """

        prior_tool_calls = list(prior_tool_calls or [])
        prior_evidence = list(prior_evidence or [])
        prior_context_doc_groups = list(prior_context_doc_groups or [])
        retry_missing_points = list(retry_missing_points or [])
        available_tools = await self._build_available_task_tools(
            allow_web_search=allow_web_search,
            plan=plan,
        )
        # override 由 Research Worker 的剩余预算提供，确保纠正轮不会突破单 Worker 总上限。
        max_tool_calls = max(
            self._settings.agent_max_tool_calls
            if max_tool_calls_override is None
            else max_tool_calls_override,
            0,
        )
        tool_calls: list[AgentTaskToolCallTrace] = []
        evidence: list[dict[str, Any]] = []
        context_doc_groups: list[list[RetrievedDoc]] = []
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
                    dependency_results=dependency_results,
                    default_mode=mode,
                    default_top_k=top_k,
                    available_tools=available_tools,
                    prior_tool_calls=prior_tool_calls,
                    prior_evidence=prior_evidence,
                    current_tool_calls=tool_calls,
                    current_evidence=evidence,
                    retry_missing_points=retry_missing_points,
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
                    # 模型明确停止调用工具后，跳出循环，随后用已成功的调用统一生成答案。
                    break

                # LLM 不负责强制预算，可能在只剩 1 次调用时仍返回 2~3 个并行
                # ToolCall。拒绝整个批次会浪费最后一次合法调用（尤其会让 Web
                # fallback 永远没有机会执行），因此按模型给出的稳定顺序只保留
                # 预算能够容纳的前 N 项。未保留项没有真正执行，也不计入调用数。
                remaining_calls = max_tool_calls - call_count
                selections = selections[:remaining_calls]
                batch_size = len(selections)
                # 一个批次中的每个实际候选 ToolCall 都计入总预算；即使随后因
                # 未注册或并行不安全被拒绝，也避免模型重复提交非法批次。
                call_count += batch_size
                # 先整体校验再启动协程：未知工具或含串行工具时，本轮一个也不执行。
                batch_error = parallel_batch_error(
                    tool_names=[
                        str(item.get("selected_tool") or "") for item in selections
                    ],
                    registered_tool_names={tool.name for tool in available_tools},
                    parallel_safe_tool_names=PARALLEL_SAFE_TASK_TOOL_NAMES,
                    max_parallel_calls=self._settings.agent_max_parallel_tool_calls,
                    remaining_calls=remaining_calls,
                )
                if batch_error:
                    # 被拒绝的调用仍写入 trace，供下一轮模型根据 ToolMessage/轨迹调整方案。
                    tool_calls.extend(
                        _failed_batch_traces(
                            selections=selections,
                            sub_question_id=sub_question.sub_question_id,
                            attempt=attempt,
                            round_index=round_index,
                            error=batch_error,
                        )
                    )
                    continue

                async def run_selection(
                    selection: dict[str, Any],
                    index: int,
                ) -> tuple[
                    AgentTaskToolCallTrace,
                    list[dict[str, Any]],
                    list[RetrievedDoc],
                ]:
                    """执行一个工具，并把可持久化结果与完整内存上下文分开返回。"""

                    # 每个协程只返回自己的 trace，不并发修改外层 tool_calls，避免共享列表写入竞态。
                    selected_tool = str(selection.get("selected_tool") or "")
                    tool_input = normalize_tool_input(selection.get("tool_input"))
                    if selected_tool == WEB_SEARCH_TOOL_NAME:
                        # 【规则匹配 移除敏感信息】Web 请求只使用当前公开子问题，不转发私有 Chunk、路径、ACL 或依赖原文。
                        tool_input = {
                            **tool_input,
                            "query": safe_web_query
                            or build_public_web_query(
                                plan.original_query, sub_question.question, []
                            ),
                        }
                    provider_call_id = str(
                        selection.get("call_id") or f"tool_{round_index}_{index}"
                    )
                    call_id = (
                        f"{sub_question.sub_question_id}_attempt_{attempt}_"
                        f"{provider_call_id}"
                    )
                    reason = str(selection.get("reason") or "")
                    try:
                        # 【执行 tool】这里只取得事实和证据；候选答案必须等本 attempt 的工具全部结束后生成。
                        execution = await self._run_task_tool_for_sub_question(
                            selected_tool=selected_tool,
                            tool_input=tool_input,
                            available_tools=available_tools,
                            sub_question=sub_question,
                            mode=mode,
                            top_k=top_k,
                            candidate_k=candidate_k,
                            min_score=min_score,
                            filters=filters,
                            tool_call_round=round_index,
                            langchain_config_factory=langchain_config_factory,
                            plan=plan,
                            user=user,
                        )
                        tagged_evidence = [
                            {**item, "tool_call_id": call_id}
                            for item in execution.evidence
                        ]
                        return (
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=selected_tool,
                                tool_input=tool_input,
                                tool_output=execution.tool_output,
                                status="completed",
                                reason=reason,
                            ),
                            tagged_evidence,
                            execution.context_docs,
                        )
                    except ToolPermissionDeniedError:
                        raise
                    except Exception as exc:
                        return (
                            AgentTaskToolCallTrace(
                                call_id=call_id,
                                round=round_index,
                                tool_name=selected_tool,
                                tool_input=tool_input,
                                status="failed",
                                error=f"{type(exc).__name__}: {exc}",
                                reason=reason,
                            ),
                            [],
                            [],
                        )

                # --------------------------------------------------开始普通任务 并行tool 执行--------------------------------------------------
                # 校验通过的只读调用同时开始；gather 按输入顺序返回，即使工具完成先后不同，
                batch_results = await asyncio.gather(
                    *(
                        run_selection(selection, index)
                        for index, selection in enumerate(selections, start=1)
                    )
                )
                for trace, call_evidence, context_docs in batch_results:
                    tool_calls.append(trace)
                    evidence = merge_evidence(evidence, call_evidence)
                    if context_docs:
                        context_doc_groups.append(context_docs)

            completed_calls = [
                item
                for item in [*prior_tool_calls, *tool_calls]
                if item.status == "completed"
            ]
            
            # 把上一轮执行的attempt检索到的正文，和本轮执行时检索到的正文进行组合，去重
            all_context_docs = _merge_context_doc_groups(
                [*prior_context_doc_groups, *context_doc_groups]
            )
            if all_context_docs or dependency_results:
                # 【所有 tool 执行完成后整合回答】完整正文只存在于当前 Worker 内存，
                # TaskPlan 只接收 tool_output 与 evidence 摘要。
                answer = await self._answer_from_tool_calls(
                    sub_question=sub_question,
                    dependency_results=dependency_results,
                    context_docs=all_context_docs,
                    filters=filters,
                    retry_missing_points=retry_missing_points,
                    langchain_config_factory=langchain_config_factory,
                )
                last_call = completed_calls[-1] if completed_calls else None
                return ResearchAttemptOutcome(
                    result=AgentTaskSubQuestionResult(
                        sub_question_id=sub_question.sub_question_id,
                        question=sub_question.question,
                        selected_tool=last_call.tool_name if last_call else "none",
                        tool_input=last_call.tool_input if last_call else {},
                        tool_output=last_call.tool_output if last_call else {},
                        tool_calls=tool_calls,
                        answer=answer,
                        evidence=evidence,
                        status="completed",
                    ),
                    context_doc_groups=context_doc_groups,
                )

            if tool_calls or prior_tool_calls:
                # 工具可能成功返回空结果，也可能全部失败；两种情况都没有可供回答的事实。
                last_call = (tool_calls or prior_tool_calls)[-1]
                return ResearchAttemptOutcome(
                    result=AgentTaskSubQuestionResult(
                        sub_question_id=sub_question.sub_question_id,
                        question=sub_question.question,
                        selected_tool=last_call.tool_name,
                        tool_input=last_call.tool_input,
                        tool_output=last_call.tool_output,
                        tool_calls=tool_calls,
                        status="failed",
                        error=last_call.error or "NO_USABLE_EVIDENCE",
                    ),
                    context_doc_groups=context_doc_groups,
                )

            # LLM 一开始就判断不需要工具，或者 agent_max_tool_calls=0 时，走纯推理分支。
            # 这个分支只能使用 dependency_results，不会主动检索或访问外部工具。
            tool_output, answer, evidence = await self._answer_without_tool(
                sub_question=sub_question,
                dependency_results=dependency_results,
                langchain_config_factory=langchain_config_factory,
            )
            return ResearchAttemptOutcome(
                result=AgentTaskSubQuestionResult(
                    sub_question_id=sub_question.sub_question_id,
                    question=sub_question.question,
                    selected_tool="none",
                    tool_input={},
                    tool_output=tool_output,
                    tool_calls=[],
                    answer=answer,
                    evidence=evidence,
                    status="completed",
                ),
                context_doc_groups=[],
            )
        except ToolPermissionDeniedError:
            # 权限拒绝属于任务级安全事件，不能降级成“这个子问题失败后继续试”。
            raise
        except Exception as exc:
            # 子问题失败不立刻中断整个计划，让后续子问题仍有机会完成。
            return ResearchAttemptOutcome(
                result=AgentTaskSubQuestionResult(
                    sub_question_id=sub_question.sub_question_id,
                    question=sub_question.question,
                    selected_tool=tool_calls[-1].tool_name if tool_calls else "none",
                    tool_input=tool_calls[-1].tool_input if tool_calls else {},
                    tool_calls=tool_calls,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                ),
                context_doc_groups=context_doc_groups,
            )

    async def _select_tool_for_sub_question(
        self,
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        default_mode: str,
        default_top_k: int,
        available_tools: list[BaseTool] | None = None,
        prior_tool_calls: list[AgentTaskToolCallTrace] | None = None,
        prior_evidence: list[dict[str, Any]] | None = None,
        current_tool_calls: list[AgentTaskToolCallTrace] | None = None,
        current_evidence: list[dict[str, Any]] | None = None,
        retry_missing_points: list[str] | None = None,
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
        prior_tool_calls = prior_tool_calls or []
        prior_evidence = prior_evidence or []
        current_tool_calls = current_tool_calls or []
        current_evidence = current_evidence or []
        retry_missing_points = retry_missing_points or []
        if not available_tools:
            return []

        if self._settings.openai_api_key:
            # 明确 web_research 计划的第一轮必须产生原生 Web Search ToolCall。
            # URL 场景仍交给下面既有的 mcp__fetch 强制修正规则。
            required_tool_name = (
                WEB_SEARCH_TOOL_NAME
                if not current_tool_calls
                and sub_question.information_source_hint == WEB_SEARCH_TOOL_NAME
                and extract_first_url(sub_question.question) is None
                else None
            )
            if required_tool_name is not None and required_tool_name not in {
                tool.name for tool in available_tools
            }:
                raise AppServiceError("Web Search 工具未配置或当前不可用")
            # 获取 llm 根据子问题 选择要使用的tool
            selections = await self._select_tool_with_bound_tools(
                tools=available_tools,
                plan=plan,
                sub_question=sub_question,
                dependency_results=dependency_results,
                prior_tool_calls=prior_tool_calls,
                prior_evidence=prior_evidence,
                current_tool_calls=current_tool_calls,
                current_evidence=current_evidence,
                retry_missing_points=retry_missing_points,
                required_tool_name=required_tool_name,
                langchain_config_factory=langchain_config_factory,
            )
            if selections is None:
                # 原生 ToolCall 失败时才退到 JSON；两种协议不会同时请求，避免重复选择。
                if required_tool_name is not None:
                    # web_policy=required 已由服务端策略确认；模型不支持原生 ToolCall 时，
                    # 由后端生成最小 WebSearch 调用，实际 query 仍会在执行前被隐私清洗。
                    return [
                        {
                            "selected_tool": WEB_SEARCH_TOOL_NAME,
                            "tool_input": {
                                "query": sub_question.question,
                                "count": default_top_k,
                            },
                            "reason": "server_enforced_required_web_policy",
                        }
                    ]
                selection = await self._select_tool_with_json(
                    plan=plan,
                    sub_question=sub_question,
                    dependency_results=dependency_results,
                    prior_tool_calls=prior_tool_calls,
                    prior_evidence=prior_evidence,
                    current_tool_calls=current_tool_calls,
                    current_evidence=current_evidence,
                    retry_missing_points=retry_missing_points,
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
                if not current_tool_calls and extract_first_url(sub_question.question):
                    # URL 在首轮即可确定；后端固定 fetch，避免模型把已知地址误交给检索工具。
                    return [
                        _repair_fetch_tool_selection(
                            selection={"selected_tool": "none", "tool_input": {}},
                            sub_question=sub_question,
                            tools=available_tools,
                        )
                    ]
                return validated

        # LLM 不可用时的兜底，不作为正常企业场景的主判断器。
        if current_tool_calls:
            # 无 LLM 兜底只允许首轮选择一次；后续没有模型就停止，避免根据旧输入重复调用。
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

    async def _build_available_task_tools(
        self,
        allow_web_search: bool = True,
        plan: AgentTaskPlan | None = None,
    ) -> list[BaseTool]:
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
        if (
            self._nl2sql_service is not None
            and plan is not None
            and plan.research_policy is not None
            and plan.research_policy.dataset_id
            and plan.research_policy.nl2sql_action == "query"
        ):
            async def nl2sql_query(question: str, max_rows: int = 100) -> str:
                # Dataset、用户和 Scope 由服务端闭包外的执行分支绑定，不允许模型传入。
                return ""

            tools.append(
                StructuredTool.from_function(
                    coroutine=nl2sql_query,
                    name=NL2SQL_QUERY_TOOL_NAME,
                    description="查询服务端已绑定的非敏感业务 Dataset，适合资产、费用、库存和数量等数据库事实。",
                    args_schema=AgentTaskNl2SqlToolInput,
                )
            )

        if allow_web_search and self._settings.bocha_api_key:
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
        tools.extend(await build_mcp_task_tools(self._settings))
        return tools

    async def _select_tool_with_bound_tools(
        self,
        tools: list[BaseTool],
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        prior_tool_calls: list[AgentTaskToolCallTrace],
        prior_evidence: list[dict[str, Any]],
        current_tool_calls: list[AgentTaskToolCallTrace],
        current_evidence: list[dict[str, Any]],
        retry_missing_points: list[str],
        required_tool_name: str | None = None,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> list[dict[str, Any]] | None:
        """返回 LLM 本轮选择的全部原生 ToolCall。"""

        try:
            bound_tools = (
                [tool for tool in tools if tool.name == required_tool_name]
                if required_tool_name is not None
                else tools
            )
            bind_options: dict[str, Any] = {
                "parallel_tool_calls": required_tool_name is None,
            }
            if required_tool_name is not None:
                bind_options["tool_choice"] = required_tool_name
            model = ChatOpenAI(
                model=self._settings.llm_model_name,
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                temperature=0.0,
            ).bind_tools(bound_tools, **bind_options)
            response = await model.ainvoke(
                # 开始由llm选择当前任务需要调用哪些tool
                _build_tool_selection_messages(
                    plan,
                    sub_question,
                    dependency_results,
                    prior_tool_calls,
                    prior_evidence,
                    current_tool_calls,
                    current_evidence,
                    retry_missing_points,
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
            # provider/协议差异由调用者继续尝试 JSON fallback；这里不泄露底层异常给模型上下文。
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
        dependency_results: list[AgentTaskSubQuestionResult],
        prior_tool_calls: list[AgentTaskToolCallTrace],
        prior_evidence: list[dict[str, Any]],
        current_tool_calls: list[AgentTaskToolCallTrace],
        current_evidence: list[dict[str, Any]],
        retry_missing_points: list[str],
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
                    dependency_results,
                    prior_tool_calls,
                    prior_evidence,
                    current_tool_calls,
                    current_evidence,
                    retry_missing_points,
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
            # JSON fallback 也不可用时交由上层按 information_source_hint 做最小保守选择。
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
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        tool_call_round: int = 1,
        langchain_config_factory: LangChainConfigFactory | None = None,
        plan: AgentTaskPlan | None = None,
        user: CurrentUserContext | None = None,
    ) -> ToolExecutionResult:
        """执行本地工具或 MCP 工具，不在单个工具边界生成答案。"""

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
                langchain_config_factory=langchain_config_factory,
            )
        if selected_tool == NL2SQL_QUERY_TOOL_NAME:
            if (
                self._nl2sql_service is None
                or plan is None
                or plan.research_policy is None
                or not plan.research_policy.dataset_id
                or user is None
            ):
                raise AppServiceError("nl2sql_query 缺少服务端 Dataset 或用户绑定")
            result = await self._nl2sql_service.query(
                user=user,
                dataset_id=plan.research_policy.dataset_id,
                question=str(
                    tool_input.get("question") or sub_question.question
                ).strip(),
                max_rows=coerce_int(
                    tool_input.get("max_rows"),
                    default=100,
                    minimum=1,
                    maximum=200,
                ),
            )
            text = result.model_dump_json()
            doc = RetrievedDoc(
                id=result.query_id,
                content=text,
                score=1.0,
                source=NL2SQL_QUERY_TOOL_NAME,
                title=f"NL2SQL 查询 {result.query_id}",
                metadata={
                    "tool_name": NL2SQL_QUERY_TOOL_NAME,
                    "query_id": result.query_id,
                    "dataset_id": result.dataset_id,
                    "row_count": result.row_count,
                    "columns": list(result.columns),
                },
            )
            return ToolExecutionResult(
                tool_output={
                    "query_id": result.query_id,
                    "row_count": result.row_count,
                    "columns": list(result.columns),
                    "status": "completed",
                },
                evidence=[doc_to_evidence(doc)],
                context_docs=[doc],
            )

        # 走到这里的是 MCP 等外部工具：先按白名单取工具，再由 LangChain tool 执行。
        tool = find_registered_tool(selected_tool, available_tools)
        # MCP 输出未必是字符串；统一成文本后，完整内容只保留在 Worker 内存。
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
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        doc = RetrievedDoc(
            id=f"{selected_tool}_{digest}",
            content=text,
            score=1.0,
            source=selected_tool,
            title=selected_tool,
            metadata={"tool_name": selected_tool},
        )
        return ToolExecutionResult(
            tool_output={
                "content_length": len(text),
                "content_preview": build_content_preview(text),
            },
            evidence=[doc_to_evidence(doc)],
            context_docs=[doc],
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
    ) -> ToolExecutionResult:
        """执行知识库检索并返回摘要、证据与完整内存文档。"""

        # LLM 可能给出不完整或越界参数；这里用后端默认值和范围做最后收敛。
        query = str(tool_input.get("query") or sub_question.question).strip()
        selected_mode = str(tool_input.get("mode") or mode).strip()
        if selected_mode not in {"vector", "keyword", "hybrid"}:
            selected_mode = mode
        selected_top_k = coerce_int(tool_input.get("top_k"), default=top_k, minimum=1, maximum=20)
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
        if self._reranker is not None and docs:
            try:
                docs = await self._reranker.rerank(
                    query=query,
                    docs=docs,
                    top_k=min(selected_top_k, len(docs)),
                )
            except ExternalServiceError:
                docs = docs[:selected_top_k]
        # 完整 docs 交给 attempt 结束后的统一回答，TaskPlan 只保存下面的摘要。
        return ToolExecutionResult(
            tool_output={
                "doc_count": len(docs),
                "top_doc_ids": build_top_doc_ids(docs),
            },
            evidence=[doc_to_evidence(doc) for doc in docs],
            context_docs=docs,
        )

    async def _run_web_search_for_sub_question(
        self,
        sub_question: AgentTaskSubQuestion,
        tool_input: dict[str, Any],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> ToolExecutionResult:
        """执行网页搜索：优先增强链路，不可用时回退裸 Bocha 调用。

        tool_input 中的 query 已由执行分支替换为隐私清洗后的公开查询，
        增强服务不感知私有内容；site 通过 forced_site 传给 Planner 兜底。
        """

        query = str(tool_input.get("query") or sub_question.question).strip()
        count = coerce_int(tool_input.get("count"), default=5, minimum=1, maximum=10)
        site = str(tool_input.get("site") or "").strip() or None
        docs: list[RetrievedDoc] | None = None
        if self._web_planner is not None:
            try:
                docs = await execute_enhanced_web_search(
                    settings=self._settings,
                    planner=self._web_planner,
                    question=query,
                    top_k=count,
                    forced_site=site,
                    plan_langchain_config=(
                        langchain_config_factory(
                            f"sub_question.{sub_question.sub_question_id}.web_search.plan"
                        )
                        if langchain_config_factory is not None
                        else None
                    ),
                    select_langchain_config=(
                        langchain_config_factory(
                            f"sub_question.{sub_question.sub_question_id}.web_search.candidate_selection"
                        )
                        if langchain_config_factory is not None
                        else None
                    ),
                )
            except Exception as exc:
                # 增强链路是增强不是硬依赖：规划、sitemap 或抓取失败时
                # 回退直接搜索引擎调用，保证 Worker 工具循环可用性。
                logger.warning(
                    "research_web_search_enhanced_fallback %s",
                    format_log_fields(
                        event="research.web_search.enhanced_fallback",
                        sub_question_id=sub_question.sub_question_id,
                        error_type=type(exc).__name__,
                    ),
                )
                docs = None
        if docs is None:
            async with httpx.AsyncClient() as http_client:
                results = await search_web_with_bocha(
                    settings=self._settings,
                    http_client=http_client,
                    query=query,
                    count=count,
                    site=site,
                )
            # WebSearch 返回的数据模型与本地检索不同；转成 RetrievedDoc 后可以复用同一 RAG 上下文构造器。
            docs = [
                RetrievedDoc(
                    id=(
                        "web_"
                        + hashlib.sha256(
                            (item.url or f"{item.title}:{index}").encode("utf-8")
                        ).hexdigest()[:16]
                    ),
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
        return ToolExecutionResult(
            tool_output={
                "result_count": len(docs),
                "top_urls": [
                    str((doc.metadata or {}).get("url") or doc.title)
                    for doc in docs[:5]
                ],
            },
            evidence=[doc_to_evidence(doc) for doc in docs],
            context_docs=docs,
        )

    async def _answer_without_tool(
        self,
        sub_question: AgentTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """不调用工具，只用已完成的前置子问题答案推理。"""

        context = RagContext(
            query=sub_question.question,
            docs=[],
            context_text=_format_dependency_answers(dependency_results) or "无前置子问题答案。",
        )
        # 纯推理路径没有外部事实，evidence 为空；调用方仍把答案标记为 completed。
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

    async def _answer_from_tool_calls(
        self,
        sub_question: AgentTaskSubQuestion,
        dependency_results: list[AgentTaskSubQuestionResult],
        context_docs: list[RetrievedDoc],
        filters: RetrievalFilters,
        retry_missing_points: list[str],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> str:
        """用历史和当前 attempt 的全部工具原始上下文生成一次候选答案。"""

        context = _append_dependency_answers(
            await assemble_rag_context(
                settings=self._settings,
                query=sub_question.question,
                docs=context_docs,
                filters={
                    "source_path": filters.source_path,
                    "section_path": filters.section_path,
                    "can_read_all": filters.can_read_all,
                    "user_id": filters.user_id,
                    "department_codes": filters.department_codes,
                    "allow_public": filters.allow_public,
                },
                source="research.build_context",
                parent_expander=self._parent_expander,
                prompt_guard=self._prompt_guard,
            ),
            dependency_results,
        )
        # 上一次attempt执行后，是否信息不足导致需要补充的要点。在本轮attempt进行补充查询
        missing_text = "; ".join(retry_missing_points)
        query = f"请综合全部工具证据回答子问题：{sub_question.question}"
        if missing_text:
            query += f"\n本次纠正需要重点补足：{missing_text}"

        # 执行llm查询
        return await self._generate_with_trace(
            query=query,
            context=context,
            langchain_config=(
                langchain_config_factory(
                    f"sub_question.{sub_question.sub_question_id}.tool_answer"
                )
                if langchain_config_factory is not None
                else None
            ),
        )

def _build_tool_selection_messages(
    plan: AgentTaskPlan,
    sub_question: AgentTaskSubQuestion,
    dependency_results: list[AgentTaskSubQuestionResult],
    prior_tool_calls: list[AgentTaskToolCallTrace],
    prior_evidence: list[dict[str, Any]],
    current_tool_calls: list[AgentTaskToolCallTrace],
    current_evidence: list[dict[str, Any]],
    retry_missing_points: list[str],
) -> list[SystemMessage | HumanMessage]:
    """构造工具选择上下文，明确区分依赖结果、历史 attempt 和当前 attempt。"""

    # 只传当前子问题和其依赖已完成答案，避免同批无关 Worker 的中间信息污染工具选择。
    return [
        SystemMessage(content=TASK_TOOL_SELECTION_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "original_query": plan.original_query,
                    "objective": plan.objective,
                    "current_sub_question": sub_question.model_dump(mode="json"),
                    "dependency_answers": [
                        {
                            "sub_question_id": item.sub_question_id,
                            "question": item.question,
                            "answer": item.answer,
                            "status": item.status,
                        }
                        for item in dependency_results
                    ],
                    "prior_attempt_tool_calls": [
                        item.model_dump(mode="json") for item in prior_tool_calls
                    ],
                    "prior_attempt_evidence": prior_evidence,
                    "current_attempt_tool_calls": [
                        item.model_dump(mode="json") for item in current_tool_calls
                    ],
                    "current_attempt_evidence": current_evidence,
                    "retry_missing_points": retry_missing_points,
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
    # 这里故意不校验名称：批次校验需要收集整轮全部未知工具，才能给模型完整的修正反馈。
    selected_tool = str(selection.get("selected_tool") or "none").strip()
    return {
        "call_id": selection.get("call_id"),
        "selected_tool": selected_tool,
        "tool_input": normalize_tool_input(selection.get("tool_input")),
        "reason": str(selection.get("reason") or ""),
    }

def _failed_batch_traces(
    *,
    selections: list[dict[str, Any]],
    sub_question_id: str,
    attempt: int,
    round_index: int,
    error: str,
) -> list[AgentTaskToolCallTrace]:
    """把整轮拒绝转换成顺序稳定的失败轨迹。"""

    return [
        AgentTaskToolCallTrace(
            call_id=(
                f"{sub_question_id}_attempt_{attempt}_"
                f"{selection.get('call_id') or f'tool_{round_index}_{index}'}"
            ),
            round=round_index,
            tool_name=str(selection.get("selected_tool") or "unknown"),
            tool_input=normalize_tool_input(selection.get("tool_input")),
            status="failed",
            error=error,
            reason=str(selection.get("reason") or ""),
        )
        for index, selection in enumerate(selections, start=1)
    ]


def _repair_fetch_tool_selection(
    selection: dict[str, Any],
    sub_question: AgentTaskSubQuestion,
    tools: list[BaseTool],
) -> dict[str, Any]:
    """【URL 场景下的稳定性补丁】判断拆解后的subquestion中是否包含明确的 URL，如果有则强制使用 Fetch MCP 工具读取网页正文"""

    if MCP_FETCH_TOOL_NAME not in {tool.name for tool in tools}:
        return selection

    # 提取question中的 URL，为空时，直接返回原始选择
    url = extract_first_url(sub_question.question)
    if not url:
        return selection

    tool_input = normalize_tool_input(selection.get("tool_input"))
    if selection.get("selected_tool") == MCP_FETCH_TOOL_NAME:
        # 保留模型填出的其他合法参数，只在 url 缺失时补上已从问题提取出的地址。
        return {
            **selection,
            "tool_input": {"url": tool_input.get("url") or url, **tool_input},
        }

    return {
        "selected_tool": MCP_FETCH_TOOL_NAME,
        "tool_input": {"url": url},
        "reason": "子问题包含明确 URL，使用 Fetch MCP 读取网页正文。",
    }

def merge_evidence(
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按来源与证据 ID 去重，保留各纠正轮首次出现的稳定顺序。"""

    merged = list(current)
    seen = {
        (str(item.get("source") or ""), str(item.get("id") or item.get("url") or ""))
        for item in merged
    }
    for item in incoming:
        # source 与 id/url 共同构成来源键，允许不同来源恰好使用同一个标识。
        key = (
            str(item.get("source") or ""),
            str(item.get("id") or item.get("url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _merge_context_doc_groups(
    groups: list[list[RetrievedDoc]],
) -> list[RetrievedDoc]:
    """按工具组轮询合并完整文档，并按来源身份稳定去重。"""

    merged: list[RetrievedDoc] = []
    seen: set[tuple[str, str]] = set()
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index >= len(group):
                continue
            doc = group[index]
            identity = str(doc.metadata.get("url") or doc.id)
            key = (doc.source, identity)
            if key in seen:
                continue
            seen.add(key)
            merged.append(doc)
    return merged


def build_public_web_query(
    original_query: str,
    sub_question: str,
    missing_points: list[str],
) -> str:
    """规则匹配 移除敏感信息 只用公开问题边界构造 Web 查询，并移除常见内部标识与本地路径。"""

    text = " ".join([original_query, sub_question, *missing_points])
    # 不把邮箱、本地/知识库路径、ACL 字段和常见员工/资产标识发送给外部搜索服务。
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", " ", text)
    text = re.sub(r"\b[A-Za-z]:[\\/][^\s，。；;]+", " ", text)
    text = re.sub(r"[^\s，。；;]+\.(?:md|txt|pptx|xlsx)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(?:AST|EMP|USER|EMPLOYEE|ASSET)[-_:#：]?[A-Za-z0-9_-]+\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:user_id|department_codes|allowed_departments|can_read_all|ACL)\s*[:=：]\s*[^\s，。；;]+",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    normalized = " ".join(text.split())[:500]
    # 清洗后为空仍给搜索服务一个无敏感信息的最小查询，避免发出空请求。
    return normalized or "公开资料研究"

def _format_dependency_answers(results: list[AgentTaskSubQuestionResult]) -> str:
    """格式化已完成子问题答案，供后续子问题引用。"""

    lines: list[str] = []
    for result in results:
        if result.status not in {"completed", "partial"}:
            continue
        limitations = []
        if result.status == "partial":
            limitations.extend(result.warnings)
            if result.evaluation is not None:
                limitations.extend(result.evaluation.missing_points)
        suffix = f"\n不足说明: {'; '.join(limitations)}" if limitations else ""
        lines.append(
            f"[{result.sub_question_id}] {result.question}\n{result.answer}{suffix}"
        )
    return "\n\n".join(lines)

def _append_dependency_answers(
    context: RagContext,
    dependency_results: list[AgentTaskSubQuestionResult],
) -> RagContext:
    """在 RAG context 后附加前置答案，保持 docs 不变。"""

    dependency_answers = _format_dependency_answers(dependency_results)
    if not dependency_answers:
        return context
    # RagContext 是值对象；创建副本而非原地修改，避免调用方共享的 context 被悄悄污染。
    return RagContext(
        query=context.query,
        docs=context.docs,
        context_text=(
            f"{context.context_text}\n\n【前置子问题答案】\n{dependency_answers}"
        ),
    )


def _as_text(value: object) -> str:
    """把不同 LLM client 的返回值收敛为文本。"""

    if isinstance(value, str):
        return value
    return str(value or "")


__all__ = [
    "AgentTaskKnowledgeRetrievalToolInput",
    "ResearchAttemptOutcome",
    "ResearchToolLoop",
    "ToolExecutionResult",
    "build_public_web_query",
    "merge_evidence",
]
