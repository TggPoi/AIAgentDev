"""Deep Agents 文档链路最小回归；默认离线，RUN_REAL_LLM=1 时调用真实 Qwen。"""

from __future__ import annotations

import asyncio
import os
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings, get_settings
from fast_app.domain.agent_task_plan import AgentResearchPolicy, AgentTaskPlanStatus
from fast_app.domain.agent_tool_permissions import (
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    PermissionCode,
)
from fast_app.domain.document_workflow import (
    DocumentChangeProposal,
    DocumentDeliverable,
    DocumentDraftResult,
    DocumentResearchResult,
    DocumentReviewResult,
    DocumentWorkflowDecision,
    DocumentWorkflowResult,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionResult,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.deep_document_agent import (
    DeepDocumentAgent,
    DeepDocumentAgentRunResult,
    DocumentReadSnapshot,
)
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from langchain_core.callbacks import AsyncCallbackHandler


ORIGINAL = "# Damage Rules\n\nBase damage is attack minus defense.\n"
UPDATED = "# Damage Rules\n\nFinal damage is max(1, attack - defense).\n"
DOC_ID = "doc_damage_rules"
SOURCE_PATH = "development/damage-rules.md"


class RealModelTraceHandler(AsyncCallbackHandler):
    """真实测试只统计模型调用数，不输出可能包含文档内容的 Tool 参数。"""

    def __init__(self) -> None:
        self.call_count = 0

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.call_count += 1


class FakeRetriever(BaseRetriever):
    async def retrieve(self, query: str, options: RetrievalOptions):
        return [
            RetrievedDoc(
                id="chunk_damage_rules",
                content=ORIGINAL,
                score=0.95,
                source="fake",
                title="Damage Rules",
                metadata={"doc_id": DOC_ID, "source_path": SOURCE_PATH},
            )
        ]


class FakeManagementService:
    def __init__(self) -> None:
        self.content = ORIGINAL

    def read_document_content(self, target_path: str) -> str:
        assert target_path == SOURCE_PATH
        return self.content

    async def plan_action(self, request, user):
        before_hash = sha256(self.content.encode("utf-8")).hexdigest()
        after_hash = (
            sha256((request.content or "").encode("utf-8")).hexdigest()
            if request.content is not None
            else None
        )
        return KnowledgeDocumentActionResult(
            operation=request.operation,
            target_path=request.target_path,
            dry_run=True,
            executed=False,
            preview=KnowledgeDocumentActionPreview(
                operation=request.operation,
                target_path=request.target_path,
                normalized_path=request.target_path,
                exists_before=True,
                risk_level=KnowledgeDocumentRiskLevel.HIGH,
                affected_doc_id=DOC_ID,
                affected_chunk_count=1,
                before_hash=before_hash,
                after_hash=after_hash,
                permission_metadata={"allowed_departments": ["development"]},
                requires_confirmation=True,
            ),
            message="dry-run",
        )


class FakePermissionService:
    async def authorize(self, user, context):
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            allowed=True,
            reason="test",
            risk_level=context.risk_level,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE],
            target_department_codes=context.target_department_codes,
            requires_confirmation=True,
        )


class FakeAuditService:
    async def record_decision(self, **kwargs):
        return None

    async def record_execution(self, **kwargs):
        return None


class StubSupervisor:
    async def decide(self, **kwargs):
        return build_decision()


class StubDeepAgent:
    async def run(self, **kwargs):
        review = DocumentReviewResult(
            deliverable_id="damage_update",
            verdict="approved",
            confidence=0.95,
        )
        proposal = DocumentChangeProposal(
            deliverable_id="damage_update",
            operation="update",
            candidate_doc_id=DOC_ID,
            candidate_source_path=SOURCE_PATH,
            base_sha256=sha256(ORIGINAL.encode("utf-8")).hexdigest(),
            content=UPDATED,
            reason="test update",
            selection_reason="ACL candidate",
            review=review,
        )
        return DeepDocumentAgentRunResult(
            workflow=DocumentWorkflowResult(
                research_results=[
                    DocumentResearchResult(
                        deliverable_id="damage_update",
                        status="completed",
                        findings=["minimum damage is required"],
                    )
                ],
                draft_results=[
                    DocumentDraftResult(
                        deliverable_id="damage_update",
                        operation="update",
                        candidate_doc_id=DOC_ID,
                        candidate_source_path=SOURCE_PATH,
                        base_sha256=proposal.base_sha256,
                        content=UPDATED,
                    )
                ],
                review_results=[review],
                approved_changes=[proposal],
                used_tools=["knowledge_retrieval", "knowledge_document_read"],
            ),
            candidates={
                DOC_ID: {
                    "doc_id": DOC_ID,
                    "source_path": SOURCE_PATH,
                    "title": "Damage Rules",
                }
            },
            read_snapshots={
                DOC_ID: DocumentReadSnapshot(
                    doc_id=DOC_ID,
                    source_path=SOURCE_PATH,
                    content=ORIGINAL,
                    sha256=proposal.base_sha256 or "",
                )
            },
        )


