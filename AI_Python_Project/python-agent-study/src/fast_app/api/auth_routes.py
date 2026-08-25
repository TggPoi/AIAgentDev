from fastapi import APIRouter, Depends

from fast_app.dependencies.rag_dependencies import get_auth_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.auth_schema import (
    ApiKeySummary,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    CurrentUserResponse,
    LoginRequest,
    LogoutRequest,
    LogoutResponse,
    RefreshTokenRequest,
    RevokeApiKeyResponse,
    TokenPairResponse,
    UserCapabilitiesResponse,
)
from fast_app.schemas.error_schema import RequestValidationErrorResponse
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.capability_service import resolve_auth_capabilities
from fast_app.services.exceptions import AuthenticationError


router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_VALIDATION_ERROR_RESPONSES = {
    422: {
        "model": RequestValidationErrorResponse,
        "description": "请求字段校验失败；只返回 allowlisted 字段的安全错误投影。",
    }
}


@router.post(
    "/login",
    response_model=TokenPairResponse,
    responses=_AUTH_VALIDATION_ERROR_RESPONSES,
)
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


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    responses=_AUTH_VALIDATION_ERROR_RESPONSES,
)
async def refresh_token_endpoint(
    req: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenPairResponse:
    """使用 refresh token 轮换并返回新的 token pair。"""

    token_pair = await auth_service.refresh(req.refresh_token)
    return TokenPairResponse.model_validate(token_pair.model_dump())


@router.post("/logout", response_model=LogoutResponse)
async def logout_endpoint(
    req: LogoutRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    """撤销当前用户提交的 refresh token；重复注销同一 token 幂等成功。"""

    _require_authenticated_user(user)
    logged_out = await auth_service.logout(
        current_user=user,
        refresh_token=req.refresh_token,
    )
    return LogoutResponse(logged_out=logged_out)


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    responses=_AUTH_VALIDATION_ERROR_RESPONSES,
)
async def change_password_endpoint(
    req: ChangePasswordRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    auth_service: AuthService = Depends(get_auth_service),
) -> ChangePasswordResponse:
    """修改当前用户密码，并原子撤销该用户全部 active refresh token。"""

    _require_authenticated_user(user)
    revoked_count = await auth_service.change_password(
        current_user=user,
        current_password=req.current_password,
        new_password=req.new_password,
    )
    return ChangePasswordResponse(
        password_changed=True,
        revoked_refresh_token_count=revoked_count,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def me_endpoint(
    user: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserResponse:
    """返回当前请求解析出的统一用户上下文。"""

    _require_authenticated_user(user)
    return CurrentUserResponse.model_validate(user.model_dump())


@router.get("/capabilities", response_model=UserCapabilitiesResponse)
async def capabilities_endpoint(
    user: CurrentUserContext = Depends(get_current_user_context),
) -> UserCapabilitiesResponse:
    """返回 React 展示控制所需的非敏感能力；业务接口仍独立鉴权。"""

    _require_authenticated_user(user)
    snapshot = resolve_auth_capabilities(user)
    return UserCapabilitiesResponse(
        can_manage_users=snapshot.can_manage_users,
        user_management_scope=snapshot.user_management_scope,
        can_manage_document_grants=snapshot.can_manage_document_grants,
        can_use_web_search=snapshot.can_use_web_search,
        can_use_nl2sql=snapshot.can_use_nl2sql,
        can_read_documents=snapshot.can_read_documents,
        can_manage_documents=snapshot.can_manage_documents,
    )


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


def _require_authenticated_user(user: CurrentUserContext) -> None:
    if not user.is_authenticated:
        raise AuthenticationError("该身份接口只允许已认证用户访问")


__all__ = ["router"]
