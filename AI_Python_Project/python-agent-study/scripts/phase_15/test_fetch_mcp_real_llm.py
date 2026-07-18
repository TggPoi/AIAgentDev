from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskSubQuestion
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import ResearchToolLoop
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent


class EmptyRetriever(BaseRetriever):
    async def retrieve(
        self,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedDoc]:
        return []


def build_plan() -> AgentTaskPlan:
    now = datetime.now(UTC)
    return AgentTaskPlan(
        task_plan_id="task_plan_202607080001_fetch_mcp_real_llm",
        task_kind="question_decomposition",
        user_id="tool_manager",
        original_query="读取 https://example.com，并说明这个页面的用途。",
        objective="验证真实 LLM 能选择 Fetch MCP 读取 URL。",
        task_type="qa",
        goal="验证真实 LLM 能选择 Fetch MCP 读取 URL。",
        sub_questions=[
            AgentTaskSubQuestion(
                sub_question_id="sq_fetch_example",
                order=1,
                question="https://example.com 这个网页说明了什么用途？",
                purpose="验证 Fetch MCP 可以读取公开网页正文。",
                depends_on=[],
                information_source_hint="web_search",
                reason="该子问题需要读取指定 URL，而不是只查知识库。",
                expected_evidence="网页正文中关于 Example Domain 的说明。",
            )
        ],
        final_synthesis_instruction="只根据网页正文回答，说明 Fetch MCP 是否成功读取页面。",
        source_query="example.com Example Domain",
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


async def main() -> None:
    settings = Settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 为空，无法执行真实 LLM 验收")
    if not settings.agent_task_mcp_enabled:
        raise RuntimeError("AGENT_TASK_MCP_ENABLED 未开启")

    with TemporaryDirectory() as temp_dir:
        settings.agent_task_plan_dir = temp_dir
        settings.agent_max_tool_calls = max(settings.agent_max_tool_calls, 2)

        llm_client = QwenLangChainLLMClient(settings=settings)
        tool_loop = ResearchToolLoop(
            settings=settings,
            vector_retriever=EmptyRetriever(),
            keyword_retriever=EmptyRetriever(),
            llm_client=llm_client,
        )
        store = AgentTaskPlanStore(settings=settings)
        worker = ResearchWorkerAgent(
            settings=settings,
            tool_loop=tool_loop,
            evaluator=ResearchEvidenceEvaluator(settings),
        )
        research = AgenticResearchExecutor(
            settings=settings,
            llm_client=llm_client,
            task_plan_store=store,
            worker_agent=worker,
        )
        executor = AgentTaskExecutor(
            settings=settings,
            vector_retriever=EmptyRetriever(),
            keyword_retriever=EmptyRetriever(),
            llm_client=llm_client,
            document_management_service=object(),
            tool_permission_service=object(),
            tool_audit_service=object(),
            task_plan_store=store,
            research_executor=research,
        )
        plan = build_plan()
        tools = await tool_loop._build_available_task_tools()
        tool_names = {tool.name for tool in tools}
        assert "mcp__fetch" in tool_names, f"未注册 mcp__fetch，可用工具: {sorted(tool_names)}"

        try:
            result = await executor.execute_question_decomposition_plan(
                plan=plan,
                user=build_user(),
                mode="hybrid",
                top_k=3,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(),
            )
        except Exception:
            saved = sorted(Path(temp_dir).glob("*_fetch_mcp_real_llm.json"))
            if saved:
                print(saved[-1].read_text(encoding="utf-8"))
            raise
        payload = result.final_output["sub_question_results"][0]
        # Evaluator 对摘要覆盖率的主观判断可能给出 partial；真实链路验收只要求
        # Fetch 成功、证据存在且 Worker 没有伪装成无条件 completed。
        assert payload["status"] in {"completed", "partial"}, payload
        assert payload["tool_calls"][0]["tool_name"] == "mcp__fetch", payload
        assert payload["tool_calls"][0]["status"] == "completed", payload
        tool_output = payload["tool_calls"][0]["tool_output"]
        assert "Example Domain" in tool_output["content_preview"]
        assert "content" not in tool_output

        print("fetch_mcp_real_llm=passed")
        print(f"selected_tool={payload['tool_calls'][0]['tool_name']}")
        print(f"answer_preview={payload['answer'][:240]}")


if __name__ == "__main__":
    asyncio.run(main())
