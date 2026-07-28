from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GitLabProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="GitLab Project 的数字 ID。")
    path_with_namespace: str = Field(description="带 Group 命名空间的 Project 路径。")
    default_branch: str | None = Field(
        default=None,
        description="Project 当前默认分支；尚未创建分支时为空。",
    )
    web_url: str = Field(description="供资产管理者在浏览器打开的 Project URL。")


class GitLabDiff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    old_path: str = Field(description="变更前的仓库相对路径。")
    new_path: str = Field(description="变更后的仓库相对路径。")
    new_file: bool = Field(default=False, description="是否为新增文件。")
    renamed_file: bool = Field(default=False, description="是否为重命名文件。")
    deleted_file: bool = Field(default=False, description="是否为删除文件。")


class GitLabCompareResult(BaseModel):
    commit_sha: str = Field(description="Compare 目标 Commit SHA。")
    compare_timeout: bool = Field(
        default=False,
        description="GitLab 是否因比较超时而返回不完整结果。",
    )
    compare_same_ref: bool = Field(
        default=False,
        description="Compare 起止引用是否指向同一个 Commit。",
    )
    overflow: bool = Field(
        default=False,
        description="GitLab 是否明确标记 diff 结果已截断。",
    )
    diffs: list[GitLabDiff] = Field(description="归一化后的仓库文件差异。")


class GitLabCommitResult(BaseModel):
    id: str = Field(description="GitLab 创建的 Commit SHA。")
    web_url: str | None = Field(
        default=None,
        description="Commit Web URL；GitLab 未返回时为空。",
    )


class GitLabMergeRequestResult(BaseModel):
    iid: int = Field(description="Merge Request 在 Project 内的 IID。")
    web_url: str = Field(description="供人工审核的 Merge Request URL。")
    state: str = Field(description="GitLab 返回的 Merge Request 状态。")


class GitLabPushProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(description="Webhook 所属 GitLab Project ID。")
    path_with_namespace: str | None = Field(
        default=None,
        description="Webhook 所属 Project 命名空间路径。",
    )


class GitLabPushWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_kind: str = Field(description="GitLab Webhook 对象类型，Push 时为 push。")
    before: str = Field(description="Push 前的 Commit SHA。")
    after: str = Field(description="Push 后的 Commit SHA。")
    ref: str = Field(description="Push 对应的完整 Git ref。")
    checkout_sha: str | None = Field(
        default=None,
        description="GitLab 可检出的目标 SHA；删除分支时可能为空。",
    )
    project: GitLabPushProject = Field(description="Webhook Project 身份。")


class GitLabSourceResponse(BaseModel):
    id: str = Field(description="RAG 系统中的 GitLab Source ID。")
    base_url: str = Field(description="GitLab 服务根 URL。")
    project_id: int = Field(description="GitLab Project 数字 ID。")
    project_path: str = Field(description="GitLab Project 命名空间路径。")
    target_branch: str = Field(description="RAG 只同步的正式分支。")
    department_code: str = Field(description="Source 对应的部门安全边界。")
    default_visibility: str = Field(description="Source 默认文档可见范围。")
    last_synced_sha: str | None = Field(description="最近成功发布的 main SHA。")
    desired_sha: str | None = Field(description="Worker 当前需要追赶到的 main SHA。")
    status: str = Field(description="Source 当前状态。")


class GitLabSyncRequest(BaseModel):
    mode: Literal["full", "reconcile"] = Field(
        description="管理员手动触发的同步模式。",
    )
    target_sha: str | None = Field(
        default=None,
        min_length=7,
        max_length=64,
        description="可选目标 SHA；为空时读取目标分支当前 HEAD。",
    )


class GitLabSyncJobResponse(BaseModel):
    id: str = Field(description="GitLab 同步任务 ID。")
    source_id: str = Field(description="任务对应的 GitLab Source ID。")
    mode: str = Field(description="任务模式：full、incremental、reconcile 或 bootstrap。")
    status: str = Field(description="任务状态。")
    phase: str = Field(description="Worker 当前执行阶段。")
    base_sha: str | None = Field(description="增量同步起点 SHA。")
    target_sha: str = Field(description="本任务冻结的目标 SHA。")
    candidate_version: int | None = Field(description="本任务构建的候选知识版本。")
    attempt_count: int = Field(description="Worker 已尝试执行次数。")
    document_count: int = Field(description="任务处理的文档数量。")
    parent_count: int = Field(description="任务生成的 Markdown 父块数量。")
    child_count: int = Field(description="任务生成的可检索 Chunk 数量。")
    change_counts: dict[str, int] = Field(description="新增、修改、删除等统计。")
    error_code: str | None = Field(description="稳定机器可读错误码。")
    error_message: str | None = Field(description="面向管理员的错误摘要。")
    created_at: datetime = Field(description="任务创建时间。")
    updated_at: datetime = Field(description="任务最近更新时间。")


class GitLabWebhookAcceptedResponse(BaseModel):
    accepted: bool = Field(description="事件是否属于已配置 main 分支并被系统接受。")
    duplicate: bool = Field(description="该 Delivery 是否已经处理过。")
    job_id: str | None = Field(
        description="创建或合并后的同步任务 ID；忽略或重复事件时为空。",
    )
    target_sha: str | None = Field(
        description="Worker 需要追赶的目标 SHA；忽略事件时为空。",
    )


class KnowledgePublicationStatusResponse(BaseModel):
    active_version: int = Field(description="所有新 RAG 请求冻结使用的正式知识版本。")
    syncing: bool = Field(description="当前是否存在运行或发布中的 GitLab 同步任务。")
    latest_candidate_version: int | None = Field(
        description="最近候选知识版本；尚未产生候选版本时为空。",
    )


class KnowledgeChangeDocument(BaseModel):
    change_type: Literal["added", "modified", "deleted", "renamed"] = Field(
        description="该文档在发布批次中的变化类型。",
    )
    doc_id: str = Field(description="RAG 中跨接口稳定的文档 ID。")
    source_path: str = Field(description="GitLab Repository 相对路径。")
    title: str = Field(description="前端通知展示的文档名称。")


class KnowledgeChangeEventResponse(BaseModel):
    id: int = Field(description="单调递增的通知游标 ID。")
    publication_version: int = Field(description="该变化正式生效的知识版本。")
    event_type: str = Field(description="通知类型。")
    changes: list[KnowledgeChangeDocument] = Field(
        description="当前用户有权感知的文档变化。",
    )
    published_at: datetime = Field(description="知识版本正式发布时间。")


class KnowledgeChangeEventListResponse(BaseModel):
    items: list[KnowledgeChangeEventResponse] = Field(
        description="按事件 ID 升序返回的权限过滤后通知。",
    )
    next_after_id: int = Field(description="React 下一次轮询应携带的 after_id。")


GitLabCommitAction = dict[str, Any]


__all__ = [
    "GitLabCommitAction",
    "GitLabCommitResult",
    "GitLabCompareResult",
    "GitLabDiff",
    "GitLabMergeRequestResult",
    "GitLabProject",
    "GitLabPushWebhook",
    "GitLabSourceResponse",
    "GitLabSyncJobResponse",
    "GitLabSyncRequest",
    "GitLabWebhookAcceptedResponse",
    "KnowledgeChangeEventListResponse",
    "KnowledgeChangeEventResponse",
    "KnowledgePublicationStatusResponse",
]
