from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeDocumentOperation(StrEnum):
    """Agent 可以提出的知识库文档管理动作。"""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class KnowledgeDocumentRiskLevel(StrEnum):
    """文档管理动作的风险等级，后续 15-7 会用于权限网关和人工确认。"""

    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class KnowledgeDocumentActionRequest(BaseModel):
    """Agent 提出的文档管理意图。

    这个模型只表达“想做什么”，不代表系统已经允许执行。真正的路径校验、
    权限判断、dry-run 和后续执行都必须进入 service 层。
    """

    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation
    target_path: str = Field(min_length=1, max_length=512)
    content: str | None = Field(default=None, max_length=200_000)
    reason: str = Field(min_length=1, max_length=1000)
    dry_run: bool = True
    expected_department_codes: list[str] = Field(default_factory=list)

    @field_validator("target_path", "reason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("content")
    @classmethod
    def normalize_optional_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.replace("\r\n", "\n")

    @field_validator("expected_department_codes")
    @classmethod
    def normalize_expected_departments(cls, value: list[str]) -> list[str]:
        return sorted({item.strip() for item in value if item.strip()})


class KnowledgeDocumentActionPreview(BaseModel):
    """文档管理 dry-run 预览。

    preview 是后续工具权限、人工确认和审计日志最重要的结构化输入。它需要告诉
    上游这次操作影响哪个文档、风险多高、预计权限 metadata 是什么。
    """

    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation
    target_path: str
    normalized_path: str
    exists_before: bool
    risk_level: KnowledgeDocumentRiskLevel
    affected_doc_id: str | None = None
    affected_chunk_count: int = 0
    before_hash: str | None = None
    after_hash: str | None = None
    permission_metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True


class KnowledgeDocumentActionResult(BaseModel):
    """文档管理工具返回给 Agent 的结构化结果。"""

    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation
    target_path: str
    dry_run: bool
    executed: bool
    preview: KnowledgeDocumentActionPreview
    message: str
    audit_id: str | None = None


__all__ = [
    "KnowledgeDocumentActionPreview",
    "KnowledgeDocumentActionRequest",
    "KnowledgeDocumentActionResult",
    "KnowledgeDocumentOperation",
    "KnowledgeDocumentRiskLevel",
]
