"""TaskPlan 统一入口：只负责分派、安全检查和任务级控制。

``AgentTaskExecutor`` 是 API/管道层调用 Agent TaskPlan 的 Facade，它不自己执行
Research Worker、工具循环或文档写入细节。它主要解决四个问题：

1. 根据 ``task_kind`` 把任务交给 ``AgenticResearchExecutor`` 或
   ``DocumentTaskExecutor``。
2. 在 confirm/retry 时重新加载 TaskPlan，并使用当前用户重新鉴权。
3. 用 ``task_plan_id -> asyncio.Lock`` 防止同一任务被两个 HTTP 请求
   同时 confirm/retry。
4. 在不等待长任务锁的前提下写入 cancel 信号，让正在运行的节点
   在下一个安全边界停止。

阅读主线可以从 ``confirm()`` 和 ``resume()`` 开始：两者先取任务锁，
然后在锁内重读 TaskPlan、检查归属/状态，最后分派专用执行器。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
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
from fast_app.domain.research_task_plan import (
    AgentTaskPlannerCandidate,
    ResearchTaskPlan,
    ResearchTaskSubQuestionCandidate,
)
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_capability_service import (
    AgentTaskCapabilityService,
)
from fast_app.services.agent_tasks.agent_task_plan_validator import AgentTaskPlanValidator
from fast_app.services.agent_tasks.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tasks.agent_tool_permission_service import AgentToolPermissionService
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from fast_app.services.exceptions import (
    AgentTaskPlanBusyError,
    AgentTaskSourceUnavailableError,
    AppServiceError,
    ToolPermissionDeniedError,
)
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
# Research 执行时的进程内活动集合。它是 Research 链路的额外重入保护，
# 不是持久化任务状态；进程重启后的恢复仍以 TaskPlan 快照为准。
_ACTIVE_RESEARCH_TASK_PLAN_IDS: set[str] = set()


# ---------------------------------------------------------------------------
# 单进程同 TaskPlan 并发控制
# ---------------------------------------------------------------------------


class _TaskPlanLockRegistry:
    """当前进程内按 task_plan_id fail-fast 互斥控制请求。

    ``_guard`` 保护锁字典本身，``_locks[task_plan_id]`` 保护某一个业务任务。
    两者不能合并：如果用一把全局锁包住整个 Agent 执行周期，不同 TaskPlan
    也会被不必要地串行化。
    """

    def __init__(self) -> None:
        """创建锁字典以及保护该字典创建/删除操作的短临界区锁。"""

        self._guard = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(self, task_plan_id: str):
        """占用任务；已有持有者时返回 409，而不是排队后重复执行。

        这是 async context manager：进入 ``async with`` 时取锁，无论执行成功、
        异常还是取消，``finally`` 都会释放并从字典删除该锁。
        """

        async with self._guard:
            # setdefault 保证同一 task_plan_id 只共享一把锁。该操作和
            # locked()/acquire() 都放在 _guard 内，避免两个请求同时创建两把锁。
            lock = self._locks.setdefault(task_plan_id, asyncio.Lock())
            if lock.locked():
                raise AgentTaskPlanBusyError("Agent task plan 当前仍在执行")
            # 这里已在 _guard 内确认 lock 未占用，acquire() 不会长时等待。
            await lock.acquire()
        try:
            yield
        finally:
            async with self._guard:
                # 先释放再删除字典引用；下一个请求会为同一 ID 创建新锁。
                lock.release()
                self._locks.pop(task_plan_id, None)

    async def is_locked(self, task_plan_id: str) -> bool:
        """取消请求只读取占用状态，不等待正在运行的任务。

        返回值是查询当时的进程内快照，只用来判断 cancel 是立即清理
        checkpoint，还是让正在运行的 Deep Agent 在安全边界自行清理。
        """

        async with self._guard:
            lock = self._locks.get(task_plan_id)
            return lock is not None and lock.locked()


# ponytail: 当前仅保护单 FastAPI 进程；部署多 Worker 时改为数据库租约/CAS。
_TASK_PLAN_LOCKS = _TaskPlanLockRegistry()


class AgentTaskExecutor:
    """对外保持统一 TaskPlan API，把实际工作交给两个专用执行器。

    Research 和文档任务的内部状态机已被拆出，本类只保留跨两类任务
    必须一致的 API 入口、归属检查、当前 ACL 重建和并发保护。
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
        evidence_evaluator: ResearchEvidenceEvaluator | None = None,
        research_executor: AgenticResearchExecutor | None = None,
        document_executor: DocumentTaskExecutor | None = None,
        capability_service: AgentTaskCapabilityService | None = None,
        prompt_guard=None,
    ) -> None:
        """装配专用执行器；可注入协作者，旧脚本仍可传原有依赖。

        FastAPI 生产依赖层可以显式注入已装配的执行器；测试和兼容脚本
        如果只提供基础组件，则在这里组装最小的 Research ToolLoop -> Worker ->
        Executor 和 DocumentTaskExecutor。
        """

        self._settings = settings
        self._task_plan_store = task_plan_store
        self._capability_service = capability_service
        self._plan_validator = AgentTaskPlanValidator()
        if research_executor is None:
            # Research 三层依赖方向固定：ToolLoop 执行一轮工具，Worker 负责
            # 纠正循环，Executor 负责多 Worker 波次调度和最终综合。
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
                prompt_guard=prompt_guard,
            )
        self._research_executor = research_executor
        # 文档执行器内部再根据 workflow.execution_mode 选择旧 direct Tool Loop
        # 或 Deep Agent 内容生产链；Facade 不参与这些业务细节。
        self._document_executor = document_executor or DocumentTaskExecutor(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            document_management_service=document_management_service,
            tool_permission_service=tool_permission_service,
            tool_audit_service=tool_audit_service,
            task_plan_store=task_plan_store,
        )

    def save_plan(self, plan: AgentTaskPlan | ResearchTaskPlan) -> None:
        """保存等待用户确认的 TaskPlan。

        该方法只保留 Facade 的统一入口，JSON/Markdown 原子写入细节由
        ``AgentTaskPlanStore`` 负责。
        """

        self._task_plan_store.save(plan)

    async def cancel(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """写入任务级取消信号；运行节点会在下一安全边界停止。

        cancel 故意不进入 ``_TASK_PLAN_LOCKS.hold()``。如果它先等待正在运行的
        Agent 释放锁，Agent 就永远看不到 CANCELLED 信号。因此这里立即更新 TaskPlan，
        再由 Middleware/工具边界重读该状态。
        """

        plan = self._task_plan_store.load(task_plan_id)
        # TaskPlan 归属是服务端数据；会话文本或模型输出不能作为取消授权。
        if plan.user_id != user.user_id and not user.has_global_role(
            RoleCode.SYSTEM_ADMIN.value
        ):
            raise ToolPermissionDeniedError("只能取消自己创建的 Agent task plan")
        if isinstance(plan, ResearchTaskPlan):
            if plan.status in {
                AgentTaskPlanStatus.COMPLETED,
                AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
                AgentTaskPlanStatus.CANCELLED,
            }:
                raise AppServiceError("已完成或已取消的 Research TaskPlan 不能再次取消")
            plan.status = AgentTaskPlanStatus.CANCELLED
            plan.error_code = None
            plan.error_message = None
            for worker in plan.progress.workers.values():
                if worker.status in {"pending", "running"}:
                    worker.status = "skipped"
            self._task_plan_store.save(plan)
            return plan
        if plan.status in {
            AgentTaskPlanStatus.COMPLETED,
            AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
            AgentTaskPlanStatus.CANCELLED,
        }:
            raise AppServiceError("已完成或已取消的 Agent task plan 不能再次取消")
        plan.status = AgentTaskPlanStatus.CANCELLED
        plan.error = None
        # 取消后把所有未终态步骤收敛为 SKIPPED，让 React 任务页不再展示
        # 永久 running/waiting_confirmation 的残留步骤。
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
        # 正在运行的 Deep Agent 会在下一安全边界看到 CANCELLED 并自行释放；
        # 未运行的失败任务则在这里立即清理，不让 cancel 被长任务锁阻塞。
        if (
            plan.task_kind == "knowledge_document_management"
            and not await _TASK_PLAN_LOCKS.is_locked(task_plan_id)
        ):
            await self._document_executor.release_agentic_checkpoint(plan)
        return plan

    async def execute_question_decomposition_plan(
        self,
        plan: ResearchTaskPlan,
        user: CurrentUserContext,
        mode: str,
        top_k: int,
        candidate_k: int | None,
        min_score: float,
        filters: RetrievalFilters,
        langchain_config_factory: LangChainConfigFactory | None = None,
        resume: bool = False,
    ) -> ResearchTaskPlan:
        """兼容原入口并委托给 Research TaskPlan 执行器。

        该方法不做新的锁或鉴权，因为正常 confirm/retry 路径已经在
        ``_run_research_controlled()`` 中完成这些控制。保留它是为了不破坏已有调用方。
        """

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
        """执行确认前的文档内容生产/Tool Loop。

        这里的 execute 不等于真实文件写入：它产生 dry-run/变更建议并进入
        ``WAITING_CONFIRMATION``。真实文件、ES 和 Milvus 更新从 ``confirm()`` 进入。
        """

        # 首次 agentic 执行和 /retry、/confirm 共用同一把 task_plan_id 锁，
        # 避免同一任务同时生成两套草稿或更新同一 RuntimeRecord。
        async with _TASK_PLAN_LOCKS.hold(plan.task_plan_id):
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
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """按任务类型恢复最近完整快照。

        公开方法只负责 fail-fast 取锁；必须在锁获取后才重读 TaskPlan，
        否则两个并发 retry 可能都基于取锁前的旧状态做决策。
        """

        async with _TASK_PLAN_LOCKS.hold(task_plan_id):
            return await self._resume_locked(
                task_plan_id,
                user,
                langchain_config_factory=langchain_config_factory,
            )

    async def _resume_locked(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        *,
        langchain_config_factory: LangChainConfigFactory | None,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """在同任务互斥范围内重新读取并恢复最近快照。

        Research 使用 TaskPlan 中的 Worker 结果快照；agentic 文档任务使用
        LangGraph PostgreSQL checkpoint；legacy direct 文档 Tool Loop 使用 ``final_output.checkpoint``。
        三条路径共享当前用户重新鉴权和同任务互斥，但恢复介质不同。
        """

        # 在锁内重读并验证归属，不使用 API 层调用前可能已过期的 plan 对象。
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
            # completed_with_warnings 允许 retry：Research Executor 保留 completed Worker，
            # 只重跑 partial/failed/skipped 和未开始子问题。
            return await self._run_research_controlled(
                plan,
                user,
                langchain_config_factory=langchain_config_factory,
                resume=True,
            )
        if plan.task_kind != "knowledge_document_management":
            raise AppServiceError("当前只支持恢复文档管理 Tool Loop")
        if not user.is_authenticated:
            raise ToolPermissionDeniedError("当前用户身份已失效，拒绝恢复文档计划")
        if plan.status not in {AgentTaskPlanStatus.RUNNING, AgentTaskPlanStatus.FAILED}:
            raise AppServiceError("只有 running 或 failed 的文档 TaskPlan 可以恢复")
        workflow = plan.final_output.get("document_workflow")
        if isinstance(workflow, dict) and workflow.get("execution_mode") == "agentic":
            # 旧 TaskPlan 可能没有 research_policy。兼容默认不允许 Web，避免恢复时
            # 因新默认值而意外扩大外部数据边界。
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
                # source/section 来自已保存策略，用户/部门/全局读权限则从
                # 当前 user 重新构造，不复用 TaskPlan 创建时的旧 ACL。
                filters=self._current_filters(
                    user,
                    source_path=policy.source_path,
                    section_path=policy.section_path,
                ),
                langchain_config_factory=langchain_config_factory,
                resume=True,
            )
        # 非 agentic 文档任务走历史 direct Tool Loop 轮次快照，不使用
        # Deep Agent 的 thread_id/StateBackend checkpoint。
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
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """确认计划，并在执行前使用当前身份和权限重新构造事实。

        confirm 和 resume 一样先占用 task_plan_id，但业务含义不同：Research confirm
        启动经用户确认的研究计划；Document confirm 则会进入高风险的真实文件/索引写入。
        """

        async with _TASK_PLAN_LOCKS.hold(task_plan_id):
            return await self._confirm_locked(
                task_plan_id,
                user,
                langchain_config_factory=langchain_config_factory,
            )

    async def _confirm_locked(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        *,
        langchain_config_factory: LangChainConfigFactory | None,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """在同任务互斥范围内重新读取、鉴权并执行确认。

        只有 ``WAITING_CONFIRMATION`` 可以进入此分支。状态检查放在锁内，保证
        第一个 confirm 更新任务后，第二个并发请求不会继续使用旧状态。
        """

        plan = self._load_owned_plan(task_plan_id, user)
        if plan.status != AgentTaskPlanStatus.WAITING_CONFIRMATION:
            raise AppServiceError("Agent task plan 状态不是 waiting_confirmation，拒绝执行")
        if plan.task_kind == "question_decomposition":
            if not isinstance(plan, ResearchTaskPlan):
                raise AppServiceError("Research TaskPlan Schema 不受支持")
            if not user.is_authenticated:
                raise ToolPermissionDeniedError("当前用户身份已失效，拒绝执行研究计划")
            return await self._run_research_controlled(
                plan,
                user,
                langchain_config_factory=langchain_config_factory,
                resume=False,
            )
        if plan.task_kind == "knowledge_document_management":
            if not user.is_authenticated:
                raise ToolPermissionDeniedError("当前用户身份已失效，拒绝执行文档计划")
            # DocumentTaskExecutor.confirm() 会再次验证冻结的 dry-run、候选 doc_id、
            # 路径、base_sha256 和当前工具权限；Router/Planner/LLM 输出不直接成为写入事实。
            return await self._document_executor.confirm(plan=plan, user=user)
        raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

    def _load_owned_plan(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """从持久化 Store 重读 TaskPlan，并校验当前请求用户的任务归属。

        返回的是锁内最新 TaskPlan 快照。普通用户只能操作自己创建的任务，
        ``admin`` 可执行管理操作；任务归属不从请求体或会话文本中接受。
        """

        plan = self._task_plan_store.load(task_plan_id)
        if plan.user_id != user.user_id and not user.has_global_role(
            RoleCode.SYSTEM_ADMIN.value
        ):
            raise ToolPermissionDeniedError("只能操作自己创建的 Agent task plan")
        return plan

    async def _run_research_controlled(
        self,
        plan: ResearchTaskPlan,
        user: CurrentUserContext,
        *,
        langchain_config_factory: LangChainConfigFactory | None,
        resume: bool,
    ) -> ResearchTaskPlan:
        """使用保存的 ResearchPolicy 和当前 ACL 启动或恢复 Research Executor。

        ``_ACTIVE_RESEARCH_TASK_PLAN_IDS`` 保护当前进程内的 Research 重入，``finally``
        保证无论 Worker 成功、失败还是取消，活动标记都不会永久残留。
        """

        task_plan_id = plan.task_plan_id
        if task_plan_id in _ACTIVE_RESEARCH_TASK_PLAN_IDS:
            raise AppServiceError("研究 TaskPlan 当前仍在执行，不能重复确认或恢复")
        policy = plan.research_policy
        await self._refresh_research_capability(plan, user)
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
            # discard 在 ID 已被移除时也不抛错，适合异常/取消统一收尾。
            _ACTIVE_RESEARCH_TASK_PLAN_IDS.discard(task_plan_id)

    async def _refresh_research_capability(
        self,
        plan: ResearchTaskPlan,
        user: CurrentUserContext,
    ) -> None:
        """确认/恢复时按当前 RBAC、Grant、Web 配置重新验证整份 Plan。"""

        if self._capability_service is None:
            raise AgentTaskSourceUnavailableError("Research Capability Service 未配置")
        capability = await self._capability_service.resolve_research(
            user=user,
            dataset_id=plan.research_policy.dataset_id,
            allow_direct_web=plan.research_policy.allow_direct_web,
            allow_web_fallback=plan.research_policy.allow_web_fallback,
            required_source_types=plan.research_policy.required_source_types,
        )
        candidate = AgentTaskPlannerCandidate(
            requirements=plan.requirements,
            sub_questions=[
                ResearchTaskSubQuestionCandidate.model_validate(
                    item.model_dump(exclude={"web_usage"})
                )
                for item in plan.sub_questions
            ],
        )
        issues = self._plan_validator.validate_formal(
            candidate,
            plan.sub_questions,
            capability,
            required_source_types=plan.research_policy.required_source_types,
        )
        if any(item.severity == "error" for item in issues):
            raise AgentTaskSourceUnavailableError(
                "当前权限、Dataset 或 Web 能力已无法满足这份 Research TaskPlan"
            )
        plan.capability_snapshot = capability

    @staticmethod
    def _current_filters(
        user: CurrentUserContext,
        *,
        source_path: str | None = None,
        section_path: list[str] | None = None,
    ) -> RetrievalFilters:
        """将当前认证用户转换为 Retriever 可执行的 ACL filters。

        ``source_path/section_path`` 可以继承用户确认的 ResearchPolicy 范围；
        user_id、department_codes 和 ``can_read_all`` 必须始终从确认/恢复时的
        ``CurrentUserContext`` 重新计算，不使用 TaskPlan 创建时的旧 ACL。
        """

        # system_admin 或显式 knowledge:read:all 可跨部门读取；否则
        # Retriever 必须使用 user_id/department_codes/allow_public 实施数据层过滤。
        return RetrievalFilters(
            source_path=source_path,
            section_path=section_path or [],
            user_id=user.user_id,
            department_codes=list(user.department_codes),
            can_read_all=(
                user.has_global_role(RoleCode.SYSTEM_ADMIN.value)
                or user.has_global_permission(PermissionCode.KNOWLEDGE_READ_ALL.value)
            ),
            allow_public=True,
        )


__all__ = ["AgentTaskExecutor", "AgentTaskPlanStore"]
