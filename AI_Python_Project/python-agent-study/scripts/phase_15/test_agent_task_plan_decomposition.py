from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.graph.rag_agent_nodes import build_task_plan_answer
from fast_app.services.agent_task_planner import AgentTaskPlanner


TODO_PREFIXES = (
    "检索",
    "调用",
    "查询",
    "搜索",
    "生成",
    "保存",
    "整理",
    "总结",
    "写入",
    "执行",
)


class LowConfidencePlanner(AgentTaskPlanner):
    def _build_model(self):
        return object()

    async def _invoke_structured_planner(self, *args, **kwargs):
        return {"confidence": 0.0}

    async def _invoke_json_planner(self, *args, **kwargs):
        raise AssertionError("structured planner already returned payload")


def assert_question_plan(plan) -> None:
    # 这个脚本主要保护“子问题必须是问题，不是工具 TODO”这条边界。
    assert plan is not None
    assert plan.original_query
    assert plan.objective
    assert plan.task_type in {"qa", "comparison", "report_generation", "analysis", "unknown"}
    assert len(plan.sub_questions) >= 3
    assert plan.final_synthesis_instruction
    assert plan.source_query
    assert len(plan.source_query) < 80
    assert all(item.question.endswith(("？", "?")) for item in plan.sub_questions)
    assert not any(
        item.question.startswith(TODO_PREFIXES)
        for item in plan.sub_questions
    )
    assert any(item.depends_on for item in plan.sub_questions)


def assert_topics_covered(plan, topics: list[str]) -> None:
    text = " ".join(
        " ".join(
            [
                item.question,
                item.purpose,
                item.reason,
                item.expected_evidence or "",
            ]
        )
        for item in plan.sub_questions
    )
    missing = [topic for topic in topics if topic.lower() not in text.lower()]
    assert missing == []


async def main() -> None:
    deterministic_planner = AgentTaskPlanner(settings=Settings(OPENAI_API_KEY=""))
    document_plan = deterministic_planner.build_document_management_plan(
        query="请删除知识库中与旧部署说明相关的文档",
        user_id="planner-user",
    )
    assert document_plan.task_kind == "knowledge_document_management"
    assert document_plan.steps == []

    low_confidence_planner = LowConfidencePlanner(
        settings=Settings(OPENAI_API_KEY="fake-key")
    )
    low_confidence_plan = await low_confidence_planner.plan_question_decomposition(
        query="请对比混合检索和 rerank 的关系",
        user_id="planner-user",
    )
    assert low_confidence_plan.task_kind == "question_decomposition"

    settings = Settings(OPENAI_API_KEY="")
    planner = AgentTaskPlanner(settings=settings)
    # OPENAI_API_KEY 置空时走规则兜底，保证没有真实 LLM 也能验证 plan 收敛规则。
    plain_complex_query = "请对比 RAG 系统中的混合检索、rerank、权限设计和 Prompt Guard 之间的关系"
    plain_plan = await planner.plan_question_decomposition(
        query=plain_complex_query,
        user_id="planner-user",
    )
    assert_question_plan(plain_plan)
    assert plain_plan.task_kind == "question_decomposition"
    assert plain_plan.target_path is None
    assert plain_plan.steps == []
    assert "问题拆解" in build_task_plan_answer(plain_plan)
    assert_topics_covered(plain_plan, ["混合检索", "rerank", "权限设计", "Prompt Guard"])

    query = "对比知识库中的混合检索、rerank、权限设计，生成报告保存到 development/complex-plan.md"

    fallback_plan = planner.build_document_management_plan(
        query=query,
        user_id="planner-user",
    )
    assert fallback_plan.task_kind == "knowledge_document_management"
    assert fallback_plan.steps == []
    assert fallback_plan.sub_questions == []

    payload = {
        "objective": "对比 RAG 系统中的混合检索、rerank 和权限设计并形成报告",
        "task_type": "comparison",
        "source_query": "混合检索 rerank 权限设计 RAG 系统 协同关系",
        "document_actions": [{"operation": "delete", "target_path": "forged.md"}],
        "confidence": 0.95,
    }
    llm_plan = planner._plan_from_payload(
        query=query,
        payload=payload,
        user_id="planner-user",
    )
    assert llm_plan is not None
    assert llm_plan.task_kind == "question_decomposition"
    assert llm_plan.steps == []
    assert "forged.md" not in llm_plan.model_dump_json()

    incomplete_query = "请对比 RAG 系统中的混合检索、rerank、权限设计和 Prompt Guard 之间的关系"
    incomplete_payload = {
        "objective": "对比 RAG 系统中的多个模块关系",
        "task_type": "comparison",
        "source_query": "rerank Prompt Guard 协同机制",
        "target_path": None,
        "report_title": "复杂问题拆解",
        "final_synthesis_instruction": "整合各模块关系。",
        "sub_questions": [
            {
                "sub_question_id": "sq_1",
                "order": 1,
                "question": "rerank 模块在检索链路中承担什么作用？",
                "purpose": "说明 rerank 的功能。",
                "depends_on": [],
                "information_source_hint": "knowledge_retrieval",
                "reason": "rerank 影响回答质量。",
                "expected_evidence": "rerank 设计资料。",
            },
            {
                "sub_question_id": "sq_2",
                "order": 2,
                "question": "Prompt Guard 如何影响 RAG 系统的安全边界？",
                "purpose": "说明 Prompt Guard 的安全作用。",
                "depends_on": [],
                "information_source_hint": "knowledge_retrieval",
                "reason": "Prompt Guard 影响安全边界。",
                "expected_evidence": "Prompt Guard 规则资料。",
            },
        ],
        "confidence": 0.95,
    }
    parsed_plan = planner._plan_from_payload(
        query=incomplete_query,
        payload=incomplete_payload,
        user_id="planner-user",
    )
    assert parsed_plan.task_kind == "question_decomposition"
    assert parsed_plan.target_path is None
    assert parsed_plan.steps == []
    assert len(parsed_plan.sub_questions) == 2
    assert parsed_plan.source_query == "rerank Prompt Guard 协同机制"

    print("agent_task_plan_decomposition=passed")


if __name__ == "__main__":
    asyncio.run(main())
