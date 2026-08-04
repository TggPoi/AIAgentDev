from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.graph.rag_agent.rag_agent_nodes import (
    _official_sitemap_candidates,
    create_call_direct_web_node,
    create_next_action_decision_node,
    route_after_loop_check,
)
from fast_app.graph.rag_agent import rag_agent_nodes as nodes_module
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan
from fast_app.services.agent_tasks import agent_task_router as router_module
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.agent_task_router import (
    AgentRouteDecision,
    AgentTaskRouteResult,
    AgentTaskRouter,
    _route_with_high_confidence_rules,
)


class FakeStructuredModel:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def ainvoke(self, _messages, config=None):
        if self.error is not None:
            raise self.error
        return self.response


class FakeChatOpenAI:
    response = None
    error: Exception | None = None
    init_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs) -> None:
        type(self).init_kwargs = kwargs

    def with_structured_output(self, _schema, method):
        assert method == "function_calling"
        return FakeStructuredModel(self.response, self.error)


class FixedRouter:
    def __init__(self, intent: str) -> None:
        self.intent = intent

    async def route(self, **_kwargs):
        return AgentTaskRouteResult(
            decision=AgentRouteDecision(
                intent=self.intent,
                confidence=0.99,
                reason="test route",
            ),
            source="model",
            latency_ms=1.0,
        )


class ExplodingPlanner:
    async def plan_question_decomposition(self, **_kwargs):
        raise AssertionError("simple_rag 不得调用 Planner")


