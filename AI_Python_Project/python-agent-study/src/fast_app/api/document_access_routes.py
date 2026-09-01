from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from fast_app.dependencies.document_access_dependencies import (
    get_document_access_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.error_schema import (
    DocumentAccessGrantValidationErrorResponse,
    RequestValidationErrorResponse,
)
from fast_app.schemas.document_access_schema import (
    CreateDocumentAccessGrantsRequest,
    CreateDocumentAccessGrantsResponse,
    DocumentAccessGrantItem,
    DocumentAccessGrantListResponse,
)
from fast_app.services.knowledge.document_access_service import DocumentAccessService


router = APIRouter(prefix="/admin/document-access", tags=["document-access"])

_DOCUMENT_ACCESS_GRANT_VALIDATION_RESPONSES = {
    422: {
        "model": DocumentAccessGrantValidationErrorResponse,
        "description": "请求字段或文档授权业务校验失败的安全错误投影。",
    }
}

_DOCUMENT_ACCESS_GRANT_REQUEST_VALIDATION_RESPONSES = {
    422: {
        "model": RequestValidationErrorResponse,
        "description": "请求字段校验失败；只返回 allowlisted 字段的安全错误投影。",
    }
}


@router.get(
    "/grants",
    response_model=DocumentAccessGrantListResponse,
    responses=_DOCUMENT_ACCESS_GRANT_VALIDATION_RESPONSES,
)
async def list_document_access_grants_endpoint(
    cursor: str | None = Query(default=None, description="上一页返回的不透明 keyset cursor。"),
    limit: int = Query(default=20, ge=1, le=100, description="本页最多返回的授权数。"),
    target_account: str | None = Query(
        default=None,
        max_length=255,
        description="按目标用户名或邮箱文本筛选。",
    ),
    doc_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        description="按精确文档 doc_id 筛选。",
    ),
    status: Literal["active", "revoked"] | None = Query(
        default=None,
        description="按 active 或 revoked 授权状态筛选。",
    ),
    department_code: str | None = Query(
        default=None,
        max_length=64,
        description="管理员可选文档所属部门；主管范围由服务端固定。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: DocumentAccessService = Depends(get_document_access_service),
) -> DocumentAccessGrantListResponse:
    return await service.list_grants(
        actor,
        cursor=cursor,
        limit=limit,
        target_account=target_account,
        doc_id=doc_id,
        status=status,
        department_code=department_code,
    )


@router.post(
    "/grants",
    response_model=CreateDocumentAccessGrantsResponse,
    responses=_DOCUMENT_ACCESS_GRANT_VALIDATION_RESPONSES,
)
async def create_document_access_grants_endpoint(
    request: CreateDocumentAccessGrantsRequest,
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: DocumentAccessService = Depends(get_document_access_service),
) -> CreateDocumentAccessGrantsResponse:
    return await service.create_grants(actor, request)


@router.delete(
    "/grants/{grant_id}",
    response_model=DocumentAccessGrantItem,
    responses=_DOCUMENT_ACCESS_GRANT_REQUEST_VALIDATION_RESPONSES,
)
async def revoke_document_access_grant_endpoint(
    grant_id: str = Path(
        min_length=1,
        max_length=64,
        description="要幂等撤销的文档授权唯一 ID。",
    ),
    actor: CurrentUserContext = Depends(get_current_user_context),
    service: DocumentAccessService = Depends(get_document_access_service),
) -> DocumentAccessGrantItem:
    return await service.revoke_grant(actor, grant_id)


__all__ = ["router"]
