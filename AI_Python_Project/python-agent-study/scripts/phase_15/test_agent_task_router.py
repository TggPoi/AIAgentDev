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
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.rag.direct_web_search_planner import (
    DIRECT_WEB_CANDIDATE_SELECTOR_PROMPT,
    DIRECT_WEB_SEARCH_PLANNER_PROMPT,
    DirectWebCandidateSelection,
    DirectWebSearchPlan,
    DirectWebSearchPlanner,
)
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

    observed_web_calls: list[dict[str, object]] = []
    original_web_search = nodes_module.search_web_with_bocha
    original_http_client = nodes_module.httpx.AsyncClient

    class FakeDirectWebPlanner:
        def __init__(self, plan: DirectWebSearchPlan) -> None:
            self.search_plan = plan
            self.selection_calls = 0

        async def plan(self, **_kwargs):
            return self.search_plan

        async def select_candidate_url(self, **kwargs):
            self.selection_calls += 1
            return kwargs["candidates"][0]["url"]

    async def fake_web_search(**kwargs):
        observed_web_calls.append(kwargs)
        site = kwargs["site"]
        domain = site or "example.com"
        return [
            SimpleNamespace(
                title="FastAPI lifespan solution one",
                snippet="FastAPI lifespan practical experience",
                summary="First relevant result",
                url=f"https://{domain}/questions/1",
                site_name=domain,
            ),
            SimpleNamespace(
                title="FastAPI lifespan solution two",
                snippet="FastAPI lifespan practical experience",
                summary="Second relevant result",
                url=f"https://{domain}/questions/2",
                site_name=domain,
            ),
        ]

    class FakePageResponse:
        content = b""
        text = "<main><h1>FastAPI lifespan</h1><p>Selected page</p></main>"

        def raise_for_status(self):
            return None

    class FakeHttpClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return FakePageResponse()

    async def run_direct_web_case(
        question: str,
        plan: DirectWebSearchPlan,
    ) -> tuple[dict[str, object], FakeDirectWebPlanner]:
        fake_planner = FakeDirectWebPlanner(plan)
        update = await create_call_direct_web_node(
            settings,
            search_planner=fake_planner,
        )({**initial_state, "query": question})
        return update, fake_planner

    nodes_module.search_web_with_bocha = fake_web_search
    nodes_module.httpx.AsyncClient = FakeHttpClient
    try:
        official_update, official_planner = await run_direct_web_case(
            "查询 Python 3.13 官方 typing 文档",
            DirectWebSearchPlan(
                query="Python 3.13 typing documentation",
                count=2,
                source_mode="official",
                result_strategy="single_best_page",
                site="docs.python.org",
            ),
        )
        assert official_planner.selection_calls == 1
        assert len(official_update["docs"]) == 1
        assert "Selected page" in official_update["docs"][0].content

        community_update, community_planner = await run_direct_web_case(
            "搜索社区中关于 FastAPI lifespan 的实践经验",
            DirectWebSearchPlan(
                query="FastAPI lifespan community experience",
                count=2,
                source_mode="community",
                result_strategy="multiple_sources",
            ),
        )
        assert community_planner.selection_calls == 0
        assert len(community_update["docs"]) == 2

        stack_update, stack_planner = await run_direct_web_case(
            "搜索 Stack Overflow 上关于 FastAPI lifespan 的多个解决方案",
            DirectWebSearchPlan(
                query="FastAPI lifespan multiple solutions",
                count=2,
                source_mode="specified_site",
                result_strategy="multiple_sources",
                site="stackoverflow.com",
            ),
        )
        assert stack_planner.selection_calls == 0
        assert len(stack_update["docs"]) == 2
        assert observed_web_calls[-1]["site"] == "stackoverflow.com"

        github_update, github_planner = await run_direct_web_case(
            "查询 GitHub Discussions 中关于该问题的不同观点",
            DirectWebSearchPlan(
                query="FastAPI lifespan different viewpoints",
                count=2,
                source_mode="specified_site",
                result_strategy="multiple_sources",
                site="github.com",
            ),
        )
        assert github_planner.selection_calls == 0
        assert len(github_update["docs"]) == 2

        best_update, best_planner = await run_direct_web_case(
            "在 Stack Overflow 中找一个最相关的解决方案",
            DirectWebSearchPlan(
                query="FastAPI lifespan best solution",
                count=2,
                source_mode="specified_site",
                result_strategy="single_best_page",
                site="stackoverflow.com",
            ),
        )
        assert best_planner.selection_calls == 1
        assert len(best_update["docs"]) == 1
    finally:
        nodes_module.search_web_with_bocha = original_web_search
        nodes_module.httpx.AsyncClient = original_http_client

    assert nodes_module._direct_page_text(
        "<style>hidden</style><h1>Row Security</h1><p>Policy &amp; role</p>"
    ) == "Row Security Policy & role"
    assert nodes_module._direct_page_text(
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
            source_mode="official",
            result_strategy="single_best_page",
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
        source_mode="official",
        result_strategy="single_best_page",
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

    try:
        DirectWebSearchPlan(
            query="official documentation",
            count=3,
            source_mode="official",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("官方来源缺少 site 时必须拒绝")

    default_plan = DirectWebSearchPlan(query="FastAPI lifespan", count=3)
    assert default_plan.source_mode == "general"
    assert default_plan.result_strategy == "multiple_sources"

    plan_schema = DirectWebSearchPlan.model_json_schema()["properties"]
    description_markers = {
        "query": ("JSON 字符串", "不回答问题"),
        "count": ("JSON 整数", "1 到 10", "禁止"),
        "source_mode": ("四个值之一", "official", "community", "specified_site"),
        "result_strategy": ("两个值之一", "single_best_page", "multiple_sources"),
        "site": ("JSON null", "空字符串", "不代表官方网站"),
        "exact_url": ("HTTPS", "JSON null", "同时提供 site"),
        "required_url_fragments": ("JSON 字符串数组", "[]", "最多 5 项"),
        "required_content_terms": ("JSON 字符串数组", "[]", "最多 5 项"),
    }
    for field_name, markers in description_markers.items():
        description = plan_schema[field_name]["description"]
        assert all(marker in description for marker in markers)
    assert "必须包含且只能包含" in DIRECT_WEB_SEARCH_PLANNER_PROMPT
    assert "输出前逐字段检查" in DIRECT_WEB_SEARCH_PLANNER_PROMPT

    selection_description = DirectWebCandidateSelection.model_json_schema()[
        "properties"
    ]["selected_url"]["description"]
    assert all(
        marker in selection_description
        for marker in ("完全一致", "JSON null", "候选列表之外")
    )
    assert "不得输出解释、Markdown 或额外字段" in DIRECT_WEB_CANDIDATE_SELECTOR_PROMPT

    class RecordingStructuredModel:
        def __init__(self, response) -> None:
            self.response = response
            self.messages = []

        def with_structured_output(self, _schema, method):
            assert method == "function_calling"
            return self

        async def ainvoke(self, messages, config=None):
            self.messages = messages
            return self.response

    selector_planner = DirectWebSearchPlanner(settings)
    selector_model = RecordingStructuredModel(
        DirectWebCandidateSelection(
            selected_url="https://attacker.example/page"
        )
    )
    selector_planner._model = selector_model
    selected_url = await selector_planner.select_candidate_url(
        question="在 Stack Overflow 中找一个最相关的解决方案",
        plan=DirectWebSearchPlan(
            query="FastAPI lifespan best solution",
            count=2,
            source_mode="specified_site",
            result_strategy="single_best_page",
            site="stackoverflow.com",
        ),
        candidates=[
            {
                "title": "Allowed",
                "url": "https://stackoverflow.com/questions/1",
                "summary": "FastAPI lifespan",
            }
        ],
    )
    assert selected_url is None
    selector_payload = selector_model.messages[-1].content
    assert '"source_mode": "specified_site"' in selector_payload
    assert '"result_strategy": "single_best_page"' in selector_payload

    invalid_planner = DirectWebSearchPlanner(settings)
    invalid_planner._model = RecordingStructuredModel(
        {
            "query": "Python typing official documentation",
            "count": 2,
            "source_mode": "official",
            "result_strategy": "single_best_page",
            "site": None,
        }
    )
    try:
        await invalid_planner.plan(
            question="查询 Python 官方文档",
            count=2,
        )
    except ExternalServiceError:
        pass
    else:
        raise AssertionError("非法 Planner 结构化输出必须转换为统一服务异常")

    print("agent_task_router=passed")


if __name__ == "__main__":
    asyncio.run(main())
