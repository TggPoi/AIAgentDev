from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings, get_secret_env_value, get_settings
from fast_app.dependencies.rag_dependencies import get_db_session
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.models import (
    GitLabSourceResponse,
    GitLabSyncJobResponse,
    GitLabSyncRequest,
    GitLabWebhookAcceptedResponse,
    KnowledgeChangeDocument,
    KnowledgeChangeEventListResponse,
    KnowledgeChangeEventResponse,
    KnowledgePublicationStatusResponse,
)
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.integrations.gitlab.webhook_service import GitLabWebhookService
from fast_app.services.exceptions import (
    AppServiceError,
    AuthenticationError,
    ToolPermissionDeniedError,
)


router = APIRouter(tags=["gitlab"])


def get_gitlab_repository(
    session: AsyncSession = Depends(get_db_session),
) -> GitLabRepository:
    return GitLabRepository(session)


@router.post(
    "/integrations/gitlab/webhooks/{source_id}",
    response_model=GitLabWebhookAcceptedResponse,
    status_code=202,
)
async def accept_gitlab_webhook(
    source_id: str,
    request: Request,
    x_gitlab_token: str = Header(default="", alias="X-Gitlab-Token"),
    x_gitlab_event_uuid: str | None = Header(
        default=None, alias="X-Gitlab-Event-UUID"
    ),
    x_gitlab_event: str = Header(default="", alias="X-Gitlab-Event"),
    repository: GitLabRepository = Depends(get_gitlab_repository),
    settings: Settings = Depends(get_settings),
) -> GitLabWebhookAcceptedResponse:
    if not settings.gitlab_integration_enabled:
        raise AppServiceError("GitLab integration 未启用")
    source = await repository.get_source(source_id)
    if source is None or source.status != "active":
        raise AppServiceError("GitLab Source 不存在或未启用")
    raw_body = await request.body()
    return await GitLabWebhookService(repository).accept(
        source=source,
        raw_body=raw_body,
        token=x_gitlab_token,
        event_uuid=x_gitlab_event_uuid,
        event_type=x_gitlab_event,
    )


@router.get(
    "/admin/gitlab/sources",
    response_model=list[GitLabSourceResponse],
)
async def list_gitlab_sources(
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
) -> list[GitLabSourceResponse]:
    _require_admin(user)
    return [_source_response(row) for row in await repository.list_sources()]


@router.get(
    "/admin/gitlab/sync-jobs",
    response_model=list[GitLabSyncJobResponse],
)
async def list_gitlab_sync_jobs(
    status: Literal[
        "pending", "running", "publishing", "retry_wait", "succeeded", "failed"
    ]
    | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
) -> list[GitLabSyncJobResponse]:
    _require_admin(user)
    return [
        _job_response(row)
        for row in await repository.list_jobs(status=status, limit=limit)
    ]


@router.post(
    "/admin/gitlab/sources/{source_id}/sync",
    response_model=GitLabSyncJobResponse,
    status_code=202,
)
async def trigger_gitlab_sync(
    source_id: str,
    body: GitLabSyncRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
    settings: Settings = Depends(get_settings),
) -> GitLabSyncJobResponse:
    _require_admin(user)
    source = await repository.get_source(source_id)
    if source is None:
        raise AppServiceError("GitLab Source 不存在")
    target_sha = body.target_sha
    if target_sha is None:
        token = get_secret_env_value(source.sync_token_env)
        client = GitLabClient(
            base_url=source.base_url,
            token=token,
            timeout_seconds=settings.gitlab_request_timeout_seconds,
            max_retries=settings.gitlab_max_retries,
        )
        try:
            target_sha = await client.get_branch_head(
                source.project_id, source.target_branch
            )
        finally:
            await client.close()
    job = await repository.enqueue(
        source_id=source.id,
        mode=body.mode,
        target_sha=target_sha,
        base_sha=source.last_synced_sha,
    )
    return _job_response(job)


