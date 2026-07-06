from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.services.agent_document_action_planner import AgentDocumentActionPlanner


def build_planner() -> AgentDocumentActionPlanner:
    return AgentDocumentActionPlanner.__new__(AgentDocumentActionPlanner)


def test_llm_content_is_rejected_without_explicit_user_content() -> None:
    planner = build_planner()
    intent = planner._intent_from_llm_payload(
        query="帮我更新 development/demo.md，把标题改成新的版本",
        payload={
            "operation": "update",
            "target_path": "development/demo.md",
            "reason": "用户要求修改文档",
            "content": "# LLM forged content",
            "expected_department_codes": ["development"],
            "confidence": 0.99,
        },
    )
    assert intent is None


def test_explicit_user_content_wins_over_llm_content() -> None:
    planner = build_planner()
    intent = planner._intent_from_llm_payload(
        query="新增 development/demo.md，内容是：# Explicit\n这是用户给出的完整正文。",
        payload={
            "operation": "create",
            "target_path": "development/demo.md",
            "reason": "用户要求新增文档",
            "content": "# LLM forged content",
            "expected_department_codes": ["development"],
            "confidence": 0.99,
        },
    )
    assert intent is not None
    assert intent.content == "# Explicit\n这是用户给出的完整正文。"


def test_delete_ignores_llm_content() -> None:
    planner = build_planner()
    intent = planner._intent_from_llm_payload(
        query="删除 development/demo.md",
        payload={
            "operation": "delete",
            "target_path": "development/demo.md",
            "reason": "用户要求删除文档",
            "content": "# LLM forged content",
            "expected_department_codes": ["development"],
            "confidence": 0.99,
        },
    )
    assert intent is not None
    assert intent.content is None


def main() -> None:
    test_llm_content_is_rejected_without_explicit_user_content()
    test_explicit_user_content_wins_over_llm_content()
    test_delete_ignores_llm_content()
    print("agent_document_action_planner_content_guard=passed")


if __name__ == "__main__":
    main()
