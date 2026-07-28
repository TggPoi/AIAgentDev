from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from fast_app.integrations.gitlab.models import (
    GitLabCommitAction,
    GitLabCommitResult,
    GitLabCompareResult,
    GitLabMergeRequestResult,
    GitLabProject,
)
from fast_app.services.exceptions import ExternalServiceError


class GitLabClient:
    """最小 GitLab API v4 客户端；只处理协议，不承担 RAG 业务。"""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("GitLab token 不能为空")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )
        # Project Access Token 通过 GitLab API v4 约定的 PRIVATE-TOKEN 请求头发送。
        # 调用方决定传入 rag-sync 还是 rag-agent；Client 本身不混合两类权限。
        self._headers = {"PRIVATE-TOKEN": token}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_project(self, project_id: int | str) -> GitLabProject:
        payload = await self._json(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}",
        )
        return GitLabProject.model_validate(payload)

    async def get_branch_head(self, project_id: int | str, branch: str) -> str:
        payload = await self._json(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}/repository/branches/"
            f"{quote(branch, safe='')}",
        )
        return str(payload["commit"]["id"])

    async def get_branch_head_optional(
        self, project_id: int | str, branch: str
    ) -> str | None:
        response = await self._request(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}/repository/branches/"
            f"{quote(branch, safe='')}",
            allowed_statuses={404},
        )
        if response.status_code == 404:
            return None
        return str(response.json()["commit"]["id"])

    async def get_file(
        self,
        project_id: int | str,
        repository_path: str,
        ref: str,
    ) -> bytes:
        response = await self._request(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}/repository/files/"
            f"{quote(repository_path, safe='')}/raw",
            params={"ref": ref},
        )
        return response.content

    async def get_file_optional(
        self,
        project_id: int | str,
        repository_path: str,
        ref: str,
    ) -> bytes | None:
        """读取可选仓库文件；仅把 GitLab 的 404 解释为文件不存在。"""

        response = await self._request(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}/repository/files/"
            f"{quote(repository_path, safe='')}/raw",
            params={"ref": ref},
            allowed_statuses={404},
        )
        return None if response.status_code == 404 else response.content

    async def download_archive(self, project_id: int | str, sha: str) -> bytes:
        response = await self._request(
            "GET",
            f"/projects/{quote(str(project_id), safe='')}/repository/archive.tar.gz",
            params={"sha": sha},
        )
        return response.content

    async def compare(
        self,
        project_id: int | str,
        from_sha: str,
        to_sha: str,
    ) -> GitLabCompareResult:
        path = f"/projects/{quote(str(project_id), safe='')}/repository/compare"
        page = 1
        payload: dict[str, Any] | None = None
        diffs: list[dict[str, Any]] = []
        # Compare API 可能分页。不能只读取第一页，否则一个 Commit 修改文件较多时，
        # 后端会漏同步后续页面中的新增、修改或删除。
        while True:
            response = await self._request(
                "GET",
                path,
                params={
                    "from": from_sha,
                    "to": to_sha,
                    "straight": "true",
                    "page": page,
                    "per_page": 100,
                },
            )
            current = response.json()
            if not isinstance(current, dict):
                raise ExternalServiceError("GitLab Compare API 未返回 JSON object")
            payload = payload or current
            diffs.extend(current.get("diffs") or [])
            next_page = response.headers.get("X-Next-Page", "").strip()
            if not next_page:
                break
            try:
                page = int(next_page)
            except ValueError as exc:
                raise ExternalServiceError("GitLab X-Next-Page 非法") from exc
        commit = payload.get("commit") or {}
        return GitLabCompareResult(
            commit_sha=str(commit.get("id") or to_sha),
            compare_timeout=bool(payload.get("compare_timeout", False)),
            compare_same_ref=bool(payload.get("compare_same_ref", False)),
            overflow=bool(payload.get("overflow", False)),
            diffs=diffs,
        )

    async def iter_pages(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        page = 1
        while True:
            query = dict(params or {})
            query.update({"page": page, "per_page": 100})
            response = await self._request("GET", path, params=query)
            payload = response.json()
            if not isinstance(payload, list):
                raise ExternalServiceError("GitLab 分页接口未返回列表")
            yield payload
            next_page = response.headers.get("X-Next-Page", "").strip()
            if not next_page:
                return
            try:
                page = int(next_page)
            except ValueError as exc:
                raise ExternalServiceError("GitLab X-Next-Page 非法") from exc

    async def create_branch(
        self,
        project_id: int | str,
        *,
        branch: str,
        ref: str,
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            f"/projects/{quote(str(project_id), safe='')}/repository/branches",
            data={"branch": branch, "ref": ref},
        )

    async def create_commit(
        self,
        project_id: int | str,
        *,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
    ) -> GitLabCommitResult:
        payload = await self._json(
            "POST",
            f"/projects/{quote(str(project_id), safe='')}/repository/commits",
            json={
                "branch": branch,
                "commit_message": commit_message,
                "actions": actions,
            },
        )
        return GitLabCommitResult.model_validate(payload)

    async def create_merge_request(
        self,
        project_id: int | str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> GitLabMergeRequestResult:
        payload = await self._json(
            "POST",
            f"/projects/{quote(str(project_id), safe='')}/merge_requests",
            data={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "remove_source_branch": "true",
            },
        )
        return GitLabMergeRequestResult.model_validate(payload)

    async def find_merge_request(
        self,
        project_id: int | str,
        *,
        source_branch: str,
    ) -> GitLabMergeRequestResult | None:
        path = f"/projects/{quote(str(project_id), safe='')}/merge_requests"
        async for rows in self.iter_pages(
            path,
            params={"source_branch": source_branch, "state": "all"},
        ):
            if rows:
                return GitLabMergeRequestResult.model_validate(rows[0])
        return None

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalServiceError("GitLab API 返回了非 JSON 响应") from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allowed_statuses: set[int] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        url = f"{self.base_url}/api/v4{path}"
        last_error: Exception | None = None
        # 这里只重试网络异常、限流和 GitLab 服务端错误。普通 4xx 通常是 Token、
        # 权限或参数错误，立即暴露给业务层，避免把确定性错误重复执行多次。
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=self._headers,
                    **kwargs,
                )
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 8))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self.max_retries:
                    last_error = RuntimeError(
                        f"GitLab HTTP {response.status_code}"
                    )
                    break
                retry_after = response.headers.get("Retry-After", "").strip()
                try:
                    delay = float(retry_after) if retry_after else min(2**attempt, 8)
                except ValueError:
                    delay = min(2**attempt, 8)
                # GitLab 明确给出 Retry-After 时优先遵守；否则使用有上限的指数退避。
                await asyncio.sleep(max(0.0, min(delay, 30.0)))
                continue

            if response.status_code in (allowed_statuses or set()):
                return response
            if response.is_error:
                message = response.text[:500]
                raise ExternalServiceError(
                    f"GitLab API 请求失败: status={response.status_code}, body={message}"
                )
            return response

        raise ExternalServiceError(f"GitLab API 暂时不可用: {last_error}")


__all__ = ["GitLabClient"]
