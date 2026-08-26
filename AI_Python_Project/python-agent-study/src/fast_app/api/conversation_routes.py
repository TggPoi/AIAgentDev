from fastapi import APIRouter, Depends, Path, Query, Response, status

from fast_app.dependencies.conversation_dependencies import (
    get_conversation_catalog_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.conversation_schema import (
    ConversationItem,
    ConversationListResponse,
    ConversationMessageListResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)
from fast_app.schemas.error_schema import RequestValidationErrorResponse
from fast_app.services.conversation.conversation_catalog_service import (
    ConversationCatalogService,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])

_CONVERSATION_VALIDATION_ERROR_RESPONSES = {
    422: {
        "model": RequestValidationErrorResponse,
        "description": "请求字段校验失败；只返回 allowlisted 字段的安全错误投影。",
    }
}


@router.get("", response_model=ConversationListResponse)
async def list_conversations_endpoint(
    cursor: str | None = Query(default=None, description="上一页返回的不透明 cursor。"),
    limit: int = Query(default=20, ge=1, le=100, description="本页最多返回的会话数。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: ConversationCatalogService = Depends(
        get_conversation_catalog_service
    ),
) -> ConversationListResponse:
    return await service.list_conversations(user, cursor=cursor, limit=limit)


@router.post(
    "",
    response_model=ConversationItem,
    status_code=status.HTTP_201_CREATED,
    responses=_CONVERSATION_VALIDATION_ERROR_RESPONSES,
)
async def create_conversation_endpoint(
    request: CreateConversationRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    service: ConversationCatalogService = Depends(
        get_conversation_catalog_service
    ),
) -> ConversationItem:
    return await service.create_conversation(user, request)


@router.patch(
    "/{session_id}",
    response_model=ConversationItem,
    responses=_CONVERSATION_VALIDATION_ERROR_RESPONSES,
)
async def rename_conversation_endpoint(
    request: UpdateConversationRequest,
    session_id: str = Path(
        min_length=1,
        max_length=128,
        description="当前用户命名空间内的外部 session ID。",
    ),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: ConversationCatalogService = Depends(
        get_conversation_catalog_service
    ),
) -> ConversationItem:
    return await service.rename_conversation(user, session_id, request)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_endpoint(
    session_id: str = Path(
        min_length=1,
        max_length=128,
        description="当前用户命名空间内的外部 session ID。",
    ),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: ConversationCatalogService = Depends(
        get_conversation_catalog_service
    ),
) -> Response:
    await service.delete_conversation(user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{session_id}/messages",
    response_model=ConversationMessageListResponse,
)
async def list_conversation_messages_endpoint(
    session_id: str = Path(
        min_length=1,
        max_length=128,
        description="当前用户命名空间内的外部 session ID。",
    ),
    cursor: str | None = Query(default=None, description="上一页返回的消息 cursor。"),
    limit: int = Query(default=50, ge=1, le=100, description="本页最多返回的消息数。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: ConversationCatalogService = Depends(
        get_conversation_catalog_service
    ),
) -> ConversationMessageListResponse:
    return await service.list_messages(
        user,
        session_id,
        cursor=cursor,
        limit=limit,
    )


__all__ = ["router"]
