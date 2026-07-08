from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

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
每个子问题最多选择一个工具。
如果当前子问题可以只依赖已有子问题答案进行推理，可以不调用工具。

选择原则：
- 项目知识库、已有工程实现、内部文档相关问题，优先 knowledge_retrieval。
- 当前知识库可能没有、需要公开互联网或最新资料时，选择 web_search。
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

    async def execute_question_decomposition_plan(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
    ) -> AgentTaskPlan:
        """按顺序回答问题拆解计划的子问题，并把结果整合成最终答案。"""

        if plan.task_kind != "question_decomposition":
            raise AppServiceError(f"不支持的问题拆解 task kind: {plan.task_kind}")

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
                )
                results.append(result)
                plan.final_output["sub_question_results"] = [
                    item.model_dump(mode="json") for item in results
                ]
                plan.final_output["used_tools"] = sorted(
                    {
                        item.selected_tool
                        for item in results
                        if item.selected_tool and item.selected_tool != "none"
                    }
                )
                self._task_plan_store.save(plan)

            # 允许单个子问题失败，但不能在完全没有有效答案时继续综合。
            if not any(item.status == "completed" for item in results):
                raise AppServiceError("所有子问题都执行失败，无法整合最终答案")

            final_answer = await self._synthesize_final_answer(plan, results)
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
    ) -> AgentTaskSubQuestionResult:
        """执行一个子问题：先让 LLM 选工具，再调用对应后端工具生成答案。"""

        selection = await self._select_tool_for_sub_question(
            plan=plan,
            sub_question=sub_question,
            previous_results=previous_results,
            default_mode=mode,
            default_top_k=top_k,
        )
        selected_tool = str(selection.get("selected_tool") or "none")
        tool_input = _normalize_tool_input(selection.get("tool_input"))

        try:
            # v1 每个子问题最多一次工具调用；多轮 tool loop 留给后续阶段。
            if selected_tool == KNOWLEDGE_RETRIEVAL_TOOL_NAME:
                tool_output, answer, evidence = await self._run_knowledge_retrieval_for_sub_question(
                    sub_question=sub_question,
                    tool_input=tool_input,
                    mode=mode,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    min_score=min_score,
                    filters=filters,
                )
            elif selected_tool == WEB_SEARCH_TOOL_NAME:
                tool_output, answer, evidence = await self._run_web_search_for_sub_question(
                    sub_question=sub_question,
                    tool_input=tool_input,
                    previous_results=previous_results,
                )
            elif selected_tool == "none":
                tool_output, answer, evidence = await self._answer_without_tool(
                    sub_question=sub_question,
                    previous_results=previous_results,
                )
            else:
                # 理论上 _validate_tool_selection 会拦截未知工具；这里保留防御。
                raise AppServiceError(f"LLM 选择了未注册工具: {selected_tool}")

            return AgentTaskSubQuestionResult(
                sub_question_id=sub_question.sub_question_id,
                question=sub_question.question,
                selected_tool=selected_tool,
                tool_input=tool_input,
                tool_output=tool_output,
                answer=answer,
                evidence=evidence,
                status="completed",
            )
        except Exception as exc:
            # 子问题失败不立刻中断整个计划，让后续子问题仍有机会完成。
            return AgentTaskSubQuestionResult(
                sub_question_id=sub_question.sub_question_id,
                question=sub_question.question,
                selected_tool=selected_tool,
                tool_input=tool_input,
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
    ) -> dict[str, Any]:
        """选择子问题工具。

        优先级：
        1. bound tools tool_call；
        2. 结构化 JSON；
        3. LLM 不可用时按 information_source_hint 兜底。
        """

        available_tools = self._build_available_task_tools()
        if not available_tools:
            return {"selected_tool": "none", "tool_input": {}}

        if self._settings.openai_api_key:
            selection = await self._select_tool_with_bound_tools(
                tools=available_tools,
                plan=plan,
                sub_question=sub_question,
                previous_results=previous_results,
            )
            if selection is None:
                selection = await self._select_tool_with_json(
                    plan=plan,
                    sub_question=sub_question,
                    previous_results=previous_results,
                )
            if selection is not None:
                return _validate_tool_selection(selection, available_tools)

        # LLM 不可用时的兜底，不作为正常企业场景的主判断器。
        fallback_tool = sub_question.information_source_hint
        if fallback_tool not in {tool.name for tool in available_tools}:
            fallback_tool = KNOWLEDGE_RETRIEVAL_TOOL_NAME
        return {
            "selected_tool": fallback_tool,
            "tool_input": {
                "query": sub_question.question,
                "mode": default_mode,
                "top_k": default_top_k,
            },
        }

    def _build_available_task_tools(self) -> list[BaseTool]:
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
        return tools

    async def _select_tool_with_bound_tools(
        self,
        tools: list[BaseTool],
        plan: AgentTaskPlan,
        sub_question: AgentTaskSubQuestion,
        previous_results: list[AgentTaskSubQuestionResult],
    ) -> dict[str, Any] | None:
        """用模型原生 tool calling 获取工具名和参数。"""

        try:
            model = ChatOpenAI(
                model=self._settings.llm_model_name,
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url,
                temperature=0.0,
            ).bind_tools(tools)
            response = await model.ainvoke(
                _build_tool_selection_messages(plan, sub_question, previous_results)
            )
        except Exception:
            return None

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # 模型明确不调用工具时，允许子问题走已有答案推理。
            return {"selected_tool": "none", "tool_input": {}}
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
                _build_tool_selection_messages(plan, sub_question, previous_results)
            )
        except Exception:
            return None
        if isinstance(response, AgentTaskToolSelectionPayload):
            return response.model_dump(mode="json")
        return response if isinstance(response, dict) else None

    async def _run_knowledge_retrieval_for_sub_question(
        self,
        sub_question: AgentTaskSubQuestion,
        tool_input: dict[str, Any],
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """执行知识库检索，并基于检索结果回答当前子问题。"""

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
        answer = await self._llm_client.generate(
            query=f"请回答子问题：{sub_question.question}",
            context=build_rag_context(sub_question.question, docs),
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
        answer = await self._llm_client.generate(
            query=f"请回答子问题：{sub_question.question}",
            context=_append_previous_answers(context, previous_results),
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
    ) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        """不调用工具，只用已完成的前置子问题答案推理。"""

        context = RagContext(
            query=sub_question.question,
            docs=[],
            context_text=_format_previous_answers(previous_results) or "无前置子问题答案。",
        )
        answer = await self._llm_client.generate(
            query=f"请基于已有子问题答案回答：{sub_question.question}",
            context=context,
        )
        return ({"reason": "no_tool_selected"}, answer, [])

    async def _synthesize_final_answer(
        self,
        plan: AgentTaskPlan,
        results: list[AgentTaskSubQuestionResult],
    ) -> str:
        """把所有子问题答案和证据整合成面向用户的最终回答。"""

        context = RagContext(
            query=plan.original_query,
            docs=[],
            context_text=_format_sub_question_results(results),
        )
        return await self._llm_client.generate(
            query=(
                f"请回答原始复杂问题：{plan.original_query}\n"
                f"最终目标：{plan.objective}\n"
                f"整合要求：{plan.final_synthesis_instruction}"
            ),
            context=context,
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
    ) -> AgentTaskPlan:
        """执行报告生成并保存到知识库的固定任务链路。"""

        if plan.task_kind != "knowledge_report_to_document":
            raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

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
            report_body = await self._llm_client.generate(
                query=f"请根据检索资料生成报告：{plan.report_title}",
                context=context,
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
            )

        step = _find_step(plan, "knowledge_document_create")
        if step.status != AgentToolStepStatus.WAITING_CONFIRMATION:
            raise AppServiceError("文档创建步骤状态不是 waiting_confirmation，拒绝执行")

        action_payload = step.output.get("action_request")
        preview_payload = step.output.get("preview")
        if not isinstance(action_payload, dict) or not isinstance(preview_payload, dict):
            raise AppServiceError("Agent task plan 缺少确认执行所需的 dry-run 事实")

        # 确认阶段不信任旧裁决结果，必须用当前用户和当前权限重新鉴权。
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
) -> list[SystemMessage | HumanMessage]:
    """构造给工具选择 LLM 的上下文，只暴露当前子问题和已完成答案。"""

    return [
        SystemMessage(content=TASK_TOOL_SELECTION_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "original_query": plan.original_query,
                    "objective": plan.objective,
                    "current_sub_question": sub_question.model_dump(mode="json"),
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
    }


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
                    f"回答: {result.answer}",
                    f"证据: {json.dumps(result.evidence, ensure_ascii=False)}",
                    f"错误: {result.error or ''}",
                ]
            )
        )
    return "\n\n".join(lines)


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
