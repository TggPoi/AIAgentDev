from __future__ import annotations

import hashlib
import hmac

from fast_app.core.config import get_secret_env_value
from fast_app.db.gitlab_tables import GitLabSourceTable
from fast_app.integrations.gitlab.models import (
    GitLabPushWebhook,
    GitLabWebhookAcceptedResponse,
)
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.services.exceptions import AppServiceError, AuthenticationError


ZERO_SHA = "0" * 40


class GitLabWebhookService:
    def __init__(self, repository: GitLabRepository) -> None:
        self.repository = repository

    async def accept(
        self,
        *,
        source: GitLabSourceTable,
        raw_body: bytes,
        token: str,
        event_uuid: str | None,
        event_type: str,
    ) -> GitLabWebhookAcceptedResponse:
        # 先验证共享 Secret，再解析和信任请求体中的 Project、分支和 Commit SHA。
        self._verify_secret(source, token)
        try:
            payload = GitLabPushWebhook.model_validate_json(raw_body)
        except Exception as exc:
            raise AppServiceError("GitLab Webhook payload 非法") from exc

        if (
            payload.object_kind != "push"
            or payload.project.id != source.project_id
            or payload.ref != f"refs/heads/{source.target_branch}"
            or payload.after == ZERO_SHA
        ):
            # 非 push、错误 Project、非正式分支和删除分支事件都不进入同步队列。
            return GitLabWebhookAcceptedResponse(
                accepted=False,
                duplicate=False,
                job_id=None,
                target_sha=None,
            )

        payload_hash = hashlib.sha256(raw_body).hexdigest()
        # 新版 GitLab 优先使用事件 UUID；缺少 UUID 时用不可变的事件事实生成稳定键，
        # 使 GitLab 重投或网络重试不会重复创建同步任务。
        delivery_key = event_uuid or hashlib.sha256(
            (
                f"{source.project_id}:{payload.before}:{payload.after}:"
                f"{payload_hash}"
            ).encode("utf-8")
        ).hexdigest()
        # Webhook 请求只登记 Delivery、推进 desired_sha 并合并/创建队列任务。
        # 下载、解析、Embedding 和双库写入全部留给独立 Worker，所以接口能快速返回 202。
        result = await self.repository.register_delivery_and_enqueue(
            source=source,
            delivery_key=delivery_key,
            event_uuid=event_uuid,
            event_type=event_type or "Push Hook",
            before_sha=payload.before,
            after_sha=payload.after,
            payload_hash=payload_hash,
        )
        return GitLabWebhookAcceptedResponse(
            accepted=True,
            duplicate=result.duplicate,
            job_id=result.job.id if result.job else None,
            target_sha=payload.after,
        )

    @staticmethod
    def _verify_secret(source: GitLabSourceTable, received: str) -> None:
        expected = get_secret_env_value(source.webhook_secret_env)
        if not expected or not received or not hmac.compare_digest(expected, received):
            raise AuthenticationError("GitLab Webhook secret 无效")


__all__ = ["GitLabWebhookService"]
