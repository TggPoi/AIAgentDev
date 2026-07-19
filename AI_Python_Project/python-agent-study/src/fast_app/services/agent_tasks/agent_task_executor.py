"""TaskPlan 统一入口：只负责分派、安全检查和任务级控制。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentToolStepStatus,
)
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tasks.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from fast_app.services.exceptions import AppServiceError, ToolPermissionDeniedError
from fast_app.services.knowledge.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import (
    ResearchToolLoop,
    build_public_web_query as _build_public_web_query,
)
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent


LangChainConfigFactory = Callable[[str], RunnableConfig]
_ACTIVE_RESEARCH_TASK_PLAN_IDS: set[str] = set()


class AgentTaskExecutor:
    """对外保持统一 TaskPlan API，把实际工作交给两个专用执行器。"""

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
        evidence_evaluator: ResearchEvidenceEvaluator | None = None,
        research_executor: AgenticResearchExecutor | None = None,
        document_executor: DocumentTaskExecutor | None = None,
    ) -> None:
        """装配专用执行器；可注入协作者，旧脚本仍可传原有依赖。"""

        self._settings = settings
        self._task_plan_store = task_plan_store
        if research_executor is None:
            tool_loop = ResearchToolLoop(
                settings=settings,
                vector_retriever=vector_retriever,
                keyword_retriever=keyword_retriever,
                llm_client=llm_client,
            )
            worker_agent = ResearchWorkerAgent(
                settings=settings,
                tool_loop=tool_loop,
                evaluator=evidence_evaluator or ResearchEvidenceEvaluator(settings),
            )
            research_executor = AgenticResearchExecutor(
                settings=settings,
                llm_client=llm_client,
                task_plan_store=task_plan_store,
                worker_agent=worker_agent,
            )
        self._research_executor = research_executor
        self._document_executor = document_executor or DocumentTaskExecutor(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            document_management_service=document_management_service,
            tool_permission_service=tool_permission_service,
            tool_audit_service=tool_audit_service,
            task_plan_store=task_plan_store,
        )

    def save_plan(self, plan: AgentTaskPlan) -> None:
        """保存等待用户确认的 TaskPlan。"""

        self._task_plan_store.save(plan)

    def cancel(self, task_plan_id: str, user: CurrentUserContext) -> AgentTaskPlan:
        """写入任务级取消信号；运行节点会在下一安全边界停止。"""

        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能取消自己创建的 Agent task plan")
        if plan.status in {
            AgentTaskPlanStatus.COMPLETED,
            AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
            AgentTaskPlanStatus.CANCELLED,
        }:
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
        resume: bool = False,
    ) -> AgentTaskPlan:
        """兼容原入口并委托给 Research TaskPlan 执行器。"""

        return await self._research_executor.execute_question_decomposition_plan(
            plan=plan,
            user=user,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            filters=filters,
            langchain_config_factory=langchain_config_factory,
            resume=resume,
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
        """执行确认前的文档 Tool Loop。"""

        return await self._document_executor.execute(
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
        """按任务类型恢复最近完整快照。"""

        plan = self._load_owned_plan(task_plan_id, user)
        if plan.task_kind == "question_decomposition":
            if plan.status not in {
                AgentTaskPlanStatus.RUNNING,
                AgentTaskPlanStatus.FAILED,
                AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
            }:
                raise AppServiceError(
                    "研究 TaskPlan 只有 running、failed 或 completed_with_warnings 可以重试"
                )
            if not user.is_authenticated:
                raise ToolPermissionDeniedError("当前用户身份已失效，拒绝恢复研究计划")
            return await self._run_research_controlled(
                plan,
                user,
                langchain_config_factory=langchain_config_factory,
                resume=True,
            )
        if plan.task_kind != "knowledge_document_management":
            raise AppServiceError("当前只支持恢复文档管理 Tool Loop")
        if plan.status not in {AgentTaskPlanStatus.RUNNING, AgentTaskPlanStatus.FAILED}:
            raise AppServiceError("只有 running 或 failed 的文档 TaskPlan 可以恢复")
        workflow = plan.final_output.get("document_workflow")
        if isinstance(workflow, dict) and workflow.get("execution_mode") == "agentic":
            policy = plan.research_policy or AgentResearchPolicy(
                mode="hybrid",
                top_k=self._settings.rag_default_top_k,
                min_score=self._settings.rag_default_min_score,
                web_policy="disabled",
            )
            return await self._document_executor.execute(
                plan=plan,
                user=user,
                mode=policy.mode,
                top_k=policy.top_k,
                candidate_k=policy.candidate_k,
                min_score=policy.min_score,
                filters=self._current_filters(
                    user,
                    source_path=policy.source_path,
                    section_path=policy.section_path,
                ),
                langchain_config_factory=langchain_config_factory,
            )
        checkpoint = plan.final_output.get("checkpoint")
        if not isinstance(checkpoint, dict) or checkpoint.get("completed") is True:
            raise AppServiceError("Agent task plan 没有可恢复的轮次检查点")
        return await self._document_executor.resume(
            plan=plan,
            user=user,
            mode="hybrid",
            top_k=self._settings.rag_default_top_k,
            candidate_k=None,
            min_score=self._settings.rag_default_min_score,
            filters=self._current_filters(user),
            langchain_config_factory=langchain_config_factory,
        )

    async def confirm(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan:
        """确认计划，并在执行前使用当前身份和权限重新构造事实。"""

        plan = self._load_owned_plan(task_plan_id, user)
        if plan.status != AgentTaskPlanStatus.WAITING_CONFIRMATION:
            raise AppServiceError("Agent task plan 状态不是 waiting_confirmation，拒绝执行")
        if plan.task_kind == "question_decomposition":
            if not user.is_authenticated:
                raise ToolPermissionDeniedError("当前用户身份已失效，拒绝执行研究计划")
            return await self._run_research_controlled(
                plan,
                user,
                langchain_config_factory=langchain_config_factory,
                resume=False,
            )
        if plan.task_kind == "knowledge_document_management":
            return await self._document_executor.confirm(plan=plan, user=user)
        raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

    def _load_owned_plan(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
    ) -> AgentTaskPlan:
        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and user.role != "admin":
            raise ToolPermissionDeniedError("只能操作自己创建的 Agent task plan")
        return plan

    async def _run_research_controlled(
        self,
        plan: AgentTaskPlan,
        user: CurrentUserContext,
        *,
        langchain_config_factory: LangChainConfigFactory | None,
        resume: bool,
    ) -> AgentTaskPlan:
        task_plan_id = plan.task_plan_id
        if task_plan_id in _ACTIVE_RESEARCH_TASK_PLAN_IDS:
            raise AppServiceError("研究 TaskPlan 当前仍在执行，不能重复确认或恢复")
        policy = plan.research_policy or AgentResearchPolicy(
            mode="hybrid",
            top_k=self._settings.rag_default_top_k,
            min_score=self._settings.rag_default_min_score,
            web_policy="disabled",
        )
        _ACTIVE_RESEARCH_TASK_PLAN_IDS.add(task_plan_id)
        try:
            return await self.execute_question_decomposition_plan(
                plan=plan,
                user=user,
                mode=policy.mode,
                top_k=policy.top_k,
                candidate_k=policy.candidate_k,
                min_score=policy.min_score,
                filters=self._current_filters(
                    user,
                    source_path=policy.source_path,
                    section_path=policy.section_path,
                ),
                langchain_config_factory=langchain_config_factory,
                resume=resume,
            )
        finally:
            _ACTIVE_RESEARCH_TASK_PLAN_IDS.discard(task_plan_id)

    @staticmethod
    def _current_filters(
        user: CurrentUserContext,
        *,
        source_path: str | None = None,
        section_path: list[str] | None = None,
    ) -> RetrievalFilters:
        permissions = set(user.permissions)
        return RetrievalFilters(
            source_path=source_path,
            section_path=section_path or [],
            user_id=user.user_id,
            department_codes=list(user.department_codes),
            can_read_all=(
                user.role == "admin"
                or "*" in permissions
                or "knowledge:read:all" in permissions
            ),
            allow_public=True,
        )


__all__ = ["AgentTaskExecutor", "AgentTaskPlanStore"]
