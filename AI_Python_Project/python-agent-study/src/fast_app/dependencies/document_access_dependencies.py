from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessRepository,
)
from fast_app.services.knowledge.document_access_policy import DocumentAccessPolicy
from fast_app.services.knowledge.document_access_service import DocumentAccessService


def get_document_access_repository(
    session: AsyncSession = Depends(get_db_session),
) -> DocumentAccessRepository:
    return DocumentAccessRepository(session)


def get_document_access_service(
    repository: DocumentAccessRepository = Depends(get_document_access_repository),
) -> DocumentAccessService:
    return DocumentAccessService(repository)


def get_document_access_policy(
    repository: DocumentAccessRepository = Depends(get_document_access_repository),
) -> DocumentAccessPolicy:
    return DocumentAccessPolicy(repository)


__all__ = [
    "get_document_access_repository",
    "get_document_access_policy",
    "get_document_access_service",
]
