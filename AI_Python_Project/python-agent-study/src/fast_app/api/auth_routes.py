from fastapi import APIRouter, Depends

from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.auth_schema import (
    ApiKeySummary,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    CurrentUserResponse,
    LoginRequest,
    RefreshTokenRequest,
    RevokeApiKeyResponse,
    TokenPairResponse,
)
from fast_app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPairResponse)
async def login_endpoint(
    req: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    """用户名/邮箱 + 密码登录，返回 JWT access token 和 refresh token。"""

    token_pair = await auth_service.login(
        username_or_email=req.username_or_email,
        password=req.password,
    )
    return TokenPairResponse.model_validate(token_pair.model_dump())


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh_token_endpoint(
    req: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    """使用 refresh token 轮换并返回新的 token pair。"""

    token_pair = await auth_service.refresh(req.refresh_token)
    return TokenPairResponse.model_validate(token_pair.model_dump())


@router.get("/me", response_model=CurrentUserResponse)
async def me_endpoint(
    user: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserResponse:
    """返回当前请求解析出的统一用户上下文。"""

    return CurrentUserResponse.model_validate(user.model_dump())


@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key_endpoint(
    req: CreateApiKeyRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> CreateApiKeyResponse:
    """为当前用户创建 API Key，原始 key 只在本次响应返回。"""

    created = await auth_service.create_api_key(
        current_user=user,
        name=req.name,
        expires_at=req.expires_at,
    )
    return CreateApiKeyResponse.model_validate(created.model_dump())


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys_endpoint(
    user: CurrentUserContext = Depends(get_current_user_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> list[ApiKeySummary]:
    """列出当前用户的 API Key 摘要，不返回原始 key。"""

    credentials = await auth_service.list_api_keys(user)
    return [
        ApiKeySummary(
            id=item.id,
            name=item.name,
            key_prefix=item.key_prefix,
            key_fingerprint=item.key_fingerprint,
            status=item.status.value,
            expires_at=item.expires_at,
            last_used_at=item.last_used_at,
            created_at=item.created_at,
            revoked_at=item.revoked_at,
        )
        for item in credentials
    ]


@router.delete("/api-keys/{api_key_id}", response_model=RevokeApiKeyResponse)
async def revoke_api_key_endpoint(
    api_key_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> RevokeApiKeyResponse:
    """撤销当前用户自己的 API Key。"""

    revoked = await auth_service.revoke_api_key(
        current_user=user,
        api_key_id=api_key_id,
    )
    return RevokeApiKeyResponse(api_key_id=api_key_id, revoked=revoked)


__all__ = ["router"]
