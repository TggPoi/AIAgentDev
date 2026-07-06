from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus, AgentToolStepStatus
from fast_app.domain.agent_tool_permissions import (
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    PermissionCode,
)
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentRiskLevel
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tool_approval_service import AgentToolApprovalService
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


class FakeRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                id="task_doc_001",
                content=f"{query} 的知识库资料。",
                score=0.9,
                source="fake",
            )
        ]


class FakeLLMClient(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        return "报告正文来自 summarize_report step，引用了检索资料。"

    async def stream(
        self,
        query: str,
        context: RagContext,
    ) -> AsyncGenerator[str, None]:
        yield await self.generate(query, context)


class FakePermissionService:
    async def authorize(self, user, context):
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.APPROVAL_REQUIRED,
            allowed=True,
            reason="测试：文档创建需要 approval",
            risk_level=KnowledgeDocumentRiskLevel.MEDIUM,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE],
            missing_permissions=[],
            target_department_codes=context.target_department_codes,
            requires_confirmation=True,
        )


class FakeAuditService:
    async def record_decision(self, **kwargs):
        return None


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kb = root / "kb"
        kb.mkdir()
        (kb / ".permission-rules.json").write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "path_prefix": "development",
                            "visibility": "department",
                            "allowed_departments": ["development"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        settings = Settings(
            OPENAI_API_KEY="",
            KNOWLEDGE_BASE_DIR=kb.as_posix(),
            AGENT_DOCUMENT_TOOLS_ENABLED=True,
            AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY=True,
            AGENT_TOOL_EXECUTION_POLICY="approval_required",
            AGENT_TOOL_APPROVAL_DIR=(root / "approvals").as_posix(),
            AGENT_TASK_PLAN_DIR=(root / "task-plans").as_posix(),
        )
        user = CurrentUserContext(
            user_id="task-user",
            is_authenticated=True,
            role="user",
            permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value],
            department_codes=["development"],
        )
        planner = AgentTaskPlanner(settings=settings)
        query = "请你查询混合检索资料，生成一份报告，并保存到 development/task-report.md"
        plan = await planner.plan(query=query, user_id=user.user_id)
        assert plan is not None
        assert plan.task_kind == "knowledge_report_to_document"
        assert [step.tool_name for step in plan.steps] == [
            "knowledge_retrieval",
            "summarize_report",
            "knowledge_document_create",
        ]

        single_tool_query = "新增 development/single.md 内容是：# 单工具"
        assert await planner.plan(query=single_tool_query, user_id=user.user_id) is None

        store = AgentTaskPlanStore(settings=settings)
        executor = AgentTaskExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLMClient(),
            document_management_service=KnowledgeDocumentManagementService(settings=settings),
            tool_permission_service=FakePermissionService(),
            tool_audit_service=FakeAuditService(),
            tool_approval_service=AgentToolApprovalService(settings=settings),
            task_plan_store=store,
        )
        executed = await executor.execute(
            plan=plan,
            user=user,
            mode="hybrid",
            top_k=1,
            candidate_k=1,
            min_score=0.0,
            filters=RetrievalFilters(department_codes=["development"]),
        )

        assert executed.status == AgentTaskPlanStatus.WAITING_APPROVAL
        create_step = executed.steps[-1]
        assert create_step.status == AgentToolStepStatus.WAITING_APPROVAL
        assert create_step.approval_id
        assert not (kb / "development" / "task-report.md").exists()

        report_content = executed.steps[1].output["content"]
        approval_files = list((root / "approvals").glob("*.json"))
        assert approval_files
        approval_payload = json.loads(approval_files[0].read_text(encoding="utf-8"))
        assert approval_payload["action_request"]["content"] == report_content
        assert "planner forged" not in approval_payload["action_request"]["content"]

        loaded = store.load(executed.task_plan_id)
        assert loaded.task_plan_id == executed.task_plan_id
        assert loaded.status == AgentTaskPlanStatus.WAITING_APPROVAL

    print("agent_task_planning_flow=passed")


if __name__ == "__main__":
    asyncio.run(main())
