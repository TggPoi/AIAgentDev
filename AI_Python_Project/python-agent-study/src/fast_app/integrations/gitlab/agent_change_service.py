from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from fast_app.core.config import Settings, get_secret_env_value
from fast_app.db.gitlab_tables import (
    GitLabChangeRequestTable,
    GitLabDocumentTable,
    GitLabSourceTable,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.project_source import GitLabProjectSource
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.services.exceptions import AppServiceError


@dataclass(frozen=True)
class SubmittedGitLabChange:
    source_id: str
    branch_name: str
    commit_sha: str
    merge_request_iid: int
    merge_request_url: str
    status: str


@dataclass(frozen=True)
class GitLabDocumentSnapshot:
    source: GitLabSourceTable
    repository_path: str
    doc_id: str
    source_revision: str
    acl: dict[str, object]
    content: str | None


@dataclass(frozen=True)
class _ResolvedAction:
    request: KnowledgeDocumentActionRequest
    preview: KnowledgeDocumentActionPreview
    expected_before_hash: str | None
    source: GitLabSourceTable
    document: GitLabDocumentTable | None
    repository_path: str


class GitLabAgentChangeService:
    """把已确认的 Agent 文档动作提交为 GitLab 分支、Commit 和 MR。"""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: GitLabRepository,
    ) -> None:
        self.settings = settings
        self.repository = repository

    async def read_document(
        self,
        *,
        target_path: str,
        doc_id: str | None = None,
        department_code: str | None = None,
    ) -> str:
        snapshot = await self.load_snapshot(
            target_path=target_path,
            doc_id=doc_id,
            department_code=department_code,
        )
        if snapshot.content is None:
            raise AppServiceError("目标文档不存在")
        return snapshot.content

    async def load_snapshot(
        self,
        *,
        target_path: str,
        doc_id: str | None = None,
        department_code: str | None = None,
        allow_missing: bool = False,
    ) -> GitLabDocumentSnapshot:
        source, repository_path, document = await self._resolve_location(
            target_path=target_path,
            doc_id=doc_id,
            department_code=department_code,
            allow_missing=allow_missing,
        )
        client = self._client(source)
        try:
            # Agent 读取的是正式分支当前 HEAD，并把这个 SHA 冻结为后续乐观并发基线。
            sha = await client.get_branch_head(source.project_id, source.target_branch)
            raw = await client.get_file_optional(
                source.project_id,
                repository_path,
                sha,
            )
        finally:
            await client.close()
        if raw is None:
            content = None
        else:
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise AppServiceError("Agent 仅支持读取 UTF-8 文本文档") from exc
        adapter = GitLabProjectSource(
            host_id=source.host_id,
            project_id=source.project_id,
            source_id=source.id,
            department_code=source.department_code,
            default_visibility=source.default_visibility,
        )
        return GitLabDocumentSnapshot(
            source=source,
            repository_path=repository_path,
            doc_id=document.doc_id if document is not None else adapter.doc_id(repository_path),
            source_revision=sha,
            acl=(
                dict(document.acl_json)
                if document is not None
                else adapter.default_acl()
            ),
            content=content,
        )

    async def submit_changes(
        self,
        *,
        task_plan_id: str,
        actions: list[
            tuple[
                KnowledgeDocumentActionRequest,
                KnowledgeDocumentActionPreview,
                str | None,
            ]
        ],
        user: CurrentUserContext,
    ) -> list[SubmittedGitLabChange]:
        resolved = [
            await self._resolve_action(request, preview, expected_hash, user)
            for request, preview, expected_hash in actions
        ]
        by_source: dict[str, list[_ResolvedAction]] = {}
        # 一个 TaskPlan 可修改多个部门 Project；每个 Project 独立创建一个分支和 MR。
        for item in resolved:
            by_source.setdefault(item.source.id, []).append(item)

        submitted: dict[str, SubmittedGitLabChange] = {}
        for source_id, items in by_source.items():
            submitted[source_id] = await self._submit_project(
                task_plan_id=task_plan_id,
                source=items[0].source,
                actions=items,
                user=user,
            )
        return [submitted[item.source.id] for item in resolved]

    async def _submit_project(
        self,
        *,
        task_plan_id: str,
        source: GitLabSourceTable,
        actions: list[_ResolvedAction],
        user: CurrentUserContext,
    ) -> SubmittedGitLabChange:
        existing = await self.repository.get_change_request(task_plan_id, source.id)
        if existing is not None and existing.merge_request_url:
            # task_plan_id + source_id 有唯一约束。确认接口重复提交时直接返回原 MR，
            # 不再创建第二个分支、Commit 或 MR。
            return _submitted(existing)

        branch_name = (
            existing.branch_name
            if existing is not None
            else _branch_name(task_plan_id, source.department_code)
        )
        client = self._client(source)
        try:
            main_sha = await client.get_branch_head(
                source.project_id,
                source.target_branch,
            )
            if existing is None:
                existing = GitLabChangeRequestTable(
                    id=f"gitlab_cr_{uuid4().hex}",
                    task_plan_id=task_plan_id,
                    source_id=source.id,
                    branch_name=branch_name,
                    base_sha=main_sha,
                    status="draft",
                )
                await self.repository.save_change_request(existing)

            branch_sha = await client.get_branch_head_optional(
                source.project_id,
                branch_name,
            )
            if branch_sha is None:
                # 临时分支始终从配置的正式分支当前 HEAD 创建，不接受模型提供 ref，
                # 因此模型无法把 MR 基线改到任意分支。
                existing.base_sha = main_sha
                await self.repository.save_change_request(existing)
                await client.create_branch(
                    source.project_id,
                    branch=branch_name,
                    ref=main_sha,
                )
                branch_sha = main_sha

            if branch_sha == existing.base_sha:
                commit_actions = await self._build_commit_actions(
                    client=client,
                    source=source,
                    base_sha=existing.base_sha,
                    actions=actions,
                )
                commit = await client.create_commit(
                    source.project_id,
                    branch=branch_name,
                    commit_message=f"Agent 文档变更：{task_plan_id}",
                    actions=commit_actions,
                )
                commit_sha = commit.id
            else:
                # 分支已经有 Commit 说明上一次请求至少完成了提交；恢复时复用现状，
                # 避免同一个确认计划重复写入相同内容。
                commit_sha = branch_sha

            merge_request = await client.find_merge_request(
                source.project_id,
                source_branch=branch_name,
            )
            if merge_request is None:
                # target_branch 来自服务端 Source 配置，固定为正式分支；不使用
                # Agent/LLM 输出的目标分支。main 的保护规则再阻止 Developer 直接 Push。
                merge_request = await client.create_merge_request(
                    source.project_id,
                    source_branch=branch_name,
                    target_branch=source.target_branch,
                    title=f"Agent 文档变更：{task_plan_id}",
                    description=(
                        f"由 RAG Agent 提交，确认用户：{user.user_id}。\n\n"
                        "合并到 main 后才会触发知识库同步。"
                    ),
                )
            existing.commit_sha = commit_sha
            existing.merge_request_iid = merge_request.iid
            existing.merge_request_url = merge_request.web_url
            existing.status = merge_request.state
            await self.repository.save_change_request(existing)
            return _submitted(existing)
        finally:
            await client.close()

    async def _build_commit_actions(
        self,
        *,
        client: GitLabClient,
        source: GitLabSourceTable,
        base_sha: str,
        actions: list[_ResolvedAction],
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        for item in actions:
            if item.repository_path in seen_paths:
                raise AppServiceError("同一 MR 中不能重复修改同一文档")
            seen_paths.add(item.repository_path)
            current = await client.get_file_optional(
                source.project_id,
                item.repository_path,
                base_sha,
            )
            if item.request.operation == KnowledgeDocumentOperation.CREATE:
                if current is not None:
                    raise AppServiceError("GitLab main 中目标文档已存在")
                result.append(
                    {
                        "action": "create",
                        "file_path": item.repository_path,
                        "content": item.request.content or "",
                        "encoding": "text",
                    }
                )
                continue
            if current is None:
                raise AppServiceError("GitLab main 中目标文档不存在")
            current_hash = hashlib.sha256(current).hexdigest()
            if (
                item.expected_before_hash
                and current_hash != item.expected_before_hash
            ):
                raise AppServiceError(
                    "GitLab main 文档已变化，拒绝执行旧的确认计划"
                )
            action = {
                "action": item.request.operation.value,
                "file_path": item.repository_path,
                # GitLab 在执行 update/delete 时再次校验文件最后提交 SHA，
                # 与内容 hash 一起防止人工确认后 main 已变化却仍覆盖新内容。
                "last_commit_id": base_sha,
            }
            if item.request.operation == KnowledgeDocumentOperation.UPDATE:
                action.update(
                    content=item.request.content or "",
                    encoding="text",
                )
            result.append(action)
        return result

    async def _resolve_action(
        self,
        request: KnowledgeDocumentActionRequest,
        preview: KnowledgeDocumentActionPreview,
        expected_hash: str | None,
        user: CurrentUserContext,
    ) -> _ResolvedAction:
        department = (
            request.expected_department_codes[0]
            if len(request.expected_department_codes) == 1
            else user.primary_department_code
        )
        source, repository_path, document = await self._resolve_location(
            target_path=preview.normalized_path,
            doc_id=preview.affected_doc_id,
            department_code=department,
            allow_missing=request.operation == KnowledgeDocumentOperation.CREATE,
        )
        return _ResolvedAction(
            request=request,
            preview=preview,
            expected_before_hash=expected_hash,
            source=source,
            document=document,
            repository_path=repository_path,
        )

    async def _resolve_location(
        self,
        *,
        target_path: str,
        doc_id: str | None,
        department_code: str | None,
        allow_missing: bool = False,
    ) -> tuple[GitLabSourceTable, str, GitLabDocumentTable | None]:
        document = await self.repository.get_document(doc_id) if doc_id else None
        if document is not None:
            # 已有文档优先相信 PostgreSQL Manifest 中的 source_id + repository_path，
            # 不让用户输入或模型猜测重新选择 Project。
            source = await self.repository.get_source(document.source_id)
            if source is None or source.status != "active":
                raise AppServiceError("文档对应的 GitLab Source 不可用")
            return source, document.repository_path, document

        normalized = _repository_path(target_path)
        document = await self.repository.find_document_by_path(normalized)
        if document is not None:
            source = await self.repository.get_source(document.source_id)
            if source is None:
                raise AppServiceError("文档对应的 GitLab Source 不存在")
            return source, document.repository_path, document
        if not allow_missing or not department_code:
            raise AppServiceError("无法把目标文档定位到唯一 GitLab Project")
        source = await self.repository.find_source_by_department(department_code)
        if source is None:
            raise AppServiceError("当前部门没有配置 GitLab Source")
        # CREATE 尚无 Manifest，只能按已确认的部门选择唯一 Source；路径保持完整，
        # 不能因为 Project 已代表部门就擅自剥离 development/ 等目录前缀。
        return source, _repository_path(normalized), None

    def _client(self, source: GitLabSourceTable) -> GitLabClient:
        # Agent 使用独立的 rag-agent Token；它可以创建临时分支/Commit/MR，
        # 与 Worker 的只读 rag-sync Token 分离。
        return GitLabClient(
            base_url=source.base_url,
            token=get_secret_env_value(source.agent_token_env),
            timeout_seconds=self.settings.gitlab_request_timeout_seconds,
            max_retries=self.settings.gitlab_max_retries,
        )


def _repository_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise AppServiceError("GitLab Repository Path 非法")
    return path.as_posix()


def _branch_name(task_plan_id: str, department_code: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", task_plan_id).strip("-")[:80]
    suffix = hashlib.sha256(
        f"{task_plan_id}:{department_code}".encode("utf-8")
    ).hexdigest()[:8]
    return f"agent/{slug or 'task'}-{suffix}"


def _submitted(row: GitLabChangeRequestTable) -> SubmittedGitLabChange:
    if (
        not row.commit_sha
        or row.merge_request_iid is None
        or not row.merge_request_url
    ):
        raise AppServiceError("GitLab Change Request 尚未完成")
    return SubmittedGitLabChange(
        source_id=row.source_id,
        branch_name=row.branch_name,
        commit_sha=row.commit_sha,
        merge_request_iid=row.merge_request_iid,
        merge_request_url=row.merge_request_url,
        status=row.status,
    )


__all__ = [
    "GitLabAgentChangeService",
    "GitLabDocumentSnapshot",
    "SubmittedGitLabChange",
]
