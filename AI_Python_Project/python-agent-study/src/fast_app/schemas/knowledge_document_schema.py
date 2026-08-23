from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from fast_app.domain.knowledge_permissions import DocumentAccessSource


KnowledgeDocumentType = Literal[
    "markdown",
    "text",
    "pdf",
    "powerpoint",
    "spreadsheet",
    "word",
]
KnowledgeDocumentRenderMode = Literal["markdown", "plain_text", "extracted_text"]


class KnowledgeDocumentItem(BaseModel):
    doc_id: str = Field(description="GitLab 文档稳定 ID，也是详情和来源跳转标识。")
    title: str = Field(description="由可信仓库文件名生成的文档展示标题。")
    file_name: str = Field(description="文档在 GitLab 仓库中的原始 basename。")
    repository_path: str = Field(description="文档在所属 GitLab Project 中的仓库相对路径。")
    department_code: str = Field(description="文档所属 GitLab Source 的部门 code。")
    document_type: KnowledgeDocumentType = Field(description="服务端识别的文档格式。")
    source_revision: str = Field(description="内容和下载必须读取的固定 Git revision。")
    updated_at: datetime = Field(description="文档 manifest 最后更新时间。")
    access_source: DocumentAccessSource = Field(
        description="当前用户获得读取权限的服务端裁决来源。",
    )


class KnowledgeDocumentListResponse(BaseModel):
    items: list[KnowledgeDocumentItem] = Field(
        description="当前页中已通过服务端 ACL 的 active 正式文档。",
    )
    next_cursor: str | None = Field(
        default=None,
        description="下一页不透明 keyset cursor；没有更多文档时为空。",
    )


class KnowledgeDocumentDetail(KnowledgeDocumentItem):
    source_id: str = Field(description="文档所属 GitLab Source 稳定 ID。")
    source_project_path: str = Field(description="文档所属 GitLab Project 展示路径。")
    visibility: str = Field(description="GitLab 原始 ACL 的 visibility 值。")


class KnowledgeDocumentContentResponse(BaseModel):
    doc_id: str = Field(description="当前预览对应的稳定文档 ID。")
    source_revision: str = Field(description="本次预览实际读取的固定 Git revision。")
    document_type: KnowledgeDocumentType = Field(description="原始文档格式。")
    render_mode: KnowledgeDocumentRenderMode = Field(
        description="前端应使用 markdown、纯文本或提取文本方式渲染。",
    )
    content: str = Field(description="经过有界截断的 UTF-8 安全文本预览。")
    truncated: bool = Field(description="预览是否因为服务端字符上限而被截断。")
    warnings: list[str] = Field(
        description="解析降级、缺失内容或截断等非致命提示代码。",
    )


__all__ = [
    "KnowledgeDocumentContentResponse",
    "KnowledgeDocumentDetail",
    "KnowledgeDocumentItem",
    "KnowledgeDocumentListResponse",
    "KnowledgeDocumentRenderMode",
    "KnowledgeDocumentType",
]
