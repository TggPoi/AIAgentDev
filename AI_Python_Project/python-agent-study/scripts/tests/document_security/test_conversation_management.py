"""验证会话 CRUD、用户隔离和 structured stream 统一 turn 持久化。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from fast_app.api.conversation_routes import router
from fast_app.api.rag_chat_routes import rag_chat_structured_sse_event_generator
from fast_app.core.config import get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.conversation_dependencies import (
    get_conversation_catalog_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.conversation_schema import (
    ConversationItem,
    ConversationListResponse,
    ConversationMessageListResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)
from fast_app.schemas.rag_chat_schema import (
    RagChatRequest,
    RagScoreBreakdown,
    RagSource,
)
from fast_app.services.auth.auth_crypto import hash_password
from fast_app.services.conversation.conversation_catalog_service import (
    ConversationCatalogService,
)
from fast_app.services.conversation.conversation_memory import (
    InMemoryConversationMemoryStore,
)
from fast_app.services.conversation.conversation_repository import (
    PostgresConversationRepository,
)
from fast_app.services.conversation.conversation_scope import (
    scope_rag_chat_request,
)
from fast_app.services.conversation.structured_turn_recorder import (
    StructuredConversationTurnRecorder,
    StructuredTurnState,
)
from fast_app.services.exceptions import ConversationNotFoundError, ExternalServiceError


USER_A = "user_conversation_management_a"
USER_B = "user_conversation_management_b"


class EventPipeline:
    def __init__(
        self,
        provider: str,
        events: list[RagStreamEvent],
        *,
        fail: bool = False,
    ) -> None:
        self.pipeline_provider = provider
        self._events = events
        self._fail = fail

    async def stream_events(self, _: RagChatRequest):
        for event in self._events:
            yield event
        if self._fail:
            raise ExternalServiceError("provider unavailable")


def main() -> None:
    asyncio.run(assert_database_and_stream_flow())
    assert_http_contract()
    print("conversation_management=passed")


async def assert_database_and_stream_flow() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    memory = InMemoryConversationMemoryStore()
    try:
        async with session_factory() as session:
            await _cleanup(session)
            await _seed_users(session)
            repository = PostgresConversationRepository(session)
            recorder = StructuredConversationTurnRecorder(
                repository=repository,
                memory_store=memory,
            )
            catalog = ConversationCatalogService(
                repository=repository,
                memory_store=memory,
            )
            user_a = _user(USER_A)
            user_b = _user(USER_B)

            await _run_success_stream(
                recorder,
                user_a,
                session_id="shared-session",
                provider="rag_agent",
                query="simple rag question",
                answer="simple rag answer",
            )
            await _run_success_stream(
                recorder,
                user_a,
                session_id="shared-session",
                provider="rag_agent",
                query="web research question",
                answer="web research answer",
            )
            await _run_success_stream(
                recorder,
                user_a,
                session_id="shared-session",
                provider="rag_agent",
                query="agent question",
                answer="agent answer",
                task_plan_id="task-plan-conversation",
                task_status="waiting_confirmation",
            )
            await _run_error_stream(
                recorder,
                user_a,
                session_id="shared-session",
            )
            await _run_aborted_stream(
                recorder,
                user_a,
                session_id="aborted-session",
            )
            await _run_success_stream(
                recorder,
                user_b,
                session_id="shared-session",
                provider="rag_agent",
                query="other user question",
                answer="other user answer",
            )

            empty = await catalog.create_conversation(
                user_a,
                CreateConversationRequest(title="  Empty   Conversation  "),
            )
            assert empty.title == "Empty Conversation"

            page_one = await catalog.list_conversations(
                user_a,
                cursor=None,
                limit=2,
            )
            assert len(page_one.items) == 2
            assert page_one.next_cursor is not None
            page_two = await catalog.list_conversations(
                user_a,
                cursor=page_one.next_cursor,
                limit=10,
            )
            conversations = [*page_one.items, *page_two.items]
            assert {item.session_id for item in conversations} == {
                "shared-session",
                "aborted-session",
                empty.session_id,
            }
            other_page = await catalog.list_conversations(
                user_b,
                cursor=None,
                limit=20,
            )
            assert [item.session_id for item in other_page.items] == [
                "shared-session"
            ]

            empty_before = next(
                item for item in conversations if item.session_id == empty.session_id
            )
            renamed = await catalog.rename_conversation(
                user_a,
                empty.session_id,
                UpdateConversationRequest(title="Renamed Conversation"),
            )
            assert renamed.title == "Renamed Conversation"
            assert renamed.updated_at == empty_before.updated_at
            assert renamed.message_count == 0

            first_messages = await catalog.list_messages(
                user_a,
                "shared-session",
                cursor=None,
                limit=3,
            )
            assert len(first_messages.items) == 3
            assert first_messages.next_cursor is not None
            second_messages = await catalog.list_messages(
                user_a,
                "shared-session",
                cursor=first_messages.next_cursor,
                limit=20,
            )
            messages = [*first_messages.items, *second_messages.items]
            assert len(messages) == 8
            assert [item.role for item in messages[:2]] == ["user", "assistant"]
            assert messages[1].sources[0].doc_id == "doc-conversation-source"
            agent_message = next(
                item for item in messages if item.content == "agent answer"
            )
            assert agent_message.agent_task_plan_id == "task-plan-conversation"
            assert agent_message.agent_task_status == "waiting_confirmation"
            error_message = messages[-1]
            assert error_message.role == "assistant"
            assert error_message.terminal_status == "error"

            aborted = await catalog.list_messages(
                user_a,
                "aborted-session",
                cursor=None,
                limit=20,
            )
            assert len(aborted.items) == 1
            assert aborted.items[0].role == "user"
            assert aborted.items[0].terminal_status == "aborted"

            b_messages = await catalog.list_messages(
                user_b,
                "shared-session",
                cursor=None,
                limit=20,
            )
            assert len(b_messages.items) == 2
            assert all("other user" in item.content for item in b_messages.items)

            try:
                await catalog.list_messages(
                    user_b,
                    empty.session_id,
                    cursor=None,
                    limit=20,
                )
            except ConversationNotFoundError:
                pass
            else:
                raise AssertionError("其他用户读取了同名空间外的会话")

            scoped_shared = scope_rag_chat_request(
                RagChatRequest(query="x", session_id="shared-session"),
                user_a,
            ).session_id
            assert scoped_shared is not None
            assert await memory.list_recent_messages(scoped_shared, 50)
            await catalog.delete_conversation(user_a, "shared-session")
            await catalog.delete_conversation(user_a, "shared-session")
            assert await memory.list_recent_messages(scoped_shared, 50) == []
            try:
                await catalog.list_messages(
                    user_a,
                    "shared-session",
                    cursor=None,
                    limit=20,
                )
            except ConversationNotFoundError:
                pass
            else:
                raise AssertionError("删除后仍可读取 durable history")

            await _run_success_stream(
                recorder,
                user_a,
                session_id="shared-session",
                provider="rag_agent",
                query="reused question",
                answer="reused answer",
            )
            reused = await catalog.list_messages(
                user_a,
                "shared-session",
                cursor=None,
                limit=20,
            )
            assert [item.content for item in reused.items] == [
                "reused question",
                "reused answer",
            ]

            idempotent_request = _scoped_request(
                user_a,
                "idempotent-session",
                "idempotent question",
            )
            state = StructuredTurnState(turn_id="turn_fixed_idempotent")
            state.observe("answer_delta", {"text": "idempotent answer"})
            await recorder.record(
                request=idempotent_request,
                provider="rag_agent",
                state=state,
                terminal_status="completed",
            )
            await recorder.record(
                request=idempotent_request,
                provider="classic",
                state=state,
                terminal_status="completed",
            )
            idempotent = await catalog.list_messages(
                user_a,
                "idempotent-session",
                cursor=None,
                limit=20,
            )
            assert len(idempotent.items) == 2
            scoped_idempotent = idempotent_request.session_id
            assert scoped_idempotent is not None
            assert len(
                await memory.list_recent_messages(scoped_idempotent, 20)
            ) == 2
    finally:
        async with session_factory() as cleanup_session:
            await _cleanup(cleanup_session)
        await engine.dispose()


async def _run_success_stream(
    recorder: StructuredConversationTurnRecorder,
    user: CurrentUserContext,
    *,
    session_id: str,
    provider: str,
    query: str,
    answer: str,
    task_plan_id: str | None = None,
    task_status: str | None = None,
) -> None:
    source = RagSource(
        id="chunk-conversation-source",
        doc_id="doc-conversation-source",
        source="elasticsearch",
        score=0.9,
        scores=RagScoreBreakdown(),
        content_preview="source preview",
    )
    events = [
        RagStreamEvent(event="sources", data={"sources": [source]}),
    ]
    if task_plan_id:
        events.append(
            RagStreamEvent(
                event="agent_task_plan_created",
                data={"task_plan_id": task_plan_id, "status": task_status},
            )
        )
    events.append(RagStreamEvent(event="answer_delta", data={"text": answer}))
    request = _scoped_request(user, session_id, query)
    chunks = [
        chunk
        async for chunk in rag_chat_structured_sse_event_generator(
            request,
            EventPipeline(provider, events),  # type: ignore[arg-type]
            turn_recorder=recorder,
        )
    ]
    assert chunks[-1].startswith("event: done")


async def _run_error_stream(
    recorder: StructuredConversationTurnRecorder,
    user: CurrentUserContext,
    *,
    session_id: str,
) -> None:
    request = _scoped_request(user, session_id, "error question")
    chunks = [
        chunk
        async for chunk in rag_chat_structured_sse_event_generator(
            request,
            EventPipeline("rag_agent", [], fail=True),  # type: ignore[arg-type]
            turn_recorder=recorder,
        )
    ]
    assert chunks[-1].startswith("event: error")


async def _run_aborted_stream(
    recorder: StructuredConversationTurnRecorder,
    user: CurrentUserContext,
    *,
    session_id: str,
) -> None:
    request = _scoped_request(user, session_id, "aborted question")
    generator = rag_chat_structured_sse_event_generator(
        request,
        EventPipeline(
            "rag_agent",
            [RagStreamEvent(event="sources", data={"sources": []})],
        ),  # type: ignore[arg-type]
        turn_recorder=recorder,
    )
    first = await anext(generator)
    assert first.startswith("event: sources")
    await generator.aclose()


def _scoped_request(
    user: CurrentUserContext,
    session_id: str,
    query: str,
) -> RagChatRequest:
    request = scope_rag_chat_request(
        RagChatRequest(query=query, session_id=session_id),
        user,
    )
    request._structured_turn_persistence_managed = True
    return request


async def _seed_users(session) -> None:
    await session.execute(
        text(
            """
            insert into users (id, username, password_hash, status)
            values
                (:user_a, 'conversation_user_a', :password_hash, 'active'),
                (:user_b, 'conversation_user_b', :password_hash, 'active')
            """
        ),
        {
            "user_a": USER_A,
            "user_b": USER_B,
            "password_hash": hash_password("Conversation123!"),
        },
    )
    await session.commit()


async def _cleanup(session) -> None:
    await session.execute(
        text("delete from conversations where user_id = any(:user_ids)"),
        {"user_ids": [USER_A, USER_B]},
    )
    await session.execute(
        text("delete from users where id = any(:user_ids)"),
        {"user_ids": [USER_A, USER_B]},
    )
    await session.commit()


def _user(user_id: str) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=user_id,
        username=user_id,
        is_authenticated=True,
        auth_source="jwt",
    )


def assert_http_contract() -> None:
    item = ConversationItem(
        session_id="conv-http",
        title="HTTP Conversation",
        created_at="2026-08-24T00:00:00Z",
        updated_at="2026-08-24T00:00:00Z",
        message_count=0,
    )
    fake_service = AsyncMock()
    fake_service.list_conversations.return_value = ConversationListResponse(
        items=[item]
    )
    fake_service.create_conversation.return_value = item
    fake_service.rename_conversation.return_value = item
    fake_service.list_messages.return_value = ConversationMessageListResponse(
        items=[]
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _user(USER_A)
    app.dependency_overrides[get_conversation_catalog_service] = (
        lambda: fake_service
    )
    with TestClient(app) as client:
        assert client.get("/conversations").status_code == 200
        assert client.post("/conversations", json={}).status_code == 201
        assert (
            client.patch(
                "/conversations/conv-http",
                json={"title": "Renamed"},
            ).status_code
            == 200
        )
        assert client.get("/conversations/conv-http/messages").status_code == 200
        assert client.delete("/conversations/conv-http").status_code == 204
        assert (
            client.patch(
                "/conversations/conv-http",
                json={"title": "   "},
            ).status_code
            == 422
        )
    schema = app.openapi()
    for path in (
        "/conversations",
        "/conversations/{session_id}",
        "/conversations/{session_id}/messages",
    ):
        assert path in schema["paths"]


if __name__ == "__main__":
    main()
