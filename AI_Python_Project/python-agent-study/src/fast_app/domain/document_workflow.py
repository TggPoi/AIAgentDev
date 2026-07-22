"""复杂文档任务在 Supervisor、Deep Agents 与确定性写入层之间的结构化契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DocumentWorkflowOperation = Literal["create", "update", "delete"]
DocumentDeliverableStatus = Literal["completed", "failed", "skipped"]


class DocumentDeliverable(BaseModel):
    """Supervisor 识别出的一个独立文档交付物。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deliverable_id: str = Field(
        min_length=1,
        max_length=80,
        description="Supervisor 分配的稳定交付物 ID；下游 Agent 必须原样传递。",
    )
    title: str = Field(
        min_length=1,
        max_length=200,
        description="供人和子 Agent 识别该交付物的简短标题。",
    )
    operation: DocumentWorkflowOperation = Field(
        description="该交付物最终允许建议的文档操作：create、update 或 delete。"
    )
    target_hint: str | None = Field(
        default=None,
        max_length=512,
        description="用户提到的目标名称或范围提示；不是可信路径或 doc_id。",
    )
    objective: str = Field(
        min_length=1,
        max_length=2_000,
        description="该交付物必须独立完成的具体内容目标。",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="必须先完成的 deliverable_id 列表；无依赖时为空。",
    )
    source_requirements: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="完成交付物所需的证据或信息来源要求。",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="完成交付物需要的能力，例如知识库检索、联网研究或审查。",
    )


class DocumentWorkflowDecision(BaseModel):
    """Supervisor 的受限决定；它不是可执行写入计划。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    execution_mode: Literal["direct", "agentic"] = Field(
        description="执行模式：direct 使用单 Agent Tool Loop；agentic 使用显式文档子 Agent。"
    )
    objective: str = Field(
        min_length=1,
        max_length=2_000,
        description="Supervisor 从用户请求中提炼出的整体文档任务目标。",
    )
    deliverables: list[DocumentDeliverable] = Field(
        description=(
            "agentic 模式下最终要创建、更新或删除的独立文档交付物；Researcher、"
            "Writer、Reviewer 是每个交付物内部的处理阶段，禁止拆成独立交付物；"
            "direct 模式下应为空。"
        )
    )
    web_policy: Literal["disabled", "fallback", "required"] = Field(
        default="disabled",
        description="联网策略：禁止、仅本地证据不足时兜底，或必须联网。",
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
        description="选择当前执行模式和交付物拆分方式的简要理由。",
    )


class DocumentResearchResult(BaseModel):
    """Researcher 返回的证据摘要。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deliverable_id: str = Field(
        description="本研究结果对应的 Supervisor deliverable_id，必须原样传递。"
    )
    status: Literal["completed", "partial", "failed"] = Field(
        description="研究状态：已充分完成、仅部分完成或没有形成可用研究结果。"
    )
    findings: list[str] = Field(
        default_factory=list,
        description="从证据中得到、与交付物目标直接相关的事实结论。",
    )
    evidence: list[dict[str, object]] = Field(
        default_factory=list,
        description="可核验的来源摘要，包含来源 ID、路径或公开 URL 等引用事实。",
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="不同来源之间尚未解决的事实冲突。",
    )
    missing_points: list[str] = Field(
        default_factory=list,
        description="当前证据仍未覆盖、Writer 不应自行猜测的内容点。",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="不阻断研究结果但应由 Writer 或 Reviewer 注意的限制。",
    )


class DocumentDraftResult(BaseModel):
    """Writer 生成的一版完整草稿。"""

    # 正文中的首尾空白可能有业务意义，不能使用全局 str_strip_whitespace。
    model_config = ConfigDict(extra="forbid")

    deliverable_id: str = Field(
        description="本草稿对应的 Supervisor deliverable_id，必须原样传递。"
    )
    operation: DocumentWorkflowOperation = Field(
        description="草稿对应的操作类型，必须与 Supervisor 交付物一致。"
    )
    candidate_doc_id: str | None = Field(
        default=None,
        description="update/delete 使用的 ACL 检索候选 doc_id；create 时为空。",
    )
    candidate_source_path: str | None = Field(
        default=None,
        description="Researcher 返回的候选源路径，仅用于交叉验证，不能自行构造。",
    )
    filename: str | None = Field(
        default=None,
        description="create 建议的 .md/.txt 文件名；目录由服务端决定。",
    )
    base_sha256: str | None = Field(
        default=None,
        description="Researcher 读取 update 目标时得到的原文 SHA-256。",
    )
    title: str = Field(default="", description="草稿的可读标题。")
    content: str | None = Field(
        default=None,
        description="create/update 的完整最终候选正文；delete 时为空。",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="草稿实际采用的研究证据引用 ID。",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="证据未直接证明但草稿明确采用的假设。",
    )
    unresolved_points: list[str] = Field(
        default_factory=list,
        description="草稿仍未解决、必须交给 Reviewer 判断的问题。",
    )