def build_settings(**overrides) -> Settings:
    values = {
        "AGENT_ROUTER_API_KEY": "router-key",
        "AGENT_ROUTER_BASE_URL": "https://router.example/v1",
        "AGENT_ROUTER_MODEL_NAME": "router-model",
        "AGENT_ROUTER_CONFIDENCE_THRESHOLD": 0.75,
        "OPENAI_API_KEY": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def main() -> None:
    settings = build_settings()
    settings.validate_agent_router_config()
    for missing_field in (
        "AGENT_ROUTER_API_KEY",
        "AGENT_ROUTER_BASE_URL",
        "AGENT_ROUTER_MODEL_NAME",
    ):
        try:
            build_settings(**{missing_field: ""}).validate_agent_router_config()
        except ValueError as exc:
            assert missing_field in str(exc)
        else:
            raise AssertionError(f"缺少 {missing_field} 时必须启动失败")

    for invalid_config in (
        {"AGENT_ROUTER_CONFIDENCE_THRESHOLD": 1.1},
        {"AGENT_ROUTER_TIMEOUT_SECONDS": 0},
        {"AGENT_ROUTER_TEMPERATURE": -0.1},
        {"AGENT_ROUTER_STRUCTURED_OUTPUT_METHOD": "plain_json"},
    ):
        try:
            build_settings(**invalid_config)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"非法 Router 配置未被拒绝: {invalid_config}")

    for invalid in (
        {"intent": "unknown", "confidence": 1.0, "reason": "bad"},
        {
            "intent": "simple_rag",
            "confidence": 1.0,
            "reason": "bad",
            "tool_name": "forged",
        },
        {
            "intent": "clarification_required",
            "confidence": 0.8,
            "reason": "missing question",
        },
    ):
        try:
            AgentRouteDecision.model_validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"非法 Router 输出未被拒绝: {invalid}")

    empty_optional_field = AgentRouteDecision.model_validate(
        {
            "intent": "simple_rag",
            "confidence": 1.0,
            "reason": "single fact",
            "clarification_question": "  ",
        }
    )
    assert empty_optional_field.clarification_question is None

    assert _route_with_high_confidence_rules(
        "请修改 docs/development/rag.md 文档"
    ).intent == "knowledge_document_management"
    # 简单/复杂 Web 必须由结构化 Router 判断，关键词规则不能把复杂比较短路成 direct Web。
    assert _route_with_high_confidence_rules("请联网搜索 FastAPI 最新版本") is None
    assert _route_with_high_confidence_rules("阅读 https://fastapi.tiangolo.com/") is None
    # 历史中的“文档”不会被规则拼入当前 query；普通缓存操作必须交给语义 Router。
    assert _route_with_high_confidence_rules("删除 Redis 测试缓存") is None

    original_chat_openai = router_module.ChatOpenAI
    router_module.ChatOpenAI = FakeChatOpenAI
    try:
        FakeChatOpenAI.error = None
        FakeChatOpenAI.response = AgentRouteDecision(
            intent="simple_rag",
            confidence=0.96,
            reason="single fact",
        )
        result = await AgentTaskRouter(settings).route(query="FastAPI 是什么？")
        assert result.decision.intent == "simple_rag"
        assert result.source == "model"
        assert "extra_body" not in FakeChatOpenAI.init_kwargs

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="web_research",
            confidence=0.98,
            reason="single step public web lookup",
        )
        result = await AgentTaskRouter(settings).route(
            query="请联网查询 PostgreSQL 16 RLS 的作用"
        )
        assert result.decision.intent == "web_research"

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="question_decomposition",
            confidence=0.98,
            reason="multi-step web comparison",
        )
        result = await AgentTaskRouter(settings).route(
            query="联网比较 RLS 与 security_invoker 并综合两份证据"
        )
        assert result.decision.intent == "question_decomposition"

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="structured_data_query",
            confidence=0.99,
            reason="single database query",
        )
        result = await AgentTaskRouter(settings).route(
            query="查询已授权模型资产的费用",
            dataset_query_bound=True,
        )
        assert result.decision.intent == "structured_data_query"
        assert result.source == "model"

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="knowledge_document_management",
            confidence=0.99,
            reason="invalid dataset route",
        )
        result = await AgentTaskRouter(settings).route(
            query="创建资产报告",
            dataset_query_bound=True,
        )
        assert result.decision.intent == "clarification_required"
        assert result.clarification_code == "dataset_query_invalid_intent"

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="simple_rag",
            confidence=0.96,
            reason="single fact",
        )
        result = await AgentTaskRouter(
            build_settings(AGENT_ROUTER_MODEL_NAME="qwen3.6-flash")
        ).route(query="FastAPI 是什么？")
        assert result.decision.intent == "simple_rag"
        assert FakeChatOpenAI.init_kwargs["extra_body"] == {
            "enable_thinking": False
        }

        FakeChatOpenAI.response = AgentRouteDecision(
            intent="question_decomposition",
            confidence=0.4,
            reason="uncertain",
        )
        result = await AgentTaskRouter(settings).route(query="帮我处理一下")
        assert result.decision.intent == "clarification_required"
        assert result.clarification_code == "router_low_confidence"

        FakeChatOpenAI.error = TimeoutError("timeout")
        result = await AgentTaskRouter(settings).route(query="继续")
        assert result.decision.intent == "clarification_required"
        assert result.clarification_code == "router_unavailable"
    finally:
        router_module.ChatOpenAI = original_chat_openai

    planner = AgentTaskPlanner(settings=build_settings())
    document_plan = planner.build_document_management_plan(
        query="请删除刚才找到的文档",
        user_id="router-test-user",
    )
    assert document_plan.task_kind == "knowledge_document_management"
    assert document_plan.sub_questions == []
    assert document_plan.steps == []

    initial_state = build_rag_agent_initial_state(
        RagChatRequest(query="你好", mode="hybrid", top_k=3),
        operation="run",
    )
    simple_update = await create_next_action_decision_node(
        settings,
        task_router=FixedRouter("simple_rag"),
        task_planner=ExplodingPlanner(),
    )(initial_state)
    assert simple_update["route_intent"] == "simple_rag"
    assert simple_update.get("agent_task_plan") is None

    document_update = await create_next_action_decision_node(
        settings,
        task_router=FixedRouter("knowledge_document_management"),
        task_planner=planner,
    )(
        build_rag_agent_initial_state(
            RagChatRequest(query="请删除刚才找到的文档", mode="hybrid", top_k=3),
            operation="run",
        )
    )
    assert document_update["route"] == "execute_task_plan"
    assert document_update["agent_task_plan"].steps == []
    assert route_after_loop_check({**initial_state, "route": "direct_web"}) == "direct_web"

    observed_web_call: dict[str, object] = {}
    observed_plan_call: dict[str, object] = {}
    original_web_search = nodes_module.search_web_with_bocha

    class FakeDirectWebPlanner:
        async def plan(self, **kwargs):
            observed_plan_call.update(kwargs)
            return DirectWebSearchPlan(
                query="PostgreSQL 16 row security policies",
                count=2,
                site="postgresql.org",
                exact_url=None,
            )

        async def select_candidate_url(self, **kwargs):
            urls = {item["url"] for item in kwargs["candidates"]}
            expected = "https://www.postgresql.org/docs/16/ddl-rowsecurity.html"
            return expected if expected in urls else None

    async def fake_web_search(**kwargs):
        observed_web_call.update(kwargs)
        return [
            SimpleNamespace(
                title="PostgreSQL 16 Row Security Policies",
                snippet="RLS restricts rows returned by a query.",
                summary="Official PostgreSQL 16 documentation.",
                url="https://www.postgresql.org/docs/16/ddl-rowsecurity.html",
                site_name="PostgreSQL",
            ),
            SimpleNamespace(
                title="Unrelated article",
                snippet="not official",
                summary="",
                url="https://example.com/postgresql-rls",
                site_name="Example",
            ),
        ]

    nodes_module.search_web_with_bocha = fake_web_search
    try:
        direct_web_update = await create_call_direct_web_node(
            settings,
            search_planner=FakeDirectWebPlanner(),
        )(
            {
                **initial_state,
                "query": "请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。",
            }
        )
    finally:
        nodes_module.search_web_with_bocha = original_web_search
    assert observed_plan_call["question"].startswith("请联网查询 PostgreSQL 16")
    assert observed_web_call["query"] == "PostgreSQL 16 row security policies"
    assert observed_web_call["site"] == "postgresql.org"
    assert [item.metadata["url"] for item in direct_web_update["docs"]] == [
        "https://www.postgresql.org/docs/16/ddl-rowsecurity.html"
    ]
    assert "https://www.postgresql.org/docs/16/ddl-rowsecurity.html" in direct_web_update["docs"][0].content
    assert nodes_module._official_page_text(
        "<style>hidden</style><h1>Row Security</h1><p>Policy &amp; role</p>"
    ) == "Row Security Policy & role"
    assert nodes_module._official_page_text(
        "<body><nav>menu</nav><main><h1>Workers</h1><p>Multiple processes</p></main></body>"
    ) == "Workers Multiple processes"

    class FakeSitemapResponse:
        content = b"""<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>https://fastapi.tiangolo.com/deployment/server-workers/</loc></url><url><loc>https://example.com/ignore/</loc></url></urlset>"""

        def raise_for_status(self):
            return None

    class FakeSitemapClient:
        async def get(self, *_args, **_kwargs):
            return FakeSitemapResponse()

    sitemap_candidates = await _official_sitemap_candidates(
        FakeSitemapClient(),
        plan=DirectWebSearchPlan(
            query="FastAPI multiple workers deployment",
            count=5,
            site="fastapi.tiangolo.com",
            required_content_terms=["workers"],
        ),
    )
    assert [item["url"] for item in sitemap_candidates] == [
        "https://fastapi.tiangolo.com/deployment/server-workers/"
    ]
    generic_official_plan = DirectWebSearchPlan(
        query="FastAPI deployment official documentation",
        count=3,
        site="fastapi.tiangolo.com",
        exact_url="https://fastapi.tiangolo.com/deployment/",
    )
    assert generic_official_plan.site == "fastapi.tiangolo.com"
    try:
        DirectWebSearchPlan(
            query="official documentation",
            count=3,
            site="example.com",
            exact_url="https://attacker.example.org/page",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("exact_url 不允许越过规划的官方网站域名")

    print("agent_task_router=passed")


if __name__ == "__main__":
    asyncio.run(main())