@router.post(
    "/admin/gitlab/sync-jobs/{job_id}/retry",
    response_model=GitLabSyncJobResponse,
    status_code=202,
)
async def retry_gitlab_sync_job(
    job_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
) -> GitLabSyncJobResponse:
    _require_admin(user)
    previous = await repository.get_job(job_id)
    if previous is None:
        raise AppServiceError("GitLab 同步任务不存在")
    try:
        job = await repository.retry_job(previous.id)
    except (LookupError, ValueError) as exc:
        raise AppServiceError(str(exc)) from exc
    return _job_response(job)


@router.get(
    "/knowledge/publication/status",
    response_model=KnowledgePublicationStatusResponse,
)
async def get_knowledge_publication_status(
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
) -> KnowledgePublicationStatusResponse:
    _require_authenticated(user)
    active, syncing, latest = await repository.get_publication_status()
    return KnowledgePublicationStatusResponse(
        active_version=active,
        syncing=syncing,
        latest_candidate_version=latest,
    )


@router.get(
    "/knowledge/change-events",
    response_model=KnowledgeChangeEventListResponse,
)
async def list_knowledge_change_events(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUserContext = Depends(get_current_user_context),
    repository: GitLabRepository = Depends(get_gitlab_repository),
) -> KnowledgeChangeEventListResponse:
    _require_authenticated(user)
    rows = await repository.list_change_events(after_id=after_id, limit=limit)
    items: list[KnowledgeChangeEventResponse] = []
    for row in rows:
        visible = [
            KnowledgeChangeDocument.model_validate(item)
            for item in row.affected_documents_json
            if _can_read_change(user, item)
        ]
        if visible:
            items.append(
                KnowledgeChangeEventResponse(
                    id=row.id,
                    publication_version=row.publication_version,
                    event_type=row.event_type,
                    changes=visible,
                    published_at=row.created_at,
                )
            )
    next_after_id = rows[-1].id if rows else after_id
    return KnowledgeChangeEventListResponse(
        items=items,
        next_after_id=next_after_id,
    )


def _require_authenticated(user: CurrentUserContext) -> None:
    if not user.is_authenticated:
        raise AuthenticationError("该接口需要已认证用户")


def _require_admin(user: CurrentUserContext) -> None:
    _require_authenticated(user)
    if not (
        user.has_global_role(RoleCode.SYSTEM_ADMIN.value)
        or user.has_global_permission(PermissionCode.GITLAB_SOURCE_MANAGE.value)
    ):
        raise ToolPermissionDeniedError("该 GitLab 管理接口仅允许管理员访问")


def _can_read_change(user: CurrentUserContext, item: dict) -> bool:
    if (
        user.has_global_role(RoleCode.SYSTEM_ADMIN.value)
        or user.has_global_permission(PermissionCode.GITLAB_CHANGE_READ_ALL.value)
    ):
        return True
    if item.get("visibility") == "public":
        return True
    if user.user_id in set(item.get("allowed_users") or []):
        return True
    return bool(set(user.department_codes) & set(item.get("allowed_departments") or []))


def _source_response(row) -> GitLabSourceResponse:
    return GitLabSourceResponse(
        id=row.id,
        base_url=row.base_url,
        project_id=row.project_id,
        project_path=row.project_path,
        target_branch=row.target_branch,
        department_code=row.department_code,
        default_visibility=row.default_visibility,
        last_synced_sha=row.last_synced_sha,
        desired_sha=row.desired_sha,
        status=row.status,
    )


def _job_response(row) -> GitLabSyncJobResponse:
    return GitLabSyncJobResponse(
        id=row.id,
        source_id=row.source_id,
        mode=row.mode,
        status=row.status,
        phase=row.phase,
        base_sha=row.base_sha,
        target_sha=row.target_sha,
        candidate_version=row.candidate_version,
        attempt_count=row.attempt_count,
        document_count=row.document_count,
        parent_count=row.parent_count,
        child_count=row.child_count,
        change_counts=row.change_counts_json or {},
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["router"]
