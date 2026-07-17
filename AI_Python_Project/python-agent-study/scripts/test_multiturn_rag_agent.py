import argparse
import asyncio
import sys
from typing import Any, cast
from uuid import uuid4

from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.rerankers.mock_reranker import MockReranker
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings, get_settings
from fast_app.domain.conversation_models import ConversationMessage, ConversationRole
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.conversation.conversation_history import (
    ConversationHistoryWindow,
    format_history_messages,
)
from fast_app.services.conversation.conversation_memory import InMemoryConversationMemoryStore
from fast_app.services.conversation.conversation_scope import (
    get_request_external_session_id,
    get_request_user_id,
    scope_rag_chat_request,
)
from fast_app.services.conversation.query_rewrite import ConversationQueryRewriter
from fast_app.services.rag.rag_agent_pipeline_service import RagAgentPipeline


FIRST_TURN_QUERY = "什么是混合检索？"
FIRST_TURN_ANSWER = "混合检索会结合向量检索和关键词检索。"
SECOND_TURN_QUERY = "它和只用向量检索有什么区别？"
EXPECTED_TOPIC = "混合检索"


class RecordingConversationPersistence:
    """Record save_turn calls without requiring a real PostgreSQL connection."""

    def __init__(self) -> None:
        self.saved_turns: list[dict[str, Any]] = []

    async def save_turn(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, object],
        user_id: str | None = None,
    ) -> None:
        self.saved_turns.append(
            {
                "conversation_id": conversation_id,
                "user_content": user_content,
                "assistant_content": assistant_content,
                "metadata": metadata,
                "user_id": user_id,
            }
        )


