from __future__ import annotations

from fast_app.core.config import Settings, get_secret_env_value
from fast_app.db.gitlab_tables import GitLabDocumentTable, GitLabSourceTable
from fast_app.integrations.gitlab.client import GitLabClient


class GitLabDocumentContentGateway:
    """使用只读 sync token 按 manifest 冻结的 path/revision 获取源文件。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(
        self,
        *,
        source: GitLabSourceTable,
        document: GitLabDocumentTable,
    ) -> bytes | None:
        client = GitLabClient(
            base_url=source.base_url,
            token=get_secret_env_value(source.sync_token_env),
            timeout_seconds=self._settings.gitlab_request_timeout_seconds,
            max_retries=self._settings.gitlab_max_retries,
        )
        try:
            return await client.get_file_optional(
                source.project_id,
                document.repository_path,
                document.source_revision,
            )
        finally:
            await client.close()


__all__ = ["GitLabDocumentContentGateway"]
