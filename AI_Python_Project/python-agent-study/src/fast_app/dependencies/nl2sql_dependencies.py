from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings, get_settings
from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.services.exceptions import AppServiceError
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.service import Nl2SqlService


def get_dataset_registry(request: Request) -> DatasetRegistry:
    registry = getattr(request.app.state, "nl2sql_dataset_registry", None)
    if not isinstance(registry, DatasetRegistry):
        raise AppServiceError("NL2SQL DatasetRegistry 尚未初始化")
    return registry


def get_nl2sql_service(
    settings: Settings = Depends(get_settings),
    registry: DatasetRegistry = Depends(get_dataset_registry),
    session: AsyncSession = Depends(get_db_session),
) -> Nl2SqlService:
    return Nl2SqlService(settings=settings, registry=registry, session=session)


__all__ = ["get_dataset_registry", "get_nl2sql_service"]