def print_field(name: str, value: object) -> None:
    """Print with unicode_escape so PowerShell code pages cannot hide failures."""

    text = str(value)
    print(f"{name}={text.encode('unicode_escape').decode('ascii')}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_history_window() -> ConversationHistoryWindow:
    messages = [
        ConversationMessage(
            conversation_id="rewrite-only",
            role=ConversationRole.USER,
            content=FIRST_TURN_QUERY,
        ),
        ConversationMessage(
            conversation_id="rewrite-only",
            role=ConversationRole.ASSISTANT,
            content=FIRST_TURN_ANSWER,
        ),
    ]
    return ConversationHistoryWindow(
        conversation_id="rewrite-only",
        messages=messages,
        formatted_text=format_history_messages(messages),
    )


def build_pipeline(
    settings: Settings,
    store: InMemoryConversationMemoryStore,
    persistence: RecordingConversationPersistence | None = None,
) -> RagAgentPipeline:
    """Build an in-process RAG Agent pipeline focused on memory/rewrite behavior."""

    return RagAgentPipeline(
        settings=settings,
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(settings=settings),
        reranker=MockReranker(),
        conversation_memory_store=store,
        query_rewriter=ConversationQueryRewriter.from_settings(settings),
        conversation_persistence=cast(Any, persistence),
    )


def assert_conversation_scope_builder() -> None:
    req = RagChatRequest(
        session_id="same-session",
        query=FIRST_TURN_QUERY,
        mode="hybrid",
        top_k=3,
    )
    alice_req = scope_rag_chat_request(
        req=req,
        user=CurrentUserContext(user_id="alice", auth_source="demo_header"),
    )
    bob_req = scope_rag_chat_request(
        req=req,
        user=CurrentUserContext(user_id="bob", auth_source="demo_header"),
    )

    print(f"scope_alice_session_id={alice_req.session_id}")
    print(f"scope_bob_session_id={bob_req.session_id}")
    print(f"scope_user_id={get_request_user_id(alice_req)}")
    print(f"scope_external_session_id={get_request_external_session_id(alice_req)}")

    require(
        alice_req.session_id != bob_req.session_id,
        "expected same external session_id to produce different scoped ids per user",
    )
    require(
        get_request_user_id(alice_req) == "alice",
        "expected scoped request to preserve internal user_id",
    )
    require(
        get_request_external_session_id(alice_req) == "same-session",
        "expected scoped request to preserve external session_id for traceability",
    )
    require(
        "user_id" not in alice_req.model_dump(),
        "expected user_id to stay out of public request model fields",
    )


async def assert_real_query_rewrite(settings: Settings, timeout_seconds: float) -> None:
    rewriter = ConversationQueryRewriter.from_settings(settings)
    require(
        rewriter.chain is not None,
        (
            "query rewrite model is unavailable. "
            "Set LLM_PROVIDER=qwen, QUERY_REWRITE_ENABLED=true, and OPENAI_API_KEY."
        ),
    )

    result = await asyncio.wait_for(
        rewriter.rewrite(
            query=SECOND_TURN_QUERY,
            history_window=build_history_window(),
        ),
        timeout=timeout_seconds,
    )

    print_field("rewrite_original_query", result.original_query)
    print_field("rewrite_rewritten_query", result.rewritten_query)
    print(f"rewrite_used_history={result.used_history}")
    print(f"rewrite_reason={result.reason}")
    print(f"rewrite_contains_expected_topic={EXPECTED_TOPIC in result.rewritten_query}")

    require(result.used_history, "expected query rewrite to use history")
    require(
        EXPECTED_TOPIC in result.rewritten_query,
        f"expected rewritten query to contain {EXPECTED_TOPIC}",
    )


async def assert_multiturn_run(settings: Settings, timeout_seconds: float) -> None:
    store = InMemoryConversationMemoryStore()
    pipeline = build_pipeline(settings=settings, store=store)
    session_id = f"verify-14-10-{uuid4().hex[:8]}"

    first_response = await pipeline.run(
        RagChatRequest(
            session_id=session_id,
            query=FIRST_TURN_QUERY,
            mode="hybrid",
            top_k=3,
        )
    )
    messages_after_first = await store.list_recent_messages(session_id, 10)

    require(len(messages_after_first) == 2, "expected first turn to save 2 messages")
    print(f"messages_after_first={len(messages_after_first)}")
    print_field("response1_query", first_response.query)

    second_response = await asyncio.wait_for(
        pipeline.run(
            RagChatRequest(
                session_id=session_id,
                query=SECOND_TURN_QUERY,
                mode="hybrid",
                top_k=3,
            )
        ),
        timeout=timeout_seconds,
    )
    messages_after_second = await store.list_recent_messages(session_id, 10)

    print(f"messages_after_second={len(messages_after_second)}")
    print_field("response2_query", second_response.query)
    print(f"response2_contains_expected_topic={EXPECTED_TOPIC in second_response.query}")
    print(f"response2_source_count={len(second_response.sources)}")

    require(len(messages_after_second) == 4, "expected second turn to save 4 messages total")
    require(
        EXPECTED_TOPIC in second_response.query,
        f"expected second response query to contain {EXPECTED_TOPIC}",
    )
    require(second_response.sources, "expected second response to include sources")


async def assert_stream_contracts(settings: Settings, timeout_seconds: float) -> None:
    store = InMemoryConversationMemoryStore()
    persistence = RecordingConversationPersistence()
    pipeline = build_pipeline(settings=settings, store=store, persistence=persistence)
    session_id = f"verify-14-10-stream-{uuid4().hex[:8]}"

    await pipeline.run(
        RagChatRequest(
            session_id=session_id,
            query=FIRST_TURN_QUERY,
            mode="hybrid",
            top_k=3,
        )
    )

    token_items: list[str] = []
    stream_req = RagChatRequest(
        session_id=session_id,
        query=SECOND_TURN_QUERY,
        mode="hybrid",
        top_k=3,
    )
    async with asyncio.timeout(timeout_seconds):
        async for token in pipeline.stream(stream_req):
            token_items.append(token)

    messages_after_stream = await store.list_recent_messages(session_id, 10)
    stream_saved_turn = persistence.saved_turns[-1]
    print(f"stream_item_type_all_str={all(isinstance(item, str) for item in token_items)}")
    print(f"stream_token_count={len(token_items)}")
    print(f"messages_after_stream={len(messages_after_stream)}")
    print(f"stream_persistence_operation={stream_saved_turn['metadata'].get('operation')}")

    require(token_items, "expected stream to produce tokens")
    require(
        all(isinstance(item, str) for item in token_items),
        "expected pipeline.stream() to yield str tokens only",
    )
    require(
        len(messages_after_stream) == 4,
        "expected stream turn to save messages after completion",
    )
    require(
        stream_saved_turn["metadata"].get("operation") == "stream",
        "expected stream turn to be persisted with operation=stream",
    )

    event_names: list[str] = []
    stream_events_req = RagChatRequest(
        session_id=session_id,
        query=SECOND_TURN_QUERY,
        mode="hybrid",
        top_k=3,
    )
    async with asyncio.timeout(timeout_seconds):
        async for event in pipeline.stream_events(stream_events_req):
            event_names.append(event.event)

    messages_after_stream_events = await store.list_recent_messages(session_id, 20)
    stream_events_saved_turn = persistence.saved_turns[-1]
    print(f"stream_events_first={event_names[0] if event_names else '<none>'}")
    print(f"stream_events_has_token={'token' in event_names}")
    print(f"stream_events_count={len(event_names)}")
    print(f"messages_after_stream_events={len(messages_after_stream_events)}")
    print(
        "stream_events_persistence_operation="
        f"{stream_events_saved_turn['metadata'].get('operation')}"
    )

    require(event_names, "expected stream_events to produce events")
    require(event_names[0] == "sources", "expected first stream_events event to be sources")
    require("token" in event_names, "expected stream_events to include token events")
    require(
        len(messages_after_stream_events) == 6,
        "expected stream_events turn to save messages after completion",
    )
    require(
        stream_events_saved_turn["metadata"].get("operation") == "stream_events",
        "expected stream_events turn to be persisted with operation=stream_events",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regression test for phase 14-10 multi-turn RAG Agent memory and query rewrite.",
    )
    parser.add_argument(
        "--rewrite-only",
        action="store_true",
        help="Only verify real LLM query rewrite behavior.",
    )
    parser.add_argument(
        "--skip-stream",
        action="store_true",
        help="Skip pipeline.stream and stream_events checks.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="Timeout for real LLM rewrite and stream checks.",
    )
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    settings = get_settings()

    assert_conversation_scope_builder()

    await assert_real_query_rewrite(
        settings=settings,
        timeout_seconds=args.timeout_seconds,
    )

    if args.rewrite_only:
        return

    await assert_multiturn_run(
        settings=settings,
        timeout_seconds=args.timeout_seconds,
    )

    if not args.skip_stream:
        await assert_stream_contracts(
            settings=settings,
            timeout_seconds=args.timeout_seconds,
        )


def main() -> int:
    try:
        asyncio.run(main_async())
        return 0
    except AssertionError as exc:
        print(f"assertion_failed={exc}", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print(f"timeout={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
