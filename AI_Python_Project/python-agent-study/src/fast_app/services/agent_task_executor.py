from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fast_app.agents.rag_agent_tools import retrieve_knowledge_docs
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentTaskPlan,
    AgentTaskPlanStatus,
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
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_approval_service import AgentToolApprovalService
from fast_app.services.agent_tool_permission_service import (
    AgentToolPermissionService,
    tool_name_for_document_operation,
)
from fast_app.services.exceptions import AppServiceError
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.rag_pipeline_service import build_rag_context, build_top_doc_ids


class AgentTaskPlanStore:
    """runtime JSON task plan store."""

    def __init__(self, settings: Settings) -> None:
        self._task_plan_dir = Path(settings.agent_task_plan_dir)

    def save(self, plan: AgentTaskPlan) -> None:
        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        plan.updated_at = datetime.now(UTC)
        path = self._path_for_new_plan(plan)
        path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def load(self, task_plan_id: str) -> AgentTaskPlan:
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
        existing = sorted(self._task_plan_dir.glob(f"*_{plan.task_plan_id}.json"))
        if existing:
            return existing[-1]
        created = plan.created_at.strftime("%Y%m%d_%H%M%S")
        return self._task_plan_dir / f"{created}_{plan.task_plan_id}.json"


class AgentTaskExecutor:
    """执行 v1 白名单 AgentTaskPlan。"""

    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        document_management_service: KnowledgeDocumentManagementService,
        tool_permission_service: AgentToolPermissionService,
        tool_audit_service: AgentToolAuditService,
        tool_approval_service: AgentToolApprovalService,
        task_plan_store: AgentTaskPlanStore,
    ) -> None:
        self._settings = settings
        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        self._llm_client = llm_client
        self._document_management_service = document_management_service
        self._tool_permission_service = tool_permission_service
        self._tool_audit_service = tool_audit_service
        self._tool_approval_service = tool_approval_service
        self._task_plan_store = task_plan_store

    # 任务执行，构造plan的步骤状态，执行知识检索和报告生成，并处理文档创建的权限和审批逻辑。
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
        if plan.task_kind != "knowledge_report_to_document":
            raise AppServiceError(f"不支持的 Agent task kind: {plan.task_kind}")

        plan.user_id = plan.user_id or user.user_id
        plan.status = AgentTaskPlanStatus.RUNNING
        self._task_plan_store.save(plan)

        try:
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
        target_departments = list(
            action_result.preview.permission_metadata.get("allowed_departments", [])
            or []
        )
        requires_approval = _requires_approval(
            policy=self._settings.agent_tool_execution_policy,
            risk_level=action_result.preview.risk_level,
        ) or self._settings.agent_document_tools_dry_run_only
        context = AgentToolCallContext(
            tool_name=tool_name_for_document_operation(action_request.operation),
            operation=action_request.operation,
            risk_level=action_result.preview.risk_level,
            target_path=action_request.target_path,
            target_department_codes=target_departments,
            requires_confirmation=requires_approval,
            metadata={"source": "rag_agent.task_executor"},
        )
        decision = await self._tool_permission_service.authorize(user=user, context=context)
        await self._tool_audit_service.record_decision(
            user=user,
            context=context,
            decision=decision,
        )
        if decision.action == AgentToolPermissionAction.DENY:
            step.status = AgentToolStepStatus.FAILED
            step.error = decision.reason
            plan.status = AgentTaskPlanStatus.FAILED
            plan.error = decision.reason
            return

        if decision.action in {
            AgentToolPermissionAction.APPROVAL_REQUIRED,
            AgentToolPermissionAction.REQUIRE_CONFIRMATION,
        }:
            created = await self._tool_approval_service.create_approval(
                user=user,
                tool_name=context.tool_name,
                action_request=action_request,
                action_result=action_result,
                permission_decision=decision,
            )
            step.status = AgentToolStepStatus.WAITING_APPROVAL
            step.requires_approval = True
            step.approval_id = created.approval.approval_id
            step.output = {
                "approval_id": created.approval.approval_id,
                "approval_kind": created.approval.approval_kind,
                "markdown_path": created.markdown_path,
                "json_path": created.json_path,
                "confirmation_text": created.confirmation_text,
                "action_request_content": report_content,
            }
            plan.status = AgentTaskPlanStatus.WAITING_APPROVAL
            plan.final_output = {
                "approval_id": created.approval.approval_id,
                "target_path": plan.target_path,
                "status": plan.status.value,
            }
            return

        if (
            self._settings.agent_tool_execution_policy == "risk_based"
            and not self._settings.agent_document_tools_dry_run_only
        ):
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

        step.status = AgentToolStepStatus.WAITING_APPROVAL
        plan.status = AgentTaskPlanStatus.WAITING_APPROVAL


def _find_step(plan: AgentTaskPlan, tool_name: str) -> AgentToolStep:
    for step in plan.steps:
        if step.tool_name == tool_name:
            return step
    raise AppServiceError(f"Agent task plan 缺少步骤: {tool_name}")


def _infer_departments_from_path(target_path: str) -> list[str]:
    first = target_path.replace("\\", "/").split("/", 1)[0].strip()
    return [first] if first else []


def _requires_approval(
    policy: str,
    risk_level: KnowledgeDocumentRiskLevel,
) -> bool:
    if policy in {"approval_required", "dry_run_only"}:
        return True
    return risk_level in {
        KnowledgeDocumentRiskLevel.HIGH,
        KnowledgeDocumentRiskLevel.CRITICAL,
    }


__all__ = ["AgentTaskExecutor", "AgentTaskPlanStore"]
