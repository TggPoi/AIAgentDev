from fastapi import Depends

from fast_app.dependencies.rag_dependencies import (
    get_conversation_memory_store,
    get_conversation_repository,
)
from fast_app.services.conversation.conversation_catalog_service import (
    ConversationCatalogService,
)
from fast_app.services.conversation.conversation_memory import ConversationMemoryStore
from fast_app.services.conversation.conversation_repository import (
    PostgresConversationRepository,
)
from fast_app.services.conversation.structured_turn_recorder import (
    StructuredConversationTurnRecorder,
)


def get_conversation_catalog_service(
    repository: PostgresConversationRepository = Depends(
        get_conversation_repository
    ),
    memory_store: ConversationMemoryStore = Depends(
        get_conversation_memory_store
    ),
) -> ConversationCatalogService:
    return ConversationCatalogService(
        repository=repository,
        memory_store=memory_store,
    )


def get_structured_conversation_turn_recorder(
    repository: PostgresConversationRepository = Depends(
        get_conversation_repository
    ),
    memory_store: ConversationMemoryStore = Depends(
        get_conversation_memory_store
    ),
) -> StructuredConversationTurnRecorder:
    return StructuredConversationTurnRecorder(
        repository=repository,
        memory_store=memory_store,
    )


__all__ = [
    "get_conversation_catalog_service",
    "get_structured_conversation_turn_recorder",
]
