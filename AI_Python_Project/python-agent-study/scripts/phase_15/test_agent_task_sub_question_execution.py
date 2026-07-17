from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskSubQuestion,
    AgentTaskSubQuestionResult,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import ResearchToolLoop
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent


class FakeRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                id=f"doc_{query[:8]}",
                content=f"知识库证据：{query}",
                score=0.9,
                source="fake_retriever",
                title="fake doc",
            )
        ]


class FakeLLM(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        return f"LLM回答: {query} | context={context.context_text[:80]}"

    async def stream(self, query: str, context: RagContext):
        yield await self.generate(query, context)


class SelectingResearchToolLoop(ResearchToolLoop):
    async def _select_tool_for_sub_question(self, *args, **kwargs) -> dict[str, Any]:
        sub_question = kwargs["sub_question"]
        if kwargs.get("tool_calls"):
            return {"selected_tool": "none", "tool_input": {}}
        if sub_question.sub_question_id == "sq_1":
            return {
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "混合检索 内部设计", "mode": "hybrid", "top_k": 2},
            }
        if sub_question.sub_question_id == "sq_2":
            return {
                "selected_tool": "web_search",
                "tool_input": {"query": "Prompt Guard public practice", "count": 2},
            }
        if sub_question.sub_question_id == "sq_bad":
            return {"selected_tool": "unknown_tool", "tool_input": {}}
        return {"selected_tool": "none", "tool_input": {}}

    async def _run_web_search_for_sub_question(self, *args, **kwargs):
        sub_question = kwargs["sub_question"]
        return (
            {"result_count": 1, "top_urls": ["https://example.com/prompt-guard"]},
            f"web answer for {sub_question.question}",
            [
                {
                    "id": "web_1",
                    "source": "web_search",
                    "title": "Prompt Guard",
                    "url": "https://example.com/prompt-guard",
                }
            ],
        )


class SelectingExecutor:
    def __init__(self, **kwargs) -> None:
        settings = kwargs["settings"]
        tool_loop = SelectingResearchToolLoop(
            settings=settings,
            vector_retriever=kwargs["vector_retriever"],
            keyword_retriever=kwargs["keyword_retriever"],
            llm_client=kwargs["llm_client"],
        )
        worker = ResearchWorkerAgent(
            settings,
            tool_loop,
            ResearchEvidenceEvaluator(settings),
        )
        research = AgenticResearchExecutor(
            settings,
            kwargs["llm_client"],
            kwargs["task_plan_store"],
            worker,
        )
        self._executor = AgentTaskExecutor(**kwargs, research_executor=research)

    def __getattr__(self, name):
        return getattr(self._executor, name)


def build_plan(task_plan_id: str) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="question_decomposition",
        user_id="tool_manager",
        original_query="对比混合检索、Prompt Guard 和权限设计如何影响 RAG 质量",
        objective="回答复杂对比问题",
        task_type="comparison",
        goal="回答复杂对比问题",
        sub_questions=[
            AgentTaskSubQuestion(
                sub_question_id="sq_1",
                order=1,
                question="混合检索如何影响 RAG 回答质量？",
                purpose="确认内部检索质量机制。",
                depends_on=[],
                information_source_hint="web_search",
                reason="故意设置 web_search hint，验证最终仍按 LLM 选择工具执行。",
                expected_evidence="内部设计文档。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_2",
                order=2,
                question="Prompt Guard 有哪些可参考的公开实践？",
                purpose="补充外部安全实践。",
                depends_on=[],
                information_source_hint="knowledge_retrieval",
                reason="故意设置 knowledge hint，验证 LLM 可以选择 web_search。",
                expected_evidence="公开网页资料。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_3",
                order=3,
                question="这些机制如何共同影响质量和安全边界？",
                purpose="整合前置答案。",
                depends_on=["sq_1", "sq_2"],
                information_source_hint="none",
                reason="综合问题可以依赖已有答案。",
                expected_evidence="前置子问题答案。",
            ),
        ],
        research_policy=AgentResearchPolicy(web_policy="required"),
        final_synthesis_instruction="按子问题答案整合为最终结论。",
        source_query="混合检索 Prompt Guard 权限设计",
        target_path=None,
        steps=[],
        created_at=now,
        updated_at=now,
    )


async def main() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            OPENAI_API_KEY="",
            BOCHA_API_KEY="fake",
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings=settings)
        executor = SelectingExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
        )
        user = CurrentUserContext(
            user_id="tool_manager",
            is_authenticated=True,
            auth_source="jwt",
            role="tool_manager",
        )

        plan = await executor.execute_question_decomposition_plan(
            plan=build_plan("task_plan_202607070001_test"),
            user=user,
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )

        assert plan.status == AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
        results = [
            AgentTaskSubQuestionResult.model_validate(item)
            for item in plan.final_output["sub_question_results"]
        ]
        assert [item.sub_question_id for item in results] == ["sq_1", "sq_2", "sq_3"]
        assert [item.selected_tool for item in results] == [
            "knowledge_retrieval",
            "web_search",
            "none",
        ]
        assert [item.status for item in results] == ["completed", "completed", "failed"]
        assert "final_answer" in plan.final_output
        assert plan.final_output["used_tools"] == ["knowledge_retrieval", "web_search"]

        saved_files = list(Path(temp_dir).glob("*_task_plan_202607070001_test.json"))
        assert len(saved_files) == 1
        saved_payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
        assert saved_payload["final_output"]["final_answer"] == plan.final_output["final_answer"]
        assert "sub_question_results" in saved_payload["final_output"]

        waiting_plan = build_plan("task_plan_202607070003_test")
        waiting_plan.status = AgentTaskPlanStatus.WAITING_CONFIRMATION
        waiting_plan.final_output = {
            "status": "waiting_confirmation",
            "confirm_endpoint": f"/agent/task-plans/{waiting_plan.task_plan_id}/confirm",
        }
        store.save(waiting_plan)
        confirmed_plan = await executor.confirm(
            task_plan_id=waiting_plan.task_plan_id,
            user=user,
        )
        assert confirmed_plan.status == AgentTaskPlanStatus.COMPLETED_WITH_WARNINGS
        assert "final_answer" in confirmed_plan.final_output
        assert len(confirmed_plan.final_output["sub_question_results"]) == 3

        bad_plan = build_plan("task_plan_202607070002_test")
        bad_plan.sub_questions[0].sub_question_id = "sq_bad"
        bad_plan.sub_questions[2].depends_on = ["sq_bad", "sq_2"]
        bad_result_plan = await executor.execute_question_decomposition_plan(
            plan=bad_plan,
            user=user,
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        bad_results = bad_result_plan.final_output["sub_question_results"]
        assert bad_results[0]["status"] == "failed"
        assert "unknown_tool" in bad_results[0]["error"]
        assert bad_results[2]["status"] == "skipped"

    print("agent_task_sub_question_execution=passed")


if __name__ == "__main__":
    asyncio.run(main())
