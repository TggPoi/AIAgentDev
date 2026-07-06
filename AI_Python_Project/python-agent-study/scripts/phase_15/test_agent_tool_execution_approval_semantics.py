from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import (
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    PermissionCode,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentActionResult,
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tool_approval_service import AgentToolApprovalService


async def test_execution_approval_is_approval_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = AgentToolApprovalService(
            Settings(
                AGENT_TOOL_APPROVAL_DIR=tmp,
                AGENT_TOOL_APPROVAL_EXPIRE_MINUTES=60,
            )
        )
        user = CurrentUserContext(
            user_id="semantic-test-user",
            is_authenticated=True,
            role="department_document_manager",
            permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value],
            department_codes=["development"],
        )
        request = KnowledgeDocumentActionRequest(
            operation=KnowledgeDocumentOperation.CREATE,
            target_path="development/semantic-test.md",
            content="# Semantic Test\n",
            reason="验证执行确认单语义",
            dry_run=True,
            expected_department_codes=["development"],
        )
        preview = KnowledgeDocumentActionPreview(
            operation=request.operation,
            target_path=request.target_path,
            normalized_path=request.target_path,
            exists_before=False,
            risk_level=KnowledgeDocumentRiskLevel.HIGH,
            affected_doc_id=None,
            affected_chunk_count=0,
            before_hash=None,
            after_hash="after",
            permission_metadata={"allowed_departments": ["development"]},
            warnings=["测试确认单，不执行真实写入。"],
            requires_confirmation=True,
        )
        action_result = KnowledgeDocumentActionResult(
            operation=request.operation,
            target_path=request.target_path,
            dry_run=True,
            executed=False,
            preview=preview,
            message="dry-run ok",
        )
        decision = AgentToolPermissionDecision(
            action=AgentToolPermissionAction.APPROVAL_REQUIRED,
            allowed=True,
            reason="需要人工确认",
            risk_level=KnowledgeDocumentRiskLevel.HIGH,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE],
            missing_permissions=[],
            target_department_codes=["development"],
            requires_confirmation=True,
        )

        created = await service.create_approval(
            user=user,
            tool_name="knowledge_document_create",
            action_request=request,
            action_result=action_result,
            permission_decision=decision,
        )

        assert created.approval.approval_kind == "tool_execution_approval"
        assert created.approval.approval_id.startswith("tool_approval_")

        json_payload = json.loads(Path(created.json_path).read_text(encoding="utf-8"))
        assert json_payload["approval_kind"] == "tool_execution_approval"
        assert json_payload["approval_id"] == created.approval.approval_id

        markdown = Path(created.markdown_path).read_text(encoding="utf-8")
        assert "执行确认单" in markdown
        assert "不是 LLM 任务规划结果" in markdown
        assert "多步骤任务计划" not in markdown
        assert "请使用系统返回的 `confirmation_text`" in markdown
        assert created.confirmation_text not in markdown


def main() -> None:
    asyncio.run(test_execution_approval_is_approval_snapshot())
    print("agent_tool_execution_approval_semantics=passed")


if __name__ == "__main__":
    main()