def build_decision() -> DocumentWorkflowDecision:
    return DocumentWorkflowDecision(
        execution_mode="agentic",
        objective="Update damage calculation documentation",
        deliverables=[
            DocumentDeliverable(
                deliverable_id="damage_update",
                title="Damage Rules Update",
                operation="update",
                target_hint=SOURCE_PATH,
                objective="Add an explicit minimum damage rule",
            )
        ],
        web_policy="disabled",
        reason="Requires research, writing and independent review",
    )


def build_user() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="tool_admin",
        is_authenticated=True,
        auth_source="jwt",
        role="admin",
        permissions=["*"],
        department_codes=["development"],
        primary_department_code="development",
    )


async def test_deterministic_boundary() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_DOCUMENT_TOOLS_ENABLED=True,
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Update damage rules after reviewing related documents",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        store.save(plan)
        management = FakeManagementService()
        executor = DocumentTaskExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=management,  # type: ignore[arg-type]
            tool_permission_service=FakePermissionService(),  # type: ignore[arg-type]
            tool_audit_service=FakeAuditService(),  # type: ignore[arg-type]
            task_plan_store=store,
            supervisor_agent=StubSupervisor(),  # type: ignore[arg-type]
            deep_document_agent=StubDeepAgent(),  # type: ignore[arg-type]
        )
        result = await executor.execute(
            plan=plan,
            user=build_user(),
            mode="hybrid",
            top_k=5,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(can_read_all=True),
        )
        assert result.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        assert len(result.steps) == 1
        assert result.steps[0].output["preview"]["before_hash"] == sha256(
            ORIGINAL.encode("utf-8")
        ).hexdigest()
        assert result.steps[0].output["action_request"]["content"] == UPDATED
        assert management.content == ORIGINAL, "dry-run 前不得修改真实文档"
        assert any(
            event.get("event") == "agent_task_document_action_prepared"
            for event in result.final_output["document_progress"]["events"]
        )


async def test_real_deep_agent() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = get_settings().model_copy(
            update={
                "agent_task_plan_dir": temp_dir,
                "agent_max_steps": 8,
                "agent_max_tool_calls": 20,
                "agent_document_worker_timeout_seconds": float(
                    os.getenv("REAL_LLM_WORKER_TIMEOUT_SECONDS", "180")
                ),
            }
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Review the damage rules and update the document with an explicit minimum damage rule.",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        store.save(plan)
        agent = DeepDocumentAgent(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=FakeManagementService(),  # type: ignore[arg-type]
            task_plan_store=store,
        )
        trace_handler = RealModelTraceHandler()
        result = await agent.run(
            plan=plan,
            decision=build_decision(),
            user=build_user(),
            mode="hybrid",
            top_k=5,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(can_read_all=True),
            langchain_config={"callbacks": [trace_handler]},
        )
        assert result.workflow.approved_changes, result.workflow.model_dump(mode="json")
        proposal = result.workflow.approved_changes[0]
        assert proposal.candidate_doc_id == DOC_ID
        assert proposal.base_sha256 == sha256(ORIGINAL.encode("utf-8")).hexdigest()
        assert "knowledge_document_read" in result.workflow.used_tools
        latest = store.load(plan.task_plan_id)
        events = latest.final_output["document_progress"]["events"]
        assert any(
            event.get("event") == "agent_task_document_subagent_started"
            for event in events
        )
        assert any(
            event.get("event") == "agent_task_document_subagent_completed"
            for event in events
        )
        # Coordinator 与三个显式 SubAgent 各自受同一模型调用上限约束。
        assert trace_handler.call_count <= settings.agent_max_tool_calls * 4
        print(f"real_model_call_count={trace_handler.call_count}", flush=True)


async def main() -> None:
    await test_deterministic_boundary()
    if os.getenv("RUN_REAL_LLM") == "1":
        await test_real_deep_agent()
    print("deep_document_agent_workflow=passed")


if __name__ == "__main__":
    asyncio.run(main())
