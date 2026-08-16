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
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_execution import (
    TaskPlanCommandReplay,
    TaskPlanOperation,
    TaskPlanWorkloadType,
)
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
from fast_app.services.agent_tasks.agent_task_lease_manager import (
    AgentTaskLeaseManager,
    build_request_hash,
)
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
    AgentTaskPlanLeaseLostError,
    AgentTaskPlanVersionConflictError,
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
        """只读查询当前进程内 task_plan_id 的占用状态，不等待运行中的任务。

        返回值是查询瞬间的进程内快照，且只反映当前 Worker 进程的状态：任务
        在另一个 Worker 上运行时这里必然返回 False。当前 cancel 路径不调用本
        方法：cancel 直接走数据库原子取消（SELECT FOR UPDATE + 失效 fencing
        token），不在取消路径上删除 checkpoint；checkpoint 由终态路径或维护
        命令在租约/fence 校验下清理。任何未来调用方都不得把破坏性动作（如
        删除 checkpoint）绑定到这个会过期的进程内快照上。
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
        lease_manager: AgentTaskLeaseManager,
        evidence_evaluator: ResearchEvidenceEvaluator | None = None,
        research_executor: AgenticResearchExecutor | None = None,
        document_executor: DocumentTaskExecutor | None = None,
        capability_service: AgentTaskCapabilityService | None = None,
        prompt_guard=None,
    ) -> None:
        """装配专用执行器；可注入协作者，旧脚本仍可传原有依赖。

        FastAPI 生产依赖层可以显式注入已装配的执行器；测试和兼容脚本
        如果只提供基础组件，则在这里组装最小的 Research ToolLoop -> Worker ->
        Executor 和 DocumentTaskExecutor。数据库租约管理器是 execute/confirm/
        retry/cancel 控制协议的必需依赖。
        """

        self._settings = settings
        self._task_plan_store = task_plan_store
        self._lease_manager = lease_manager
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

    async def save_plan(self, plan: AgentTaskPlan | ResearchTaskPlan) -> None:
        """保存等待用户确认的 TaskPlan。

        该方法只保留 Facade 的统一入口，数据库写入与审查导出细节由
        ``AgentTaskPlanStore`` 负责。同一 task_plan_id 重复创建会返回稳定冲突。
        """

        await self._task_plan_store.create(plan)

    async def cancel(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        idempotency_key: str,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """写入任务级取消信号；运行节点会在下一安全边界停止。

        cancel 故意不进入 ``_TASK_PLAN_LOCKS.hold()``。如果它先等待正在运行的
        Agent 释放锁，Agent 就永远看不到 CANCELLED 信号。这里通过数据库原子
        cancel（SELECT FOR UPDATE + 失效 fencing token）立即更新 TaskPlan，再由
        Middleware/工具边界重读该状态；checkpoint 由终态路径或维护命令清理，
        不在取消路径上直接删除。
        """

        return await self._task_plan_store.cancel(
            task_plan_id=task_plan_id,
            user=user,
            idempotency_key=idempotency_key,
            request_hash=build_request_hash(
                task_plan_id=task_plan_id,
                operation="cancel",
                payload={},
            ),
        )

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

        首次创建计划与执行都包在数据库租约内；幂等键由服务端稳定 TaskPlan ID
        生成，同一 TaskPlan 的重复 execute 会命中同一条幂等命令（失败后同键
        复活重试，见 Repository 的修订语义）。
        """

        try:
            await self._task_plan_store.create(plan)
        except AgentTaskPlanVersionConflictError:
            # 同一 TaskPlan 的请求重放交给 execute 命令幂等记录处理。
            pass

        # 首次 agentic 执行和 /retry、/confirm 共用同一把 task_plan_id 锁，
        # 避免同一任务同时生成两套草稿或更新同一 RuntimeRecord。
        async with _TASK_PLAN_LOCKS.hold(plan.task_plan_id):
            result = await self._run_with_database_lease(
                task_plan_id=plan.task_plan_id,
                operation="execute",
                idempotency_key=f"execute:{plan.task_plan_id}",
                request_payload={},
                allowed_statuses={AgentTaskPlanStatus.CREATED},
                workload_type="document",
                runner=lambda current: self._document_executor.execute(
                    plan=current,
                    user=user,
                    mode=mode,
                    top_k=top_k,
                    candidate_k=candidate_k,
                    min_score=min_score,
                    filters=filters,
                    langchain_config_factory=langchain_config_factory,
                ),
            )
        if not isinstance(result, AgentTaskPlan):
            raise AppServiceError("Document execute 返回了错误的 TaskPlan 类型")
        return result

    async def _run_with_database_lease(
        self,
        *,
        task_plan_id: str,
        operation: TaskPlanOperation,
        idempotency_key: str,
        request_payload: dict[str, Any],
        allowed_statuses: set[AgentTaskPlanStatus],
        workload_type: TaskPlanWorkloadType,
        runner: Callable[
            [AgentTaskPlan | ResearchTaskPlan],
            Awaitable[AgentTaskPlan | ResearchTaskPlan],
        ],
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """通用数据库租约执行骨架：重放、心跳、事实重读、成功释放、异常收尾。

        Research/Document 业务仍留在原专用执行器；本方法只负责控制协议。
        """

        async with self._lease_manager.hold(
            task_plan_id=task_plan_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
            allowed_statuses=allowed_statuses,
            workload_type=workload_type,
        ) as acquired:
            if isinstance(acquired, TaskPlanCommandReplay):
                return self._task_plan_store.from_snapshot(
                    dict(acquired.response_json)
                )
            lease = acquired
            try:
                current = await self._task_plan_store.load(task_plan_id)
                result = await runner(current)
                lease.assert_active()
                # 先通知心跳停止续租，再释放数据库租约，避免成功释放与
                # heartbeat UPDATE 竞态产生假的 lease-lost。
                lease.closing.set()
                try:
                    await self._task_plan_store.repository.finish_success(
                        lease=lease,
                        response_json=result.model_dump(mode="json"),
                    )
                except AgentTaskPlanLeaseLostError:
                    # 修订：用户取消可能恰好在 runner 返回后发生：cancel_atomic
                    # 已经递增 fence token 并清空租约，finish_success 必然不命中。
                    # 此时数据库状态已经是 cancelled，取消已经收敛，不应把成功的
                    # 取消误报为执行失败。
                    latest = await self._task_plan_store.load(task_plan_id)
                    if latest.status != AgentTaskPlanStatus.CANCELLED:
                        raise
                    return latest
                return result
            except BaseException as exc:
                lease.closing.set()
                if isinstance(exc, AgentTaskPlanLeaseLostError):
                    # heartbeat 可能比最终 finish_success 更早发现 cancel_atomic
                    # 已经撤销当前租约。此时同样以数据库终态为准，避免把一次
                    # 已成功持久化的取消继续收尾成 failed 或向客户端误报失败。
                    latest = await self._task_plan_store.load(task_plan_id)
                    if latest.status == AgentTaskPlanStatus.CANCELLED:
                        return latest
                # 专用执行器通常会先保存 failed；这里作为租约模块的最终兜底，
                # 收敛发生在 Supervisor 等专用 try/except 之外的异常，避免任务
                # 留在活跃状态但命令已经失败并释放租约。
                try:
                    latest = await self._task_plan_store.load(task_plan_id)
                    if latest.status in {
                        AgentTaskPlanStatus.CREATED,
                        AgentTaskPlanStatus.PREPARING_CONFIRMATION,
                        AgentTaskPlanStatus.EXECUTING_CONFIRMED,
                    }:
                        failed_from = latest.status
                        latest.status = AgentTaskPlanStatus.FAILED
                        if isinstance(latest, ResearchTaskPlan):
                            latest.error_code = getattr(
                                exc, "error_code", type(exc).__name__
                            )
                            latest.error_message = str(exc)
                        else:
                            latest.error = f"{type(exc).__name__}: {exc}"
                            latest.failure_phase = failed_from.value
                            latest.final_output["status"] = latest.status.value
                        await self._task_plan_store.save(latest)
                except (
                    AgentTaskPlanLeaseLostError,
                    AgentTaskPlanVersionConflictError,
                ):
                    # cancel 或其他新代际执行者已经取得权威事实时，旧执行者只做
                    # 命令/容量释放，不能用兜底状态覆盖新快照。
                    pass
                await self._task_plan_store.repository.finish_failure(
                    lease=lease,
                    error_code=getattr(exc, "error_code", type(exc).__name__),
                    error_message=str(exc),
                )
                raise

    async def resume(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
        idempotency_key: str,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """按任务类型恢复最近完整快照。

        公开方法只负责 fail-fast 取锁；必须在锁获取后才重读 TaskPlan，
        否则两个并发 retry 可能都基于取锁前的旧状态做决策。数据库租约
        跨进程保证同一任务只有一个恢复执行者。
        """

        async with _TASK_PLAN_LOCKS.hold(task_plan_id):
            hint = await self._load_owned_plan(task_plan_id, user)
            is_research = isinstance(hint, ResearchTaskPlan)
            allowed = (
                {
                    AgentTaskPlanStatus.EXECUTING_CONFIRMED,
                    AgentTaskPlanStatus.FAILED,
                    AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
                }
                if is_research
                else {
                    AgentTaskPlanStatus.PREPARING_CONFIRMATION,
                    AgentTaskPlanStatus.EXECUTING_CONFIRMED,
                    AgentTaskPlanStatus.FAILED,
                }
            )

            async def run(_current):
                return await self._resume_locked(
                    task_plan_id,
                    user,
                    langchain_config_factory=langchain_config_factory,
                )

            return await self._run_with_database_lease(
                task_plan_id=task_plan_id,
                operation="retry",
                idempotency_key=idempotency_key,
                request_payload={},
                allowed_statuses=allowed,
                workload_type="research" if is_research else "document",
                runner=run,
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
        plan = await self._load_owned_plan(task_plan_id, user)
        if plan.task_kind == "question_decomposition":
            if plan.status not in {
                AgentTaskPlanStatus.EXECUTING_CONFIRMED,
                AgentTaskPlanStatus.FAILED,
                AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS,
            }:
                raise AppServiceError(
                    "研究 TaskPlan 只有 executing_confirmed、failed 或 "
                    "completed_with_warnings 可以重试"
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
        if plan.status not in {
            AgentTaskPlanStatus.PREPARING_CONFIRMATION,
            AgentTaskPlanStatus.EXECUTING_CONFIRMED,
            AgentTaskPlanStatus.FAILED,
        }:
            raise AppServiceError(
                "只有 preparing_confirmation、executing_confirmed 或 failed 的文档 "
                "TaskPlan 可以恢复"
            )
        failed_phase = plan.failure_phase
        if (
            plan.status == AgentTaskPlanStatus.EXECUTING_CONFIRMED
            or failed_phase == AgentTaskPlanStatus.EXECUTING_CONFIRMED.value
        ):
            plan.status = AgentTaskPlanStatus.EXECUTING_CONFIRMED
            plan.error = None
            plan.failure_phase = None
            plan.final_output["status"] = plan.status.value
            await self._task_plan_store.save(plan)
            return await self._document_executor.confirm(plan=plan, user=user)
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
        idempotency_key: str,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """确认计划，并在执行前使用当前身份和权限重新构造事实。

        confirm 和 resume 一样先占用 task_plan_id，但业务含义不同：Research confirm
        启动经用户确认的研究计划；Document confirm 则会进入高风险的真实文件/索引写入。
        数据库租约 + 幂等命令保证多 Worker 下同一确认只执行一次真实副作用。
        """

        async with _TASK_PLAN_LOCKS.hold(task_plan_id):
            hint = await self._load_owned_plan(task_plan_id, user)
            workload_type: TaskPlanWorkloadType = (
                "research"
                if hint.task_kind == "question_decomposition"
                else "document"
            )

            async def run(current):
                # 租约内再次执行归属、身份、状态和当前 ACL 校验。
                current = await self._load_owned_plan(task_plan_id, user)
                if current.status != AgentTaskPlanStatus.WAITING_CONFIRMATION:
                    raise AppServiceError(
                        "Agent task plan 状态不是 waiting_confirmation，拒绝执行"
                    )
                if not user.is_authenticated:
                    raise ToolPermissionDeniedError(
                        "当前用户身份已失效，拒绝执行计划"
                    )
                current.status = AgentTaskPlanStatus.EXECUTING_CONFIRMED
                if isinstance(current, ResearchTaskPlan):
                    current.error_code = None
                    current.error_message = None
                else:
                    current.error = None
                    current.failure_phase = None
                    current.final_output["status"] = current.status.value
                # 人工确认先持久化为数据库权威状态，随后执行器和真实副作用
                # 边界都会再次验证 executing_confirmed。
                await self._task_plan_store.save(current)
                if isinstance(current, ResearchTaskPlan):
                    return await self._run_research_controlled(
                        current,
                        user,
                        langchain_config_factory=langchain_config_factory,
                        resume=False,
                    )
                if current.task_kind == "knowledge_document_management":
                    # DocumentTaskExecutor.confirm() 会再次验证冻结的 dry-run、
                    # 候选 doc_id、路径、base_sha256 和当前工具权限；
                    # Router/Planner/LLM 输出不直接成为写入事实。
                    return await self._document_executor.confirm(
                        plan=current, user=user
                    )
                raise AppServiceError(f"不支持的 Agent task kind: {current.task_kind}")

            return await self._run_with_database_lease(
                task_plan_id=task_plan_id,
                operation="confirm",
                idempotency_key=idempotency_key,
                request_payload={"confirmed": True},
                allowed_statuses={AgentTaskPlanStatus.WAITING_CONFIRMATION},
                workload_type=workload_type,
                runner=run,
            )

    async def _load_owned_plan(
        self,
        task_plan_id: str,
        user: CurrentUserContext,
    ) -> AgentTaskPlan | ResearchTaskPlan:
        """从持久化 Store 重读 TaskPlan，并校验当前请求用户的任务归属。

        返回的是锁内最新 TaskPlan 快照。普通用户只能操作自己创建的任务，
        ``admin`` 可执行管理操作；任务归属不从请求体或会话文本中接受。
        """

        plan = await self._task_plan_store.load(task_plan_id)
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

        同任务互斥由外层 ``_TASK_PLAN_LOCKS``（进程内快速失败）与数据库租约
        （跨进程权威）共同保证，不再维护独立的进程内活动集合。
        """

        task_plan_id = plan.task_plan_id
        policy = plan.research_policy
        await self._refresh_research_capability(plan, user)
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
            dataset_scope=plan.research_policy.dataset_scope,
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


__all__ = ["AgentTaskExecutor"]
