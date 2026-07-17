from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.api.rag_chat_routes import rag_chat_structured_sse_event_generator
from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.rerankers.mock_reranker import MockReranker
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.agent_tasks.agent_task_router import (
    AgentRouteDecision,
    AgentTaskRouteResult,
)
from fast_app.services.conversation.conversation_memory import InMemoryConversationMemoryStore
from fast_app.services.rag.rag_agent_pipeline_service import RagAgentPipeline


class ClarificationRouter:
    async def route(self, **_kwargs):
        return AgentTaskRouteResult(
            decision=AgentRouteDecision(
                intent="clarification_required",
                confidence=0.52,
                reason="ambiguous",
                clarification_question="请明确希望普通问答、联网检索还是文档操作。",
            ),
            source="model",
            latency_ms=2.5,
            clarification_code="ambiguous_intent",
        )


def parse_sse_name(payload: str) -> str:
    return payload.splitlines()[0].removeprefix("event: ")


async def main() -> None:
    settings = Settings(
        _env_file=None,
        AGENT_ROUTER_API_KEY="router-key",
        AGENT_ROUTER_BASE_URL="https://router.example/v1",
        AGENT_ROUTER_MODEL_NAME="router-model",
        LANGSMITH_TRACING=False,
        PROMPT_GUARD_ENABLED=False,
    )
    memory_store = InMemoryConversationMemoryStore()
    pipeline = RagAgentPipeline(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(settings=settings),
        reranker=MockReranker(),
        conversation_memory_store=memory_store,
        task_router=cast(Any, ClarificationRouter()),
    )
    request = RagChatRequest(
        session_id="router-clarification-test",
        query="帮我处理一下",
        mode="hybrid",
        top_k=3,
    )

    response = await pipeline.run(request)
    assert response.clarification_required is True
    assert response.clarification_code == "ambiguous_intent"
    assert response.route_intent == "clarification_required"
    assert response.route_confidence == 0.52
    assert response.agent_task_plan is None
    assert response.answer == response.clarification_question
    messages = await memory_store.list_recent_messages(
        "router-clarification-test",
        limit=10,
    )
    assert [message.role.value for message in messages] == ["user", "assistant"]
    assert messages[-1].content == response.clarification_question

    events = [event async for event in pipeline.stream_events(request)]
    names = [event.event for event in events]
    assert names[:3] == [
        "agent_route_clarification_required",
        "sources",
        "answer_delta",
    ]
    assert events[1].data == {"sources": []}

    sse_payloads = [
        payload
        async for payload in rag_chat_structured_sse_event_generator(
            request,
            cast(Any, pipeline),
        )
    ]
    sse_names = [parse_sse_name(payload) for payload in sse_payloads]
    assert sse_names[:3] == names[:3]
    assert sse_names[-1] == "done"
    done_data = json.loads(sse_payloads[-1].split("data: ", 1)[1])
    assert done_data == {"status": "done"}
    assert "error" not in sse_names

    print("agent_router_clarification_flow=passed")


if __name__ == "__main__":
    asyncio.run(main())
