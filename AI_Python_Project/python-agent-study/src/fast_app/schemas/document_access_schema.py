from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fast_app.schemas.knowledge_document_schema import KnowledgeDocumentType


DocumentAccessGrantStatus = Literal["active", "revoked"]


class DocumentAccessGrantableDocumentItem(BaseModel):
    doc_id: str = Field(description="可作为跨部门授权候选的active非public文档稳定ID。")
    title: str = Field(description="由可信仓库文件名生成的候选文档展示标题。")
    repository_path: str = Field(description="候选文档在GitLab Project中的仓库相对路径。")
    document_department_code: str = Field(
        description="候选文档所属部门code；主管范围由服务端固定。",
    )
    document_type: KnowledgeDocumentType = Field(
        description="服务端识别的候选文档格式。",
    )


class DocumentAccessGrantableDocumentListResponse(BaseModel):
    items: list[DocumentAccessGrantableDocumentItem] = Field(
        description="当前actor有权管理的active非public文档候选项。",
    )
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明keyset cursor；没有更多候选项时为空。",
    )


class DocumentAccessGrantUser(BaseModel):
    user_id: str = Field(description="被授权用户唯一 ID。")
    username: str = Field(description="被授权用户稳定登录用户名。")
    display_name: str | None = Field(
        default=None,
        description="被授权用户展示名称；未设置时为空。",
    )
    primary_department_code: str | None = Field(
        default=None,
        description="被授权用户主归属部门；没有部门时为空。",
    )


class DocumentAccessGrantItem(BaseModel):
    grant_id: str = Field(description="跨部门文档读取授权唯一 ID。")
    document_id: str = Field(description="被精确授权的 GitLab 文档 doc_id。")
    repository_path: str = Field(description="文档在 GitLab Project 中的稳定仓库相对路径。")
    document_department_code: str = Field(
        description="文档所属 GitLab Source 的部门 code，也是主管授权范围依据。",
    )
    grantee: DocumentAccessGrantUser = Field(description="被授权用户最小身份摘要。")
    status: DocumentAccessGrantStatus = Field(
        description="授权状态：active 立即生效，revoked 仅保留审计。",
    )
    granted_by_user_id: str = Field(description="创建该授权的 actor 用户 ID。")
    granted_at: datetime = Field(description="授权创建时间，也是列表稳定排序依据。")
    revoked_by_user_id: str | None = Field(
        default=None,
        description="撤销授权的 actor 用户 ID；active 时为空。",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="授权撤销时间；active 时为空。",
    )


class DocumentAccessGrantListResponse(BaseModel):
    items: list[DocumentAccessGrantItem] = Field(
        description="当前页中 actor 有权管理的文档授权记录。",
    )
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明 keyset cursor；没有更多记录时为空。",
    )


class CreateDocumentAccessGrantsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_account: str = Field(
        min_length=1,
        max_length=255,
        description="被授权用户的精确用户名或邮箱；服务端规范化后查询 active 账号。",
    )
    document_ids: list[str] = Field(
        min_length=1,
        max_length=100,
        description="本次原子授权的精确 active GitLab 文档 doc_id 集合。",
    )

    @field_validator("target_account")
    @classmethod
    def normalize_target_account(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("target_account 不能只包含空白字符")
        return normalized

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 64 for item in normalized):
            raise ValueError("document_ids 每项长度必须在 1 到 64 之间")
        if len(set(normalized)) != len(normalized):
            raise ValueError("document_ids 不能包含重复值")
        return normalized


class CreateDocumentAccessGrantsResponse(BaseModel):
    items: list[DocumentAccessGrantItem] = Field(
        description="本次请求涉及的授权记录，包含新建和已存在的 active grant。",
    )
    created_count: int = Field(ge=0, description="本次事务实际新建的 active grant 数量。")
    existing_count: int = Field(ge=0, description="本次幂等复用的 active grant 数量。")


__all__ = [
    "CreateDocumentAccessGrantsRequest",
    "CreateDocumentAccessGrantsResponse",
    "DocumentAccessGrantableDocumentItem",
    "DocumentAccessGrantableDocumentListResponse",
    "DocumentAccessGrantItem",
    "DocumentAccessGrantListResponse",
    "DocumentAccessGrantStatus",
    "DocumentAccessGrantUser",
]
