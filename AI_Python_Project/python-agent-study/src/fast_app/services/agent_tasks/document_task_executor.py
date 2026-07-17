"""知识库文档 TaskPlan 的 Tool Loop、dry-run 与确认执行。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from difflib import unified_diff
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, messages_from_dict, messages_to_dict
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from fast_app.agents.tools.document_management_tools import (
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME, KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_READ_TOOL_NAME, KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    KnowledgeDocumentReplacement, build_knowledge_document_management_tools,
    build_knowledge_document_read_tool,
)
from fast_app.agents.tools.rag_agent_tools import KNOWLEDGE_RETRIEVAL_TOOL_NAME, retrieve_knowledge_docs
from fast_app.agents.tools.web_search_tools import WEB_SEARCH_TOOL_NAME, WebSearchToolInput, search_web_with_bocha
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus, AgentTaskToolCallTrace, AgentToolStep, AgentToolStepStatus
from fast_app.domain.agent_tool_permissions import AgentToolCallContext, AgentToolPermissionAction, PermissionCode
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentActionRequest, KnowledgeDocumentOperation, KnowledgeDocumentRiskLevel
from fast_app.domain.rag_models import RetrievalFilters, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_tool_support import build_mcp_task_tools, doc_to_evidence, normalize_tool_input, parallel_batch_error
from fast_app.services.agent_tasks.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tasks.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.knowledge.knowledge_document_management_service import KnowledgeDocumentManagementService
from fast_app.services.research.research_tool_loop import AgentTaskKnowledgeRetrievalToolInput
from fast_app.services.rag.rag_pipeline_service import build_content_preview

LangChainConfigFactory = Callable[[str], RunnableConfig]
PARALLEL_SAFE_DOCUMENT_TOOL_NAMES = {KNOWLEDGE_RETRIEVAL_TOOL_NAME, WEB_SEARCH_TOOL_NAME, KNOWLEDGE_DOCUMENT_READ_TOOL_NAME}

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
    pass


class _TaskPlanCancelledError(AppServiceError):
    pass


_ACTIVE_DOCUMENT_TASK_PLAN_IDS: set[str] = set()


class DocumentTaskExecutor:
    """只负责文档任务的 Tool Loop、确认和补偿状态。"""

    def __init__(self, settings: Settings, vector_retriever: BaseRetriever, keyword_retriever: BaseRetriever, document_management_service: KnowledgeDocumentManagementService, tool_permission_service: AgentToolPermissionService, tool_audit_service: AgentToolAuditService, task_plan_store: AgentTaskPlanStore) -> None:
        self._settings = settings
        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        self._document_management_service = document_management_service
        self._tool_permission_service = tool_permission_service
        self._tool_audit_service = tool_audit_service
        self._task_plan_store = task_plan_store

    def _sync_cancelled_state(self, plan: AgentTaskPlan) -> bool:
        latest = self._task_plan_store.load(plan.task_plan_id)
        if latest.status != AgentTaskPlanStatus.CANCELLED:
            return False
        plan.status = latest.status
        plan.steps = latest.steps
        plan.final_output = {**plan.final_output, **latest.final_output}
        plan.error = None
        return True

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
                # checkpoint 保存的是每个完整轮次后的状态；恢复不会执行一次只完成一半的并行批次。
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
        # 这个模型只负责提出 ToolCall；文档读写的真实实现与权限判断都在下方后端工具闭包中。
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
                # 先把 AIMessage 放入 checkpoint；无论本轮成功还是拒绝，下一轮都能看到自己刚才的调用。
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
                                tool_input=normalize_tool_input(call.get("args")),
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
                batch_error = parallel_batch_error(
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
                        tool_input = normalize_tool_input(call.get("args"))
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
                    tool_input = normalize_tool_input(call.get("args"))
                    tool = tools_by_name[tool_name]
                    try:
                        # tools 已由整批校验确认存在且可并行；这里不允许单个协程提前修改候选/read 状态。
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
                        # 只有 dry-run 写工具才能产出待确认步骤；retrieval/read 只更新下一轮可用的服务端事实。
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
            # 进程/请求中断可能发生在轮次边界以外，不能当作用户主动取消。
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
        # 将消息同时持久化为 LangChain 可反序列化格式，resume 才能把 ToolMessage 原样交回模型。
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
                    "evidence": [doc_to_evidence(doc) for doc in docs],
                },
                ensure_ascii=False,
            )

        async def read_document(doc_id: str) -> str:
            # 候选校验先于文件读取，防止模型用猜测的 doc_id/path 读取任意知识库文档。
            candidate = _require_document_candidate(doc_id, candidates)
            content = self._document_management_service.read_document_content(
                candidate["source_path"]
            )
            # 只有读取成功后才记入 read_doc_ids；这正是 update 的“读过原文”凭据。
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
            tools.extend(await build_mcp_task_tools(self._settings))
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
        # plan_action 负责路径/ACL/内容等领域校验，返回的是预览而不是实际写入结果。
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

    async def resume(
        self,
        *,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        return await self._execute_document_tool_loop(
            plan=plan, user=user, mode=mode, top_k=top_k, candidate_k=candidate_k,
            min_score=min_score, filters=filters,
            langchain_config_factory=langchain_config_factory, resume=True,
        )


def _parse_tool_message_content(content: object) -> dict[str, Any]:
    """把 ToolMessage 的字符串或结构化正文统一收敛成可保存的字典。"""

    if isinstance(content, str):
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            # 工具允许返回普通文本；不把它当成失败，包装后仍可展示在 trace 中。
            return {"content": content}
        # JSON 数组/标量同样保留，避免假设每个第三方工具都返回对象。
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
    # step 只保存确认所需的冻结事实；真正执行时会从 action_request 重建领域请求。
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
        # 一个文档可能命中多个 chunk；按 doc_id 聚合后，模型只能对文档而非单个片段发起写操作。
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
        # 仅保留片段预览，既给确认页面提供选择依据，也避免把整篇文档塞回 ToolCall 结果。
        item["matched_chunks"].append(build_content_preview(doc.content))
    return list(candidates.values())


def _apply_unique_replacements(
    content: str,
    replacements: list[KnowledgeDocumentReplacement],
) -> str:
    """只应用在当前文本中唯一出现的精确替换。"""

    updated = content
    for replacement in replacements:
        # 每次替换都基于上一次替换后的文本，因此也能发现 replacement 之间互相影响的歧义。
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
    # Path.name 丢弃模型给出的目录部分，避免 create 工具借文件名进行路径穿越。
    if not requested_name.endswith((".md", ".txt")):
        requested_name = f"agent-{task_plan_id.rsplit('_', 1)[-1]}.md"
    directory = user.primary_department_code or f"users/{user.user_id}"
    return f"{directory}/{requested_name}"
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
        # candidates/read_doc_ids 都是“本轮开始前”的副本，故同批新结果绝不能立刻解锁后继工具。
        tool_name = str(call.get("name") or "")
        tool_input = normalize_tool_input(call.get("args"))
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

__all__ = ["DocumentTaskExecutor"]
