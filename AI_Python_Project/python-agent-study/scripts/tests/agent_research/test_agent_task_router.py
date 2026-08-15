from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import PermissionCode
from fast_app.domain.research_task_plan import AgentTaskCapabilitySnapshot
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.rag_agent.rag_agent_nodes import (
    create_call_direct_web_node,
    create_next_action_decision_node,
    route_after_loop_check,
)
from fast_app.services.rag.direct_web_sitemap import _official_sitemap_candidates
import fast_app.services.rag.enhanced_web_search as enhanced_module
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.agent_tasks.agent_task_capability_service import (
    AgentTaskCapabilityService,
)
from fast_app.services.exceptions import (
    AgentTaskSourceUnavailableError,
    ExternalServiceError,
    ToolPermissionDeniedError,
)
from fast_app.services.rag.direct_web_page_text import extract_page_text
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


class RecordingResearchPlanner:
    def __init__(self) -> None:
        self.calls = 0
        self.request = None

    async def plan_question_decomposition(self, **kwargs):
        self.calls += 1
        self.request = kwargs["request"]
        return SimpleNamespace(
            task_plan_id="source-policy-test-plan",
            task_kind="question_decomposition",
        )


class DatasetScopeCapabilityService:
    async def resolve_research(self, **_kwargs):
        return AgentTaskCapabilitySnapshot(
            available_source_types=[
                "knowledge_retrieval",
                "nl2sql_query",
            ],
            web_direct_allowed=False,
            web_fallback_allowed=False,
            knowledge_retrieval_available=True,
            nl2sql_query_available=True,
            dataset_id="game_test",
            allowed_dataset_fields=[
                "asset_name",
                "cost_yuan",
                "polygon_count",
                "average_cost_yuan",
            ],
            dataset_field_synonyms={
                "cost_yuan": ["费用"],
                "polygon_count": ["模型面数"],
            },
            max_requirements=10,
            max_sub_questions=8,
        )


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
    read_only_document_query = (
        "仅根据 development/rag-backend-deployment.md 中的内容，列出 "
        "DATABASE_URL、MILVUS_PORT 和 ELASTICSEARCH_URL 的示例值；"
        "这是只读知识问答，不创建、修改或删除文档。"
    )
    # 否定语义中的“创建/修改/删除”不能被当成文档写操作；复杂度仍交给结构化 Router 判断。
    assert _route_with_high_confidence_rules(read_only_document_query) is None
    assert _route_with_high_confidence_rules(
        "读取 development/rag-backend-deployment.md 并总结；不要修改任何文档。"
    ) is None
    # 简单/复杂 Web 必须由结构化 Router 判断，关键词规则不能把复杂比较短路成 direct Web。
    assert _route_with_high_confidence_rules("请联网搜索 FastAPI 最新版本") is None
    assert _route_with_high_confidence_rules("阅读 https://fastapi.tiangolo.com/") is None
    # 历史中的“文档”不会被规则拼入当前 query；普通缓存操作必须交给语义 Router。
    assert _route_with_high_confidence_rules("删除 Redis 测试缓存") is None
    assert _route_with_high_confidence_rules("如何修改知识库文档？") is None

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
            intent="question_decomposition",
            confidence=0.98,
            reason="read-only multi-fact knowledge question",
        )
        result = await AgentTaskRouter(settings).route(
            query=read_only_document_query
        )
        assert result.decision.intent == "question_decomposition"
        assert result.source == "model"

        # Provider 可能轻微超过 reason 的展示上限。reason 只用于审计，不能因为
        # 它多出几个字符就丢弃已经合法的 intent/confidence 并降级为澄清。
        FakeChatOpenAI.response = {
            "intent": "question_decomposition",
            "confidence": 0.95,
            "reason": "路由说明" * 51,
        }
        result = await AgentTaskRouter(settings).route(
            query=(
                "仅根据 development/rag-backend-deployment.md，比较 Milvus 与 "
                "Elasticsearch 的权限过滤职责；这是只读知识问答。"
            )
        )
        assert result.decision.intent == "question_decomposition"
        assert result.source == "model"
        assert len(result.decision.reason) == 200

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

    web_settings = build_settings(BOCHA_API_KEY="configured")
    capability_service = AgentTaskCapabilityService(
        settings=web_settings,
        dataset_registry=None,
        nl2sql_authorization=object(),
    )
    web_user = CurrentUserContext(
        user_id="web-user",
        is_authenticated=True,
        auth_source="jwt",
        global_permission_codes=[
            PermissionCode.AGENT_TOOL_WEB_SEARCH.value
        ],
    )

    blocked_planner = RecordingResearchPlanner()
    blocked_state = build_rag_agent_initial_state(
        RagChatRequest(
            query=(
                "请联网比较 PostgreSQL 16 的 RLS 与 "
                "security_invoker，并综合两份网页证据。"
            ),
            allow_direct_web=False,
            allow_web_fallback=False,
        ),
        operation="stream_events",
        current_user=web_user,
    )
    try:
        await create_next_action_decision_node(
            web_settings,
            task_router=FixedRouter("question_decomposition"),
            task_planner=blocked_planner,
            capability_service=capability_service,
        )(blocked_state)
    except AgentTaskSourceUnavailableError:
        pass
    else:
        raise AssertionError("必需 Web 与请求策略冲突时必须在 Planner 前失败")
    assert blocked_planner.calls == 0

    denied_planner = RecordingResearchPlanner()
    denied_state = build_rag_agent_initial_state(
        RagChatRequest(
            query="请联网比较 RLS 与 security_invoker。",
            allow_direct_web=True,
            allow_web_fallback=False,
        ),
        operation="stream_events",
        current_user=CurrentUserContext(
            user_id="reader",
            is_authenticated=True,
            auth_source="jwt",
        ),
    )
    try:
        await create_next_action_decision_node(
            web_settings,
            task_router=FixedRouter("question_decomposition"),
            task_planner=denied_planner,
            capability_service=capability_service,
        )(denied_state)
    except ToolPermissionDeniedError:
        pass
    else:
        raise AssertionError("复杂 Web 请求无权限时必须在 Planner 前返回 403")
    assert denied_planner.calls == 0

    local_planner = RecordingResearchPlanner()
    local_update = await create_next_action_decision_node(
        web_settings,
        task_router=FixedRouter("question_decomposition"),
        task_planner=local_planner,
        capability_service=capability_service,
    )(
        build_rag_agent_initial_state(
            RagChatRequest(
                query="比较混合检索与 rerank 的职责。",
                allow_direct_web=False,
                allow_web_fallback=False,
            ),
            operation="stream_events",
            current_user=web_user,
        )
    )
    assert local_planner.calls == 1
    assert local_update["route"] == "execute_task_plan"

    dataset_planner = RecordingResearchPlanner()
    dataset_update = await create_next_action_decision_node(
        web_settings,
        task_router=FixedRouter("question_decomposition"),
        task_planner=dataset_planner,
        capability_service=DatasetScopeCapabilityService(),
    )(
        build_rag_agent_initial_state(
            RagChatRequest(
                query="比较角色资产01和角色资产06的费用、模型面数",
                dataset_id="game_test",
                nl2sql_action="query",
                allow_direct_web=False,
                allow_web_fallback=False,
            ),
            operation="stream_events",
            current_user=web_user,
        )
    )
    assert dataset_update["route"] == "execute_task_plan"
    assert dataset_planner.calls == 1
    assert dataset_planner.request.dataset_scope.explicit_fields == [
        "cost_yuan",
        "polygon_count",
    ]

    observed_web_calls: list[dict[str, object]] = []
    original_web_search = enhanced_module.search_web_with_bocha
    # 增强服务的 httpx.AsyncClient 构造点在 enhanced_web_search 模块内，
    # 必须 patch enhanced_module.httpx 才能把假客户端注入共享服务层。
    original_http_client = enhanced_module.httpx.AsyncClient

    class FakeDirectWebPlanner:
        def __init__(self, plan: DirectWebSearchPlan) -> None:
            self.search_plan = plan
            self.selection_calls = 0
            self.last_candidates: list[dict[str, str]] = []

        async def plan(self, **_kwargs):
            return self.search_plan

        async def select_candidate_url(self, **kwargs):
            self.selection_calls += 1
            self.last_candidates = kwargs["candidates"]
            return kwargs["candidates"][0]["url"]

    async def fake_web_search(**kwargs):
        observed_web_calls.append(kwargs)
        site = kwargs["site"]
        domain = site or "example.com"
        # query 里带 "has16"/"version15" 时模拟搜索引擎同时召回
        # 新旧版本页面，用于验证候选池的 URL 片段硬约束。
        extra = []
        if "has16" in kwargs.get("query", ""):
            extra.append(
                SimpleNamespace(
                    title="New version page",
                    snippet="current docs",
                    summary="version 16 page",
                    url=f"https://{domain}/docs/16/page.html",
                    site_name=domain,
                )
            )
        if "version15" in kwargs.get("query", ""):
            extra.append(
                SimpleNamespace(
                    title="Old version page",
                    snippet="legacy docs",
                    summary="version 15 page",
                    url=f"https://{domain}/docs/15/page.html",
                    site_name=domain,
                )
            )
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
            *extra,
        ]

    class FakePageResponse:
        content = b""
        # 正文必须超过正文提取的最小有效字符数，才能命中全文路径。
        text = (
            "<main><h1>FastAPI lifespan</h1><p>Selected page</p>"
            "<p>" + "FastAPI lifespan 实践说明。" * 30 + "</p></main>"
        )
        url = "https://docs.python.org/3/library/typing.html"

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

    enhanced_module.search_web_with_bocha = fake_web_search
    enhanced_module.httpx.AsyncClient = FakeHttpClient
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

        # 盲区 A 回归：候选池必须保留 URL 片段硬约束，
        # 错误版本页面不得进入选择器视野。
        version_update, version_planner = await run_direct_web_case(
            "查询 PostgreSQL 16 官方文档",
            DirectWebSearchPlan(
                query="PostgreSQL 16 row security has16 version15",
                count=2,
                source_mode="official",
                result_strategy="single_best_page",
                site="docs.python.org",
                required_url_fragments=["16"],
            ),
        )
        assert version_planner.selection_calls == 1
        candidate_urls = [
            item["url"] for item in version_planner.last_candidates
        ]
        assert all("16" in url for url in candidate_urls)
        assert len(version_update["docs"]) == 1
    finally:
        enhanced_module.search_web_with_bocha = original_web_search
        enhanced_module.httpx.AsyncClient = original_http_client

    assert extract_page_text(
        "<style>hidden</style><h1>Row Security</h1><p>Policy &amp; role</p>"
    ) == ""
    long_body = "<p>" + "行级安全策略实践说明。" * 40 + "</p>"
    assert (
        extract_page_text(f"<body><nav>menu</nav>{long_body}</body>")
        == "行级安全策略实践说明。" * 40
    )

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
        "required_url_fragments": ("JSON 字符串数组", "[]", "最多 5 项", "版本号"),
        "required_content_terms": ("JSON 字符串数组", "[]", "最多 2 项"),
    }
    for field_name, markers in description_markers.items():
        description = plan_schema[field_name]["description"]
        assert all(marker in description for marker in markers)
    assert "必须包含且只能包含" in DIRECT_WEB_SEARCH_PLANNER_PROMPT
    assert "版本号" in DIRECT_WEB_SEARCH_PLANNER_PROMPT
    assert "禁止编造版本片段" in DIRECT_WEB_SEARCH_PLANNER_PROMPT
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

        def with_structured_output(self, _schema, method, **_kwargs):
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

    drop_planner = DirectWebSearchPlanner(settings)
    drop_planner._model = RecordingStructuredModel(
        {
            "query": "PostgreSQL 16 row level security",
            "count": 3,
            "source_mode": "official",
            "result_strategy": "single_best_page",
            "site": "postgresql.org",
            "exact_url": "http://www.postgresql.org/docs/current/ddl-rowsecurity.html",
        }
    )
    dropped_plan = await drop_planner.plan(
        question="查询 PostgreSQL 16 官方文档的行级安全策略",
        count=3,
    )
    assert dropped_plan.exact_url is None
    assert dropped_plan.site == "postgresql.org"

    empty_url_planner = DirectWebSearchPlanner(settings)
    empty_url_planner._model = RecordingStructuredModel(
        {
            "query": "PostgreSQL 16 row level security",
            "count": 3,
            "source_mode": "official",
            "result_strategy": "single_best_page",
            "site": "postgresql.org",
            "exact_url": "",
        }
    )
    empty_url_plan = await empty_url_planner.plan(
        question="查询 PostgreSQL 16 官方文档的行级安全策略",
        count=3,
    )
    assert empty_url_plan.exact_url is None

    print("agent_task_router=passed")


if __name__ == "__main__":
    asyncio.run(main())
