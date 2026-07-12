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
        if context.confirmation_text is not None:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.EXECUTE_ALLOWED,
                allowed=True,
                reason="测试：TaskPlan 已人工确认",
                risk_level=KnowledgeDocumentRiskLevel.MEDIUM,
                required_permissions=[
                    PermissionCode.KNOWLEDGE_DOCUMENT_CREATE,
                    PermissionCode.KNOWLEDGE_DOCUMENT_APPROVE,
                ],
                missing_permissions=[],
                target_department_codes=context.target_department_codes,
                requires_confirmation=False,
            )
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            allowed=True,
            reason="测试：文档创建需要 TaskPlan 人工确认",
            risk_level=KnowledgeDocumentRiskLevel.MEDIUM,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE],
            missing_permissions=[],
            target_department_codes=context.target_department_codes,
            requires_confirmation=True,
        )


class FakeAuditService:
    async def record_decision(self, **kwargs):
        return None

    async def record_execution(self, **kwargs):
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
            AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY=False,
            AGENT_TOOL_EXECUTION_POLICY="confirmation_required",
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
        assert plan.task_kind == "knowledge_document_management"
        assert plan.steps == []

        single_tool_query = "新增 development/single.md 内容是：# 单工具"
        single_plan = await planner.plan(query=single_tool_query, user_id=user.user_id)
        assert single_plan is not None
        assert single_plan.task_kind == "knowledge_document_management"
        assert single_plan.steps == []

    print("agent_task_planning_flow=passed")


if __name__ == "__main__":
    asyncio.run(main())
