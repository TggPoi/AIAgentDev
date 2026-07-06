from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeDocumentOperation(StrEnum):
    """Agent 可以提出的知识库文档管理动作。"""

    # 新建知识库文档。
    CREATE = "create"
    # 更新已有知识库文档。
    UPDATE = "update"
    # 删除已有知识库文档。
    DELETE = "delete"


class KnowledgeDocumentRiskLevel(StrEnum):
    """文档管理动作的风险等级，用于权限网关和 TaskPlan 人工确认。"""

    # 中风险动作，通常需要记录审计但不一定需要人工确认。
    MEDIUM = "medium"
    # 高风险动作，需要 TaskPlan 人工确认。
    HIGH = "high"
    # 关键风险动作，代表删除或影响范围更大的操作。
    CRITICAL = "critical"


class KnowledgeDocumentActionRequest(BaseModel):
    """Agent 提出的文档管理意图。

    这个模型只表达“想做什么”，不代表系统已经允许执行。真正的路径校验、
    权限判断、dry-run 和后续执行都必须进入 service 层。
    """

    # 禁止 planner 输出未声明字段，避免工具层误读多余参数。
    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation = Field(description="目标文档动作：create / update / delete。")
    target_path: str = Field(min_length=1, max_length=512, description="知识库内相对目标路径。")
    content: str | None = Field(default=None, max_length=200_000, description="create/update 的目标正文；delete 时为空。")
    reason: str = Field(min_length=1, max_length=1000, description="Agent 或用户给出的动作原因。")
    dry_run: bool = Field(default=True, description="是否只做预览；当前高风险动作默认先 dry-run。")
    expected_department_codes: list[str] = Field(
        default_factory=list,
        description="用户或 planner 预期的目标部门 code，用于和实际 metadata 对比。",
    )

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

    preview 是后续工具权限、TaskPlan 确认和审计日志最重要的结构化输入。它需要告诉
    上游这次操作影响哪个文档、风险多高、预计权限 metadata 是什么。
    """

    # 预览结果是权限和确认的事实输入，禁止混入未声明字段。
    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation = Field(description="预览对应的文档动作。")
    target_path: str = Field(description="用户或 planner 提供的原始目标路径。")
    normalized_path: str = Field(description="服务端规范化后的知识库相对路径。")
    exists_before: bool = Field(description="执行前目标文档是否已经存在。")
    risk_level: KnowledgeDocumentRiskLevel = Field(description="根据动作和目标状态计算出的风险等级。")
    affected_doc_id: str | None = Field(default=None, description="预计受影响的文档 ID；新建时可为空。")
    affected_chunk_count: int = Field(default=0, description="预计受影响的 chunk 数量。")
    before_hash: str | None = Field(default=None, description="执行前文档内容 hash；新建时为空。")
    after_hash: str | None = Field(default=None, description="执行后目标内容 hash；删除时可为空。")
    permission_metadata: dict[str, Any] = Field(default_factory=dict, description="从目标路径或文档推断出的权限 metadata。")
    warnings: list[str] = Field(default_factory=list, description="dry-run 阶段发现的风险提示或注意事项。")
    requires_confirmation: bool = Field(default=True, description="该动作是否需要进入人工确认流程。")


class KnowledgeDocumentActionResult(BaseModel):
    """文档管理工具返回给 Agent 的结构化结果。"""

    # 工具结果只暴露稳定字段，便于 Agent、API 和审计日志统一消费。
    model_config = ConfigDict(extra="forbid")

    operation: KnowledgeDocumentOperation = Field(description="本次工具请求执行的文档动作。")
    target_path: str = Field(description="工具作用的知识库相对目标路径。")
    dry_run: bool = Field(description="本次调用是否为预览模式。")
    executed: bool = Field(description="是否已经执行真实写入或删除动作。")
    preview: KnowledgeDocumentActionPreview = Field(description="执行前生成的结构化预览。")
    message: str = Field(description="面向 Agent / API 调用方展示的结果说明。")
    audit_id: str | None = Field(default=None, description="审计记录 ID；没有落审计时为空。")


__all__ = [
    "KnowledgeDocumentActionPreview",
    "KnowledgeDocumentActionRequest",
    "KnowledgeDocumentActionResult",
    "KnowledgeDocumentOperation",
    "KnowledgeDocumentRiskLevel",
]
