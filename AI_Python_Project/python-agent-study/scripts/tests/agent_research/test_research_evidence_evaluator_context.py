"""Research Evidence Evaluator 必须审核答案实际使用的上下文。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentTaskSubQuestion,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.agent_tasks.agent_task_tool_support import doc_to_evidence
from fast_app.services.rag.rag_context_builder import build_rag_context
from fast_app.services.research import research_evidence_evaluator as evaluator_module
from fast_app.services.research.research_evidence_evaluator import (
    ResearchEvidenceEvaluator,
)
from fast_app.services.research.research_tool_loop import (
    filter_evidence_refs_for_context,
)


class CapturingStructuredModel:
    def __init__(self, owner: "CapturingChatOpenAI") -> None:
        self._owner = owner

    async def ainvoke(self, messages, config=None):
        del config
        type(self._owner).messages = messages
        return ResearchEvidenceEvaluation(
            verdict="sufficient",
            confidence=0.9,
            relevance=0.9,
            coverage=0.9,
            authority=0.9,
            recommended_action="accept",
            reason="测试证据充分。",
        )


class CapturingChatOpenAI:
    messages = None

    def __init__(self, **_kwargs) -> None:
        pass

    def with_structured_output(self, *_args, **_kwargs):
        return CapturingStructuredModel(self)


class UnexpectedChatOpenAI:
    def __init__(self, **_kwargs) -> None:
        raise AssertionError("没有可核验证据时不应创建 Evaluator LLM")


async def test_evaluator_receives_the_context_used_to_generate_the_answer() -> None:
    late_facts = (
        "DATABASE_URL=postgresql://rag; "
        "MILVUS_PORT=19530; "
        "ELASTICSEARCH_URL=http://elasticsearch:9200"
    )
    doc = RetrievedDoc(
        id="deployment-config",
        content=f"{'普通部署说明。' * 25}{late_facts}",
        score=0.98,
        source="knowledge_retrieval",
        title="RAG 后端部署配置",
        metadata={
            "source_path": "development/rag-backend-deployment.md",
            "user_id": "must-not-reach-evaluator",
        },
    )
    evidence_ref = doc_to_evidence(doc)
    assert late_facts not in evidence_ref["content_preview"]

    answer_context = build_rag_context("列出部署示例配置", [doc])
    assert late_facts in answer_context.context_text

    original_chat_openai = evaluator_module.ChatOpenAI
    evaluator_module.ChatOpenAI = CapturingChatOpenAI
    try:
        evaluator = ResearchEvidenceEvaluator(
            Settings(_env_file=None, OPENAI_API_KEY="test-key")
        )
        evaluation = await evaluator.evaluate(
            sub_question=AgentTaskSubQuestion(
                sub_question_id="sq_config",
                order=1,
                question="列出部署文档中的三个示例配置值。",
                purpose="核验部署配置示例。",
                information_source_hint="knowledge_retrieval",
                reason="需要知识库证据。",
            ),
            answer="配置值见部署文档。",
            evidence_refs=[evidence_ref],
            answer_context=answer_context,
        )
    finally:
        evaluator_module.ChatOpenAI = original_chat_openai

    assert evaluation.verdict == "sufficient"
    assert CapturingChatOpenAI.messages is not None
    payload = json.loads(CapturingChatOpenAI.messages[-1].content)
    assert late_facts in payload["evidence_context"]
    assert "content_preview" not in payload["evidence_refs"][0]
    assert "user_id" not in payload["evidence_refs"][0]["metadata"]


def test_only_evidence_used_by_the_answer_remains_traceable() -> None:
    parent_doc = RetrievedDoc(
        id="parent-1",
        content="父块中的完整证据。",
        score=0.9,
        source="knowledge_retrieval",
        metadata={
            "chunk_level": "parent",
            "matched_child_ids": ["child-used"],
        },
    )
    context = build_rag_context("核验父块", [parent_doc])
    filtered = filter_evidence_refs_for_context(
        [
            {"id": "child-used", "source": "knowledge_retrieval"},
            {"id": "child-not-used", "source": "knowledge_retrieval"},
        ],
        context,
    )
    assert [item["id"] for item in filtered] == ["child-used"]


async def test_missing_evidence_context_is_deterministically_insufficient() -> None:
    original_chat_openai = evaluator_module.ChatOpenAI
    evaluator_module.ChatOpenAI = UnexpectedChatOpenAI
    try:
        evaluator = ResearchEvidenceEvaluator(
            Settings(_env_file=None, OPENAI_API_KEY="test-key")
        )
        evaluation = await evaluator.evaluate(
            sub_question=AgentTaskSubQuestion(
                sub_question_id="sq_missing",
                order=1,
                question="没有证据的问题",
                purpose="验证保守收敛。",
                information_source_hint="knowledge_retrieval",
                reason="测试无证据分支。",
            ),
            answer="无法核验的答案",
            evidence_refs=[],
            answer_context=None,
        )
    finally:
        evaluator_module.ChatOpenAI = original_chat_openai
    assert evaluation.verdict == "insufficient"


if __name__ == "__main__":
    asyncio.run(test_evaluator_receives_the_context_used_to_generate_the_answer())
    test_only_evidence_used_by_the_answer_remains_traceable()
    asyncio.run(test_missing_evidence_context_is_deterministically_insufficient())
    print("research_evidence_evaluator_context=passed")
