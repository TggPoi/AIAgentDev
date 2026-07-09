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
    AgentTaskPlan,
    AgentTaskPlanStatus,
    AgentTaskSubQuestion,
)
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore


class FakeRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(
                id=f"doc_{query[:8]}",
                content=f"fake evidence: {query}",
                score=0.9,
                source="fake",
                title="fake doc",
            )
        ]


class FakeLLM(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        return f"answer: {query} | {context.context_text[:120]}"

    async def stream(self, query: str, context: RagContext):
        yield await self.generate(query, context)


class LoopExecutor(AgentTaskExecutor):
    async def _select_tool_for_sub_question(self, *args, **kwargs) -> dict[str, Any]:
        sub_question = kwargs["sub_question"]
        tool_calls = kwargs.get("tool_calls") or []
        if sub_question.sub_question_id == "sq_loop":
            if len(tool_calls) == 0:
                return {
                    "selected_tool": "knowledge_retrieval",
                    "tool_input": {"query": "内部 RAG 设计", "top_k": 2},
                    "reason": "先查内部知识库",
                }
            if len(tool_calls) == 1:
                return {
                    "selected_tool": "web_search",
                    "tool_input": {"query": "RAG evaluation practice", "count": 1},
                    "reason": "再补公开资料",
                }
            return {"selected_tool": "none", "tool_input": {}, "reason": "证据足够"}
        if sub_question.sub_question_id == "sq_limit":
            return {
                "selected_tool": "knowledge_retrieval",
                "tool_input": {"query": "循环上限测试", "top_k": 1},
                "reason": "故意超过上限",
            }
        return {
            "selected_tool": "unknown_tool",
            "tool_input": {},
            "reason": "测试未知工具不能执行",
        }

    async def _run_knowledge_retrieval_for_sub_question(self, *args, **kwargs):
        sub_question = kwargs["sub_question"]
        return (
            {"doc_count": 1, "top_doc_ids": ["doc_1"]},
            f"knowledge answer for {sub_question.question}",
            [{"id": "doc_1", "source": "knowledge_retrieval"}],
        )

    async def _run_web_search_for_sub_question(self, *args, **kwargs):
        sub_question = kwargs["sub_question"]
        return (
            {"result_count": 1, "top_urls": ["https://example.com/rag"]},
            f"web answer for {sub_question.question}",
            [{"id": "web_1", "source": "web_search"}],
        )


def build_plan(task_plan_id: str) -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id=task_plan_id,
        task_kind="question_decomposition",
        user_id="tool_manager",
        original_query="分析 RAG 系统质量改进路径",
        objective="按子问题收集证据并综合回答",
        task_type="analysis",
        goal="按子问题收集证据并综合回答",
        sub_questions=[
            AgentTaskSubQuestion(
                sub_question_id="sq_loop",
                order=1,
                question="RAG 质量改进需要哪些内部证据和外部实践？",
                purpose="验证一个子问题多轮调用不同工具。",
                depends_on=[],
                information_source_hint="knowledge_retrieval",
                reason="复杂问题需要多来源证据。",
                expected_evidence="内部文档和公开资料。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_limit",
                order=2,
                question="工具循环达到上限后应如何停止？",
                purpose="验证 AGENT_MAX_TOOL_CALLS 生效。",
                depends_on=[],
                information_source_hint="knowledge_retrieval",
                reason="避免无限工具调用。",
                expected_evidence="工具调用轨迹。",
            ),
            AgentTaskSubQuestion(
                sub_question_id="sq_unknown",
                order=3,
                question="未知工具是否会被执行？",
                purpose="验证工具白名单。",
                depends_on=[],
                information_source_hint="none",
                reason="LLM 不能凭空调用工具。",
                expected_evidence="失败轨迹。",
            ),
        ],
        final_synthesis_instruction="综合所有成功子问题答案。",
        source_query="RAG 质量 改进",
        target_path=None,
        steps=[],
        created_at=now,
        updated_at=now,
    )


def build_user() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="tool_manager",
        is_authenticated=True,
        auth_source="jwt",
        role="tool_manager",
    )


def build_executor(settings: Settings, store: AgentTaskPlanStore) -> AgentTaskExecutor:
    return LoopExecutor(
        settings=settings,
        vector_retriever=FakeRetriever(),
        keyword_retriever=FakeRetriever(),
        llm_client=FakeLLM(),
        document_management_service=object(),
        tool_permission_service=object(),
        tool_audit_service=object(),
        task_plan_store=store,
    )


async def main() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            OPENAI_API_KEY="",
            BOCHA_API_KEY="fake",
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_MAX_TOOL_CALLS=2,
        )
        store = AgentTaskPlanStore(settings=settings)
        executor = build_executor(settings, store)

        plan = await executor.execute_question_decomposition_plan(
            plan=build_plan("task_plan_202607080001_tool_loop"),
            user=build_user(),
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )

        assert plan.status == AgentTaskPlanStatus.COMPLETED
        results = plan.final_output["sub_question_results"]
        assert [item["sub_question_id"] for item in results] == [
            "sq_loop",
            "sq_limit",
            "sq_unknown",
        ]
        assert [call["tool_name"] for call in results[0]["tool_calls"]] == [
            "knowledge_retrieval",
            "web_search",
        ]
        assert len(results[1]["tool_calls"]) == 2
        assert results[1]["tool_calls"][-1]["round"] == 2
        assert results[2]["status"] == "failed"
        assert results[2]["tool_calls"][0]["tool_name"] == "unknown_tool"
        assert "未注册工具" in results[2]["tool_calls"][0]["error"]
        assert plan.final_output["used_tools"] == [
            "knowledge_retrieval",
            "web_search",
        ]
        saved = list(Path(temp_dir).glob("*_task_plan_202607080001_tool_loop.json"))
        assert len(saved) == 1
        payload = json.loads(saved[0].read_text(encoding="utf-8"))
        assert "tool_calls" in payload["final_output"]["sub_question_results"][0]

        server_path = ROOT / "scripts" / "mcp_demo_server.py"
        mcp_settings = Settings(
            OPENAI_API_KEY="",
            AGENT_TASK_PLAN_DIR=temp_dir,
            AGENT_TASK_MCP_ENABLED=True,
            AGENT_TASK_MCP_STDIO_SERVERS_JSON=json.dumps(
                [
                    {
                        "name": "demo",
                        "command": sys.executable,
                        "args": [str(server_path)],
                        "allowed_tool_names": ["add", "echo"],
                    }
                ]
            ),
        )
        mcp_store = AgentTaskPlanStore(settings=mcp_settings)
        mcp_executor = AgentTaskExecutor(
            settings=mcp_settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLM(),
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=mcp_store,
        )
        tools = await mcp_executor._build_available_task_tools()
        assert "mcp__add" in {tool.name for tool in tools}
        assert "mcp__echo" in {tool.name for tool in tools}
        tool_output, answer, evidence = await mcp_executor._run_task_tool_for_sub_question(
            selected_tool="mcp__add",
            tool_input={"a": 2, "b": 3},
            available_tools=tools,
            sub_question=build_plan("task_plan_202607080002_mcp").sub_questions[0],
            previous_results=[],
            mode="hybrid",
            top_k=3,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(),
        )
        assert tool_output["content"] == "5"
        assert "answer:" in answer
        assert evidence[0]["source"] == "mcp__add"

    print("agent_task_tool_loop=passed")


if __name__ == "__main__":
    asyncio.run(main())
