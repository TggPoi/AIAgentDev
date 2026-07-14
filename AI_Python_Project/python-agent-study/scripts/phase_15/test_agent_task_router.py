from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.graph.rag_agent_nodes import create_next_action_decision_node
from fast_app.graph.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services import agent_task_router as router_module
from fast_app.services.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_task_router import (
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

    def __init__(self, **_kwargs) -> None:
        pass

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

    assert _route_with_high_confidence_rules(
        "请修改 docs/development/rag.md 文档"
    ).intent == "knowledge_document_management"
    assert _route_with_high_confidence_rules("请联网搜索 FastAPI 最新版本").intent == "web_research"
    assert _route_with_high_confidence_rules("阅读 https://fastapi.tiangolo.com/").intent == "web_research"
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

    web_plan = planner.build_web_research_plan(
        query="请联网搜索 FastAPI 官方部署建议",
        user_id="router-test-user",
    )
    assert len(web_plan.sub_questions) == 1
    assert web_plan.sub_questions[0].information_source_hint == "web_search"

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

    print("agent_task_router=passed")


if __name__ == "__main__":
    asyncio.run(main())
