from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    utc_now,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.conversation.conversation_memory import ConversationMemoryStore
from fast_app.services.conversation.conversation_repository import (
    PostgresConversationRepository,
)
from fast_app.services.conversation.conversation_scope import (
    get_request_external_session_id,
    get_request_user_id,
)


TurnTerminalStatus = Literal["completed", "error", "aborted"]


@dataclass
class StructuredTurnState:
    turn_id: str = field(default_factory=lambda: f"turn_{uuid4().hex}")
    answer_parts: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    agent_task_plan_id: str | None = None
    agent_task_status: str | None = None
    error_message: str | None = None

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts)

    def observe(self, event: str, data: dict[str, Any]) -> None:
        if event == "answer_delta":
            text = data.get("text")
            if isinstance(text, str):
                self.answer_parts.append(text)
        elif event == "sources":
            raw_sources = data.get("sources")
            if isinstance(raw_sources, list):
                self.sources = [
                    normalized
                    for item in raw_sources
                    if (normalized := _json_dict(item)) is not None
                ]
        elif event == "nl2sql_result":
            summary = data.get("summary")
            if isinstance(summary, str) and summary.strip() and not self.answer:
                self.answer_parts.append(summary)
        elif event == "error":
            self.error_message = _public_error_message(data)

        task_plan_id = data.get("task_plan_id")
        if isinstance(task_plan_id, str) and task_plan_id:
            self.agent_task_plan_id = task_plan_id
        if event.startswith("agent_task"):
            status = data.get("status")
            if isinstance(status, str) and status:
                self.agent_task_status = status


class StructuredConversationTurnRecorder:
    """在 structured stream 边界为所有 provider 保存一致、幂等的一轮消息。"""

    def __init__(
        self,
        *,
        repository: PostgresConversationRepository,
        memory_store: ConversationMemoryStore,
    ) -> None:
        self._repository = repository
        self._memory_store = memory_store

    async def record(
        self,
        *,
        request: RagChatRequest,
        provider: str,
        state: StructuredTurnState,
        terminal_status: TurnTerminalStatus,
    ) -> None:
        conversation_id = request.session_id
        user_id = get_request_user_id(request)
        external_session_id = get_request_external_session_id(request)
        if not conversation_id or not user_id or not external_session_id:
            return
        now = utc_now()
        metadata: dict[str, object] = {
            "turn_id": state.turn_id,
            "pipeline_provider": provider,
            "operation": "stream_events",
            "user_id": user_id,
            "external_session_id": external_session_id,
            "scoped_session_id": conversation_id,
            "terminal_status": terminal_status,
            "sources": state.sources,
            "source_count": len(state.sources),
            "agent_task_plan_id": state.agent_task_plan_id,
            "agent_task_status": state.agent_task_status,
        }
        messages = [
            ConversationMessage(
                id=f"{state.turn_id}:user",
                conversation_id=conversation_id,
                role=ConversationRole.USER,
                content=request.query,
                created_at=now,
                metadata={**metadata, "sources": [], "source_count": 0},
            )
        ]
        assistant_content = state.answer.strip()
        if terminal_status == "error" and not assistant_content:
            assistant_content = state.error_message or "请求处理失败"
        if assistant_content:
            messages.append(
                ConversationMessage(
                    id=f"{state.turn_id}:assistant",
                    conversation_id=conversation_id,
                    role=ConversationRole.ASSISTANT,
                    content=assistant_content,
                    created_at=utc_now(),
                    metadata=metadata,
                )
            )
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            external_session_id=external_session_id,
            title=_default_title(request.query),
            updated_at=utc_now(),
            metadata={
                "external_session_id": external_session_id,
                "last_terminal_status": terminal_status,
                "last_pipeline_provider": provider,
                "last_turn_id": state.turn_id,
            },
        )
        await self._repository.save_conversation_turn(
            conversation,
            messages,
        )
        for message in messages:
            await self._memory_store.append_message(message)


def _default_title(query: str) -> str:
    normalized = " ".join(query.split())
    return normalized[:60] or "新会话"


def _json_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return None


def _json_value(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _public_error_message(data: dict[str, Any]) -> str:
    for key in ("message", "public_message", "detail"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = data.get("error")
    if isinstance(error, dict):
        return _public_error_message(error)
    return "请求处理失败"


__all__ = [
    "StructuredConversationTurnRecorder",
    "StructuredTurnState",
    "TurnTerminalStatus",
]
