from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings, get_settings
from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.integrations.gitlab.document_content_gateway import (
    GitLabDocumentContentGateway,
)
from fast_app.services.knowledge.document_access_policy import DocumentAccessPolicy
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessRepository,
)
from fast_app.services.knowledge.knowledge_document_read_repository import (
    KnowledgeDocumentReadRepository,
)
from fast_app.services.knowledge.knowledge_document_read_service import (
    KnowledgeDocumentReadService,
)


def get_knowledge_document_read_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDocumentReadService:
    return KnowledgeDocumentReadService(
        settings=settings,
        repository=KnowledgeDocumentReadRepository(session),
        access_policy=DocumentAccessPolicy(DocumentAccessRepository(session)),
        content_gateway=GitLabDocumentContentGateway(settings),
    )


__all__ = ["get_knowledge_document_read_service"]
