from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from fast_app.domain.conversation_models import Conversation, utc_now
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.conversation_schema import (
    ConversationItem,
    ConversationListResponse,
    ConversationMessageItem,
    ConversationMessageListResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)
from fast_app.schemas.rag_chat_schema import RagSource
from fast_app.services.conversation.conversation_memory import ConversationMemoryStore
from fast_app.services.conversation.conversation_repository import (
    ConversationListRecord,
    ConversationMessageRecord,
    PostgresConversationRepository,
)
from fast_app.services.conversation.conversation_scope import (
    build_scoped_conversation_id,
)
from fast_app.services.exceptions import (
    AuthenticationError,
    ConversationConflictError,
    ConversationCursorInvalidError,
    ConversationNotFoundError,
)


class ConversationCatalogService:
    """提供当前用户会话目录、标题、删除和公开消息历史。"""

    def __init__(
        self,
        *,
        repository: PostgresConversationRepository,
        memory_store: ConversationMemoryStore,
    ) -> None:
        self._repository = repository
        self._memory_store = memory_store

    async def list_conversations(
        self,
        user: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
    ) -> ConversationListResponse:
        self._require_authenticated(user)
        updated_at, conversation_id = _decode_conversation_cursor(cursor)
        rows, has_more = await self._repository.list_conversations_for_user(
            user_id=user.user_id,
            limit=limit,
            cursor_updated_at=updated_at,
            cursor_id=conversation_id,
        )
        return ConversationListResponse(
            items=[_to_item(row) for row in rows],
            next_cursor=(
                _encode_conversation_cursor(
                    rows[-1].conversation.updated_at,
                    rows[-1].conversation.id,
                )
                if has_more and rows
                else None
            ),
        )

    async def create_conversation(
        self,
        user: CurrentUserContext,
        request: CreateConversationRequest,
    ) -> ConversationItem:
        self._require_authenticated(user)
        for _ in range(3):
            external_session_id = f"conv_{uuid4().hex}"
            conversation = Conversation(
                id=build_scoped_conversation_id(
                    user.user_id,
                    external_session_id,
                ),
                user_id=user.user_id,
                external_session_id=external_session_id,
                title=request.title or "新会话",
                metadata={"external_session_id": external_session_id},
            )
            try:
                await self._repository.create_conversation(conversation)
            except IntegrityError:
                continue
            return ConversationItem(
                session_id=external_session_id,
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                message_count=0,
            )
        raise ConversationConflictError("无法生成唯一会话 ID，请重试")

    async def rename_conversation(
        self,
        user: CurrentUserContext,
        session_id: str,
        request: UpdateConversationRequest,
    ) -> ConversationItem:
        self._require_authenticated(user)
        conversation = await self._repository.update_title(
            user_id=user.user_id,
            external_session_id=session_id,
            title=request.title,
        )
        if conversation is None:
            raise ConversationNotFoundError("会话不存在")
        return ConversationItem(
            session_id=session_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=await self._message_count(user, conversation.id),
        )

    async def delete_conversation(
        self,
        user: CurrentUserContext,
        session_id: str,
    ) -> None:
        self._require_authenticated(user)
        scoped_id = build_scoped_conversation_id(user.user_id, session_id)
        deleted_id = await self._repository.delete_conversation_for_user(
            user_id=user.user_id,
            external_session_id=session_id,
        )
        await self._memory_store.delete_conversation(deleted_id or scoped_id)

    async def list_messages(
        self,
        user: CurrentUserContext,
        session_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> ConversationMessageListResponse:
        self._require_authenticated(user)
        conversation = (
            await self._repository.get_conversation_by_external_session(
                user_id=user.user_id,
                external_session_id=session_id,
            )
        )
        if conversation is None:
            raise ConversationNotFoundError("会话不存在")
        after_sequence = _decode_message_cursor(cursor)
        rows, has_more = await self._repository.list_message_records_for_user(
            conversation_id=conversation.id,
            user_id=user.user_id,
            limit=limit,
            after_sequence_no=after_sequence,
        )
        return ConversationMessageListResponse(
            items=[_to_message_item(row) for row in rows],
            next_cursor=(
                _encode_message_cursor(rows[-1].sequence_no)
                if has_more and rows
                else None
            ),
        )

    async def _message_count(
        self,
        user: CurrentUserContext,
        conversation_id: str,
    ) -> int:
        return await self._repository.count_messages_for_user(
            conversation_id=conversation_id,
            user_id=user.user_id,
        )

    @staticmethod
    def _require_authenticated(user: CurrentUserContext) -> None:
        if not user.is_authenticated:
            raise AuthenticationError("会话管理只允许已认证用户")


def _to_item(row: ConversationListRecord) -> ConversationItem:
    preview = (
        " ".join(row.last_message_content.split())[:120]
        if row.last_message_content
        else None
    )
    role = row.last_message_role if row.last_message_role in {"user", "assistant"} else None
    return ConversationItem(
        session_id=row.conversation.external_session_id or row.conversation.id,
        title=row.conversation.title,
        created_at=row.conversation.created_at,
        updated_at=row.conversation.updated_at,
        message_count=row.message_count,
        last_message_role=role,
        last_message_preview=preview,
    )


def _to_message_item(row: ConversationMessageRecord) -> ConversationMessageItem:
    metadata = row.message.metadata
    sources: list[RagSource] = []
    for source in metadata.get("sources") or []:
        try:
            sources.append(RagSource.model_validate(source))
        except (TypeError, ValidationError):
            continue
    terminal_status = str(metadata.get("terminal_status") or "completed")
    if terminal_status not in {"completed", "error", "aborted"}:
        terminal_status = "completed"
    return ConversationMessageItem(
        message_id=row.message.id,
        sequence_no=row.sequence_no,
        role=row.message.role.value,
        content=row.message.content,
        sources=sources,
        agent_task_plan_id=_optional_string(metadata.get("agent_task_plan_id")),
        agent_task_status=_optional_string(metadata.get("agent_task_status")),
        terminal_status=terminal_status,
        created_at=row.message.created_at,
    )


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None


def _encode_conversation_cursor(updated_at: datetime, conversation_id: str) -> str:
    return _encode_payload(
        {"updated_at": updated_at.isoformat(), "conversation_id": conversation_id}
    )


def _decode_conversation_cursor(
    cursor: str | None,
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        payload = _decode_payload(cursor)
        updated_at = datetime.fromisoformat(payload["updated_at"])
        conversation_id = payload["conversation_id"]
        if (
            updated_at.tzinfo is None
            or not isinstance(conversation_id, str)
            or not conversation_id
        ):
            raise ValueError
        return updated_at, conversation_id
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversationCursorInvalidError("会话列表 cursor 无效") from exc


def _encode_message_cursor(sequence_no: int) -> str:
    return _encode_payload({"sequence_no": sequence_no})


def _decode_message_cursor(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        value = _decode_payload(cursor)["sequence_no"]
        if not isinstance(value, int) or value < 1:
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversationCursorInvalidError("消息列表 cursor 无效") from exc


def _encode_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(cursor: str) -> dict[str, object]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ConversationCursorInvalidError("cursor 无效") from exc


__all__ = ["ConversationCatalogService"]
