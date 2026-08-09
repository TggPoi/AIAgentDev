"""统一增强 Web 检索改造后的真实网络冒烟验证。

覆盖三条真实执行路径（需要 BOCHA_API_KEY、LLM 配置与外网）：
1. RAG 主链路：从图 START 节点完整走通
   decide_next_action -> check_loop_limits -> call_direct_web -> build_context -> generate_answer；
2. Research Worker 链路：ResearchToolLoop._run_web_search_for_sub_question 真实执行；
3. DeepAgent / direct 文档闭包的对外契约：闭包内部与真实网络交互的部分
   就是 execute_enhanced_web_search + build_web_search_payload，
   这里按同一调用序列真实执行并固化 key 集合契约（闭包本体依赖完整
   TaskPlan 工作流上下文，离线回归已覆盖其装配逻辑）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from fast_app.agents.tools.web_search_tools import WebSearchResult
from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.components.rerankers.mock_reranker import MockReranker
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentTaskSubQuestion
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.rag_agent.rag_agent_builder import build_rag_agent_graph
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.agent_tasks.agent_task_capability_service import AgentTaskCapabilityService
from fast_app.services.agent_tasks.agent_task_router import AgentTaskRouter
from fast_app.services.nl2sql.authorization import Nl2SqlAuthorizationService
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
from fast_app.services.rag.enhanced_web_search import (
    build_payload_from_web_search_results,
    build_web_search_payload,
    execute_enhanced_web_search,
)
from fast_app.services.research.research_tool_loop import ResearchToolLoop

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


QUESTION = "请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。"
_PAYLOAD_KEYS = {"title", "url", "site_name", "content"}


def show(name: str, value: object) -> None:
    """用 unicode_escape 打印，避免 PowerShell 代码页吞掉中文导致误判。"""

    print(f"{name}={str(value).encode('unicode_escape').decode('ascii')}")


async def step1_rag_main_graph(settings: Settings) -> None:
    """从 START 走完整图：真实 Router -> direct_web 增强检索 -> 真实生成。"""

    # direct_web 路径不触碰 NL2SQL 鉴权，dummy session 即可满足装配签名。
    capability_service = AgentTaskCapabilityService(
        settings=settings,
        dataset_registry=None,
        nl2sql_authorization=Nl2SqlAuthorizationService(cast("AsyncSession", None)),
    )
    graph = build_rag_agent_graph(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=QwenLangChainLLMClient(settings=settings),
        reranker=MockReranker(),
        rerank_top_k=3,
        task_router=AgentTaskRouter(settings),
        capability_service=capability_service,
    )
    user = CurrentUserContext(
        user_id="smoke_user",
        is_authenticated=True,
        auth_source="jwt",
        global_permission_codes=["agent:tool:web_search"],
    )
    initial_state = build_rag_agent_initial_state(
        RagChatRequest(query=QUESTION, mode="hybrid", top_k=3),
        operation="run",
        current_user=user,
    )
    final_state = await graph.ainvoke(initial_state)
    show("[1] route_intent", final_state.get("route_intent"))
    show("[1] route_source", final_state.get("route_source"))
    show("[1] final_reason", final_state.get("final_reason"))
    docs = final_state.get("docs") or []
    answer = final_state.get("answer") or ""
    assert final_state.get("route_intent") == "web_research", final_state.get("route_intent")
    assert docs, "call_direct_web 节点应产出文档"
    assert answer.strip(), "generate_answer 应产出非空回答"
    for index, doc in enumerate(docs, start=1):
        show(f"[1] doc{index}.url", (doc.metadata or {}).get("url"))
        print(f"[1] doc{index}.content_len={len(doc.content)}")
    show("[1] answer_preview", answer[:160])
    print("step1_rag_main_graph OK")


async def step2_research_tool_loop(settings: Settings) -> None:
    """Research Worker 链路的 web 检索分支真实执行（增强路径优先）。"""

    loop = ResearchToolLoop(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=QwenLangChainLLMClient(settings=settings),
        web_planner=DirectWebSearchPlanner(settings),
    )
    sub_question = AgentTaskSubQuestion(
        sub_question_id="sq_web_1",
        order=1,
        question="PostgreSQL 16 的行级安全策略有什么作用？",
        purpose="为最终回答提供官方证据",
        information_source_hint="web_search",
        reason="知识库没有公开 PostgreSQL 官方资料",
    )
    result = await loop._run_web_search_for_sub_question(
        sub_question=sub_question,
        tool_input={"query": QUESTION, "count": 3, "site": "postgresql.org"},
    )
    show("[2] result_count", result.tool_output.get("result_count"))
    show("[2] top_urls", result.tool_output.get("top_urls"))
    assert result.context_docs, "Research 链路应产出上下文文档"
    assert result.evidence, "Research 链路应产出证据摘要"
    for index, doc in enumerate(result.context_docs, start=1):
        show(f"[2] doc{index}.url", (doc.metadata or {}).get("url"))
        print(f"[2] doc{index}.content_len={len(doc.content)}")
    print("step2_research_tool_loop OK")


async def step3_tool_payload_contract(settings: Settings) -> None:
    """DeepAgent / direct 闭包的真实网络调用序列与 JSON 契约。"""

    planner = DirectWebSearchPlanner(settings)
    docs = await execute_enhanced_web_search(
        settings=settings,
        planner=planner,
        question=QUESTION,
        top_k=3,
    )
    payload = build_web_search_payload(docs, content_limit=8000)
    assert payload, "增强路径应产出载荷"
    for item in payload:
        assert item.keys() == _PAYLOAD_KEYS, item.keys()
        assert len(item["content"]) <= 8000
    show("[3] enhanced_payload_count", len(payload))
    show("[3] enhanced_first_url", payload[0]["url"])
    print(f"[3] enhanced_first_content_len={len(payload[0]['content'])}")

    fallback_payload = build_payload_from_web_search_results(
        [
            WebSearchResult(
                title="Row Security",
                url="https://postgresql.org/docs/16/x.html",
                snippet="snippet text",
                summary="summary text",
            )
        ],
        content_limit=8000,
    )
    assert fallback_payload[0].keys() == _PAYLOAD_KEYS
    print("step3_tool_payload_contract OK")


async def main() -> None:
    settings = Settings()
    assert settings.bocha_api_key, "BOCHA_API_KEY 未配置，无法执行真实网络测试"
    print("=" * 60)
    print("统一增强 Web 检索改造 真实网络冒烟")
    print("=" * 60)
    await step1_rag_main_graph(settings)
    await step2_research_tool_loop(settings)
    await step3_tool_payload_contract(settings)
    print("=" * 60)
    print("REAL NETWORK SMOKE ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
