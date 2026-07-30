from fastapi import APIRouter, Depends

from fast_app.dependencies.nl2sql_dependencies import get_nl2sql_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.nl2sql.models import (
    Nl2SqlDatasetItem,
    Nl2SqlQueryRequest,
    Nl2SqlQueryResult,
)
from fast_app.services.nl2sql.service import Nl2SqlService


router = APIRouter(prefix="/nl2sql", tags=["nl2sql"])


@router.get("/datasets", response_model=list[Nl2SqlDatasetItem])
async def list_nl2sql_datasets(
    user: CurrentUserContext = Depends(get_current_user_context),
    service: Nl2SqlService = Depends(get_nl2sql_service),
) -> list[Nl2SqlDatasetItem]:
    return await service.list_datasets(user)


@router.post("/query", response_model=Nl2SqlQueryResult)
async def query_nl2sql_dataset(
    req: Nl2SqlQueryRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    service: Nl2SqlService = Depends(get_nl2sql_service),
) -> Nl2SqlQueryResult:
    return await service.query(
        user=user,
        dataset_id=req.dataset_id,
        question=req.question,
        max_rows=req.max_rows,
    )


__all__ = ["router"]
