from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.db.conversation_tables import ConversationTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    utc_now,
)
from fast_app.services.conversation.conversation_repository import PostgresConversationRepository


async def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    conversation_id = f"verify-message-order-{uuid4().hex[:8]}"
    created_at = utc_now()
    messages = [
        ConversationMessage(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=created_at,
        )
        for message_id, role, content in (
            ("z-user", ConversationRole.USER, "第一轮用户"),
            ("a-assistant", ConversationRole.ASSISTANT, "第一轮助手"),
            ("y-user", ConversationRole.USER, "第二轮用户"),
            ("b-assistant", ConversationRole.ASSISTANT, "第二轮助手"),
        )
    ]

    try:
        async with session_factory() as session:
            repository = PostgresConversationRepository(session)
            await repository.save_conversation_turn(
                Conversation(id=conversation_id, updated_at=created_at),
                messages,
            )
            stored = await repository.list_messages(conversation_id, limit=10)
            assert [item.id for item in stored] == [item.id for item in messages]
            await session.execute(
                delete(ConversationTable).where(ConversationTable.id == conversation_id)
            )
            await session.commit()
    finally:
        await engine.dispose()

    print("conversation_message_order=passed")


if __name__ == "__main__":
    asyncio.run(main())