class DocumentReviewResult(BaseModel):
    """Reviewer 对草稿的结构化判断。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deliverable_id: str = Field(
        description="被审查草稿对应的 Supervisor deliverable_id，必须原样传递。"
    )
    verdict: Literal["approved", "revision_required", "rejected"] = Field(
        description=(
            "审查结论：approved 可进入变更校验；revision_required 必须交回 Writer；"
            "rejected 表示不能继续。"
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Reviewer 对当前审查结论的置信度，范围 0 到 1。",
    )
    factual_issues: list[str] = Field(
        default_factory=list,
        description="草稿中与研究证据不一致的具体事实问题。",
    )
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description="草稿中缺少证据支持的具体陈述。",
    )
    missing_sections: list[str] = Field(
        default_factory=list,
        description="为满足交付物目标仍需补充的章节或内容。",
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="草稿未妥善呈现或处理的证据冲突。",
    )
    revision_instructions: list[str] = Field(
        default_factory=list,
        description="verdict=revision_required 时交给 Writer 的可执行修改要求。",
    )


class DocumentChangeProposal(BaseModel):
    """Reviewer 通过后交给服务端验证的变更建议；仍不具备写权限。"""

    model_config = ConfigDict(extra="forbid")

    deliverable_id: str = Field(
        description="本建议对应的 Supervisor deliverable_id，必须原样传递。"
    )
    operation: DocumentWorkflowOperation = Field(
        description="建议的操作类型，必须与 Supervisor 和最终草稿一致。"
    )
    candidate_doc_id: str | None = Field(
        default=None,
        description="update/delete 的 ACL 检索候选 doc_id；create 时为空。",
    )
    candidate_source_path: str | None = Field(
        default=None,
        description="Researcher 返回的候选源路径；服务端会与 doc_id 重新核对。",
    )
    filename: str | None = Field(
        default=None,
        description="create 建议的文件名；真实目录由服务端生成。",
    )
    base_sha256: str | None = Field(
        default=None,
        description="update 目标被 Researcher 读取时的 SHA-256。",
    )
    content: str | None = Field(
        default=None,
        description="与 Writer 最终草稿完全一致的 create/update 完整正文。",
    )
    reason: str = Field(
        min_length=1,
        max_length=1_000,
        description="为什么需要执行该文档变更。",
    )
    selection_reason: str = Field(
        default="",
        max_length=1_000,
        description="为什么该 ACL 检索候选是正确操作目标。",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="支持该变更建议的研究证据引用 ID。",
    )
    review: DocumentReviewResult = Field(
        description="该交付物最后一次 Reviewer 返回的 approved 审查结果。"
    )

    @model_validator(mode="after")
    def validate_operation_fields(self) -> "DocumentChangeProposal":
        if self.review.verdict != "approved":
            raise ValueError("只有 Reviewer approved 的草稿才能形成变更建议")
        if self.operation == "create":
            if not self.filename or self.content is None:
                raise ValueError("create 必须提供 filename 和 content")
        elif self.operation == "update":
            if not self.candidate_doc_id or not self.base_sha256 or self.content is None:
                raise ValueError("update 必须提供 candidate_doc_id、base_sha256 和 content")
        elif not self.candidate_doc_id:
            raise ValueError("delete 必须提供 candidate_doc_id")
        return self


class DocumentDeliverableFailure(BaseModel):
    """未能形成可确认动作的交付物结果。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deliverable_id: str = Field(description="失败或跳过的 Supervisor deliverable_id。")
    status: Literal["failed", "skipped"] = Field(
        description="failed 表示自身执行失败；skipped 表示因依赖失败而未执行。"
    )
    error_code: str = Field(description="稳定的机器可读失败或跳过错误码。")
    reason: str = Field(description="供人工复查的失败或跳过原因。")


class DocumentWorkflowResult(BaseModel):
    """DeepDocumentAgent 的唯一结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    research_results: list[DocumentResearchResult] = Field(
        default_factory=list,
        description="每个交付物实际产生的 Researcher 结构化结果。",
    )
    draft_results: list[DocumentDraftResult] = Field(
        default_factory=list,
        description="Writer 产生的全部草稿版本，按执行顺序排列。",
    )
    review_results: list[DocumentReviewResult] = Field(
        default_factory=list,
        description="Reviewer 产生的全部审查版本，按执行顺序排列。",
    )
    approved_changes: list[DocumentChangeProposal] = Field(
        default_factory=list,
        description="最终 Reviewer 批准且等待服务端验证的变更建议。",
    )
    failed_deliverables: list[DocumentDeliverableFailure] = Field(
        default_factory=list,
        description="自身执行失败、未形成可确认动作的交付物。",
    )
    skipped_deliverables: list[DocumentDeliverableFailure] = Field(
        default_factory=list,
        description="因前置依赖失败而未执行的交付物。",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="不阻断可用变更但必须向用户展示的工作流限制。",
    )
    used_tools: list[str] = Field(
        default_factory=list,
        description="工作流声称使用的工具名；服务端会用实际调用记录覆盖。",
    )
    evidence: list[dict[str, object]] = Field(
        default_factory=list,
        description="工作流汇总的可核验证据摘要，不包含权限外原文。",
    )


__all__ = [
    "DocumentChangeProposal",
    "DocumentDeliverable",
    "DocumentDeliverableFailure",
    "DocumentDraftResult",
    "DocumentResearchResult",
    "DocumentReviewResult",
    "DocumentWorkflowDecision",
    "DocumentWorkflowResult",
]
