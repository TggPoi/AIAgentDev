"""Research TaskPlan v2 的规划、证据和执行状态模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fast_app.domain.agent_task_plan import AgentTaskPlanStatus, AgentTaskToolCallTrace


AgentTaskExternalSourceType = Literal[
    "knowledge_retrieval",
    "web_search",
    "nl2sql_query",
]
AgentTaskInformationSourceHint = Literal[
    "knowledge_retrieval",
    "web_search",
    "nl2sql_query",
    "none",
]
AgentTaskEvidenceType = Literal[
    "knowledge_chunk",
    "web_citation",
    "sql_query_result",
    "derived_synthesis",
]
RequirementCompletionPolicy = Literal["strict", "allow_partial"]
RequirementEvidenceStatus = Literal[
    "pending",
    "partially_satisfied",
    "satisfied",
    "failed",
]
ResearchSubQuestionStatus = Literal[
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "skipped",
]
WebUsage = Literal[
    "direct",
    "fallback_on_insufficient_evidence",
    "not_used",
]


class FrozenConversationTurn(BaseModel):
    """服务端冻结的会话消息；message_id 不进入模型可见上下文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message_id: str = Field(description="服务端消息 ID，仅用于校验历史消息归属。")
    role: Literal["user", "assistant"] = Field(description="消息发送角色。")
    content: str = Field(description="经过长度约束的消息正文。")


class AgentTaskPlanningTurn(BaseModel):
    """Planner 和 Reviewer 可见的有限会话消息。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"] = Field(description="模型可见的消息发送角色。")
    content: str = Field(description="解决当前指代所需的有限消息正文。")


class ResolvedPlanningRequest(BaseModel):
    """Router、Planner 和 Reviewer 共用的解析后规划请求。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    current_query: str = Field(description="用户当前输入，优先级高于历史消息。")
    relevant_history: list[AgentTaskPlanningTurn] = Field(
        default_factory=list,
        description="只包含解决当前指代所需的有限历史，不含内部消息 ID。",
    )
    resolved_query: str = Field(description="指代解析后的完整任务语义。")


class RequirementSourcePolicy(BaseModel):
    """一个 Requirement 对外部证据来源的确定性契约。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["all_of", "any_of", "none"] = Field(
        description="all_of 要求全部来源，any_of 接受任一来源，none 不读取新外部事实。"
    )
    source_types: list[AgentTaskExternalSourceType] = Field(
        default_factory=list,
        description="Requirement 允许或必须使用的外部来源；none 模式必须为空。",
    )

    @model_validator(mode="after")
    def validate_sources(self) -> RequirementSourcePolicy:
        self.source_types = list(dict.fromkeys(self.source_types))
        if self.mode == "none" and self.source_types:
            raise ValueError("mode=none 时 source_types 必须为空")
        if self.mode != "none" and not self.source_types:
            raise ValueError("all_of/any_of 必须声明至少一个外部来源")
        return self


class AgentTaskExpectedEvidence(BaseModel):
    """Requirement 期望获得的可计数证据。"""

    model_config = ConfigDict(extra="forbid")

    evidence_type: AgentTaskEvidenceType = Field(description="期望证据的结构化类型。")
    minimum_count: int = Field(
        ge=1,
        le=20,
        description="满足该证据契约所需的最少合法 Evidence 数量。",
    )
    requires_query_id: bool = Field(
        default=False,
        description="证据是否必须携带真实 NL2SQL query_id；仅 SQL 证据允许为 true。",
    )
    required_attributes: list[str] = Field(
        default_factory=list,
        description="SQL 结果必须提供的 Dataset 逻辑字段；非 SQL 证据必须为空。",
    )

    @model_validator(mode="after")
    def validate_contract(self) -> AgentTaskExpectedEvidence:
        self.required_attributes = list(
            dict.fromkeys(item.strip().lower() for item in self.required_attributes if item.strip())
        )
        if self.evidence_type == "sql_query_result":
            if not self.requires_query_id:
                raise ValueError("sql_query_result 必须 requires_query_id=true")
        elif self.requires_query_id:
            raise ValueError("非 SQL Evidence 不允许 requires_query_id=true")
        if self.evidence_type != "sql_query_result" and self.required_attributes:
            raise ValueError("required_attributes 只允许用于 sql_query_result")
        return self


class AgentTaskRequirement(BaseModel):
    """从 resolved query 拆出的原子需求及证据完成策略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str = Field(description="当前 Research TaskPlan 内唯一的 Requirement ID。")
    description: str = Field(description="必须由最终答案覆盖的原子用户需求。")
    source_policy: RequirementSourcePolicy = Field(description="该需求的外部来源组合规则。")
    expected_evidence: list[AgentTaskExpectedEvidence] = Field(
        description="该需求必须达到的结构化证据阈值。"
    )
    completion_policy: RequirementCompletionPolicy = Field(
        description="strict 不允许缺证据；allow_partial 允许带明确限制的部分结论。"
    )


class ResearchTaskSubQuestionCandidate(BaseModel):
    """Planner 和 Reviewer 可以生成或修订的不可信子问题候选。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sub_question_id: str = Field(description="当前候选计划内唯一的子问题 ID。")
    order: int = Field(ge=1, description="子问题的稳定展示和执行排序。")
    question: str = Field(description="Worker 需要回答的具体研究问题。")
    purpose: str = Field(description="该子问题对最终任务的作用。")
    depends_on: list[str] = Field(
        default_factory=list,
        description="该子问题依赖的前置候选子问题 ID。",
    )
    information_source_hint: AgentTaskInformationSourceHint = Field(
        description="Planner 建议的主要事实来源；不授予 Tool 权限。"
    )
    covers_requirement_ids: list[str] = Field(
        description="该子问题预期提供证据的 Requirement ID。"
    )
    reason: str = Field(description="为什么该问题和来源能够覆盖所声明的需求。")


class ResearchTaskSubQuestion(ResearchTaskSubQuestionCandidate):
    """通过校验后由服务端生成的正式研究子问题。"""

    web_usage: WebUsage = Field(
        description="服务端依据请求策略和来源提示计算的 Web 执行方式。"
    )


class AgentTaskSubQuestionEvidenceValidation(BaseModel):
    """一个 Worker 结果所携带 Evidence 的合法性校验结果。"""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(description="被校验的正式研究子问题 ID。")
    valid_evidence_refs: list[str] = Field(
        default_factory=list,
        description="通过 Schema 和真实 Tool 来源校验的 Evidence ID。",
    )
    invalid_evidence_refs: list[str] = Field(
        default_factory=list,
        description="未通过校验且不会写入 Registry 的 Evidence ID。",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Evidence 无效或不足的稳定原因码。",
    )


class ResearchTaskSubQuestionResult(BaseModel):
    """Research Worker 的执行结果；不直接决定 Requirement 状态。"""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(description="对应的正式 Research SubQuestion ID。")
    status: ResearchSubQuestionStatus = Field(description="Worker 自身执行状态。")
    answer: str | None = Field(default=None, description="Worker 生成的受限子问题回答。")
    attempt_count: int = Field(ge=0, description="Worker 已执行的研究尝试次数。")
    tool_calls: list[AgentTaskToolCallTrace] = Field(
        default_factory=list,
        description="当前子问题的结构化工具调用轨迹。",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="本结果引用的、已经写入唯一 Registry 的 Evidence ID。",
    )
    evidence_validation: AgentTaskSubQuestionEvidenceValidation | None = Field(
        default=None,
        description="Evidence 合法性校验结果；尚未合并 Wave 时为空。",
    )
    warnings: list[str] = Field(default_factory=list, description="影响答案完整性的限制说明。")
    error_code: str | None = Field(default=None, description="Worker 失败时的稳定错误码。")
    error_message: str | None = Field(default=None, description="经过清洗的 Worker 失败说明。")


class AgentTaskEvidenceRef(BaseModel):
    """Registry 中可恢复、可去重的 Typed Evidence。"""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="稳定且在当前 TaskPlan 内唯一的 Evidence ID。")
    evidence_type: AgentTaskEvidenceType = Field(description="证据结构类型。")
    source_type: AgentTaskExternalSourceType | None = Field(
        default=None,
        description="服务端 Tool 映射的外部来源；派生证据必须为空。",
    )
    sub_question_id: str = Field(description="产生该证据的正式 Research SubQuestion ID。")
    reference_id: str | None = Field(
        default=None,
        description="Chunk、Web 结果、query_id 或派生 SubQuestion Result 的稳定引用。",
    )
    url: str | None = Field(default=None, description="仅公开 Web citation 使用的 HTTP(S) URL。")
    query_id: str | None = Field(default=None, description="仅 SQL 查询证据使用的真实 query_id。")
    dependency_sub_question_ids: list[str] = Field(
        default_factory=list,
        description="仅派生证据使用的前置 SubQuestion ID。",
    )
    provided_attributes: list[str] = Field(
        default_factory=list,
        description="仅 SQL Evidence 使用的真实查询返回逻辑字段。",
    )

    @model_validator(mode="after")
    def validate_type_fields(self) -> AgentTaskEvidenceRef:
        self.dependency_sub_question_ids = list(dict.fromkeys(self.dependency_sub_question_ids))
        self.provided_attributes = list(
            dict.fromkeys(item.strip().lower() for item in self.provided_attributes if item.strip())
        )
        if self.evidence_type == "knowledge_chunk":
            if self.source_type != "knowledge_retrieval" or not self.reference_id:
                raise ValueError("knowledge_chunk 需要 knowledge_retrieval 和 reference_id")
            if self.url or self.query_id or self.dependency_sub_question_ids or self.provided_attributes:
                raise ValueError("knowledge_chunk 携带了不允许的字段")
        elif self.evidence_type == "web_citation":
            parsed = urlparse(self.url or "")
            if self.source_type != "web_search" or not self.reference_id:
                raise ValueError("web_citation 需要 web_search 和 reference_id")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("web_citation URL 必须是合法 HTTP(S) URL")
            if self.query_id or self.dependency_sub_question_ids or self.provided_attributes:
                raise ValueError("web_citation 携带了不允许的字段")
        elif self.evidence_type == "sql_query_result":
            if self.source_type != "nl2sql_query" or not self.query_id:
                raise ValueError("sql_query_result 需要 nl2sql_query 和 query_id")
            if self.reference_id != self.query_id:
                raise ValueError("sql_query_result reference_id 必须等于 query_id")
            if self.url or self.dependency_sub_question_ids:
                raise ValueError("sql_query_result 携带了不允许的字段")
        else:
            if self.source_type is not None or not self.reference_id:
                raise ValueError("derived_synthesis source_type 必须为空且 reference_id 必填")
            if not self.dependency_sub_question_ids:
                raise ValueError("derived_synthesis 必须引用前置 SubQuestion")
            if self.url or self.query_id or self.provided_attributes:
                raise ValueError("derived_synthesis 携带了不允许的字段")
        return self


class AgentTaskEvidenceRegistry(BaseModel):
    """Research TaskPlan 内 Typed Evidence 的唯一持久化事实源。"""

    model_config = ConfigDict(extra="forbid")

    evidence_by_id: dict[str, AgentTaskEvidenceRef] = Field(
        default_factory=dict,
        description="按 Evidence ID 保存完整 EvidenceRef 的唯一映射。",
    )


class AgentTaskRequirementEvidenceStatus(BaseModel):
    """Aggregator 对一个 Requirement 的当前确定性判断。"""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(description="对应的 Requirement ID。")
    status: RequirementEvidenceStatus = Field(description="Requirement 当前证据状态。")
    satisfied_source_types: list[AgentTaskExternalSourceType] = Field(
        default_factory=list,
        description="已经达到 ExpectedEvidence 阈值的外部来源。",
    )
    missing_source_types: list[AgentTaskExternalSourceType] = Field(
        default_factory=list,
        description="尚未达到证据契约的外部来源。",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="参与本次 Requirement 判断的合法 Evidence ID。",
    )
    covering_sub_question_ids: list[str] = Field(
        default_factory=list,
        description="声明覆盖该 Requirement 的正式 SubQuestion ID。",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="证据不足或失败的稳定原因码。",
    )


class AgentTaskPlanValidationIssue(BaseModel):
    """后端确定性校验发现的结构、来源或可执行性问题。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="确定性校验问题码。")
    message: str = Field(description="经过清洗的校验问题说明。")
    requirement_ids: list[str] = Field(default_factory=list, description="受影响的 Requirement ID。")
    sub_question_ids: list[str] = Field(default_factory=list, description="受影响的 SubQuestion ID。")
    severity: Literal["warning", "error"] = Field(description="warning 可保存，error 必须阻止计划。")


class AgentTaskPlanReviewerFinding(BaseModel):
    """Reviewer 发现的语义质量问题及最终解决状态。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Reviewer 语义发现码。")
    message: str = Field(description="经过清洗的 Reviewer 发现说明。")
    requirement_ids: list[str] = Field(default_factory=list, description="受影响的 Requirement ID。")
    sub_question_ids: list[str] = Field(default_factory=list, description="受影响的 SubQuestion ID。")
    severity: Literal["warning", "error"] = Field(description="发现的严重程度。")
    status: Literal["detected", "resolved", "remaining"] = Field(
        description="本次发现尚未处理、已修复或最终仍存在。"
    )


class AgentTaskPlanQualityChecks(BaseModel):
    """Reviewer 使用的可解释 pass/fail 检查项。"""

    model_config = ConfigDict(extra="forbid")

    requirement_coverage: Literal["pass", "fail"] = Field(description="用户需求是否完整覆盖。")
    source_alignment: Literal["pass", "fail"] = Field(description="来源和完成策略是否符合用户原意。")
    semantic_alignment: Literal["pass", "fail"] = Field(description="计划是否保持 resolved query 语义。")
    dependency_quality: Literal["pass", "fail"] = Field(description="依赖是否能支撑综合结论。")
    executability: Literal["pass", "fail"] = Field(description="计划是否能由当前 Tool 和字段执行。")
    completion_policy_alignment: Literal["pass", "fail"] = Field(
        description="strict/allow_partial 是否符合用户的完整性要求。"
    )


class AgentTaskPlanReviewDecision(BaseModel):
    """Reviewer 单次调用的临时决策，不直接持久化 rejected 计划。"""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accepted", "revised", "rejected"] = Field(description="Reviewer 临时结论。")
    checks: AgentTaskPlanQualityChecks = Field(description="结构化质量检查结果。")
    reviewer_findings: list[AgentTaskPlanReviewerFinding] = Field(
        default_factory=list,
        description="Reviewer 本次发现及处理状态。",
    )
    revision_summary: str | None = Field(default=None, description="修订内容摘要；未修订时为空。")
    revised_requirements: list[AgentTaskRequirement] | None = Field(
        default=None,
        description="revised 时返回的完整 Requirement 集合。",
    )
    revised_sub_questions: list[ResearchTaskSubQuestionCandidate] | None = Field(
        default=None,
        description="revised 时返回的完整 SubQuestion Candidate 集合。",
    )

    @model_validator(mode="after")
    def validate_decision_state(self) -> AgentTaskPlanReviewDecision:
        if self.verdict in {"accepted", "revised"} and any(
            value == "fail" for value in self.checks.model_dump().values()
        ):
            raise ValueError("accepted/revised 的最终质量检查必须全部通过")
        remaining_errors = [
            item
            for item in self.reviewer_findings
            if item.severity == "error" and item.status in {"detected", "remaining"}
        ]
        if self.verdict == "revised":
            if self.revised_requirements is None or self.revised_sub_questions is None:
                raise ValueError("revised 必须返回完整 Requirements 和 SubQuestions")
            if remaining_errors:
                raise ValueError("revised 不允许保留未解决 error")
        elif self.revised_requirements is not None or self.revised_sub_questions is not None:
            raise ValueError("只有 revised 可以返回修订后的计划")
        if self.verdict == "accepted" and remaining_errors:
            raise ValueError("accepted 不允许 detected/remaining error")
        if self.verdict == "rejected" and not any(
            item.severity == "error" and item.status == "remaining"
            for item in self.reviewer_findings
        ):
            raise ValueError("rejected 至少需要一个 remaining error")
        return self


class AgentTaskPlanQualityReview(BaseModel):
    """只保存 accepted/revised 有效 TaskPlan 的最终评审结果。"""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accepted", "revised"] = Field(description="最终有效计划的 Reviewer 结论。")
    checks: AgentTaskPlanQualityChecks = Field(description="最终质量检查结果。")
    reviewer_findings: list[AgentTaskPlanReviewerFinding] = Field(
        default_factory=list,
        description="Reviewer 语义发现及其最终解决状态。",
    )
    revision_summary: str | None = Field(default=None, description="一次修订的摘要；未修订时为空。")
    revision_count: Literal[0, 1] = Field(description="Reviewer 实际修订次数。")
    initial_validation_findings: list[AgentTaskPlanValidationIssue] = Field(
        default_factory=list,
        description="Candidate 第一次确定性校验发现的问题历史。",
    )

    @model_validator(mode="after")
    def validate_persisted_review(self) -> AgentTaskPlanQualityReview:
        if any(value == "fail" for value in self.checks.model_dump().values()):
            raise ValueError("有效 TaskPlan 的最终质量检查必须全部通过")
        if any(
            item.severity == "error" and item.status != "resolved"
            for item in self.reviewer_findings
        ):
            raise ValueError("有效 TaskPlan 不允许未解决的 Reviewer error")
        if (self.verdict == "accepted" and self.revision_count != 0) or (
            self.verdict == "revised" and self.revision_count != 1
        ):
            raise ValueError("verdict 与 revision_count 不一致")
        return self


class AgentTaskPlannerCandidate(BaseModel):
    """Planner 唯一允许输出的 Research 规划内容。"""

    model_config = ConfigDict(extra="forbid")

    requirements: list[AgentTaskRequirement] = Field(description="从 resolved query 拆出的原子需求。")
    sub_questions: list[ResearchTaskSubQuestionCandidate] = Field(
        description="为 Requirements 提供证据的子问题候选。"
    )


class AgentTaskCapabilitySnapshot(BaseModel):
    """计划创建时的非敏感能力摘要，不替代确认时重新鉴权。"""

    model_config = ConfigDict(extra="forbid")

    available_source_types: list[AgentTaskExternalSourceType] = Field(description="当前可用于计划的来源类型。")
    web_direct_allowed: bool = Field(description="当前请求是否允许明确 direct Web。")
    web_fallback_allowed: bool = Field(description="知识库证据不足时是否允许 Web fallback。")
    knowledge_retrieval_available: bool = Field(description="当前用户和请求是否可执行知识库检索。")
    nl2sql_query_available: bool = Field(description="当前用户和请求是否可执行绑定 Dataset 查询。")
    dataset_id: str | None = Field(default=None, description="内部绑定 Dataset ID；公开 View 不返回。")
    dataset_name: str | None = Field(default=None, description="非敏感 Dataset 展示名称。")
    dataset_domain: str | None = Field(default=None, description="非敏感 Dataset 业务领域。")
    allowed_dataset_views: list[str] = Field(
        default_factory=list,
        description="供字段校验使用的白名单逻辑视图；公开 View 不返回。",
    )
    allowed_dataset_fields: list[str] = Field(
        default_factory=list,
        description="供 required_attributes 校验使用的白名单逻辑字段。",
    )
    dataset_schema_context: str | None = Field(
        default=None,
        description="仅非敏感 Dataset 的白名单 Schema、COMMENT 和关系上下文；公开 View 不返回。",
    )
    max_requirements: int = Field(ge=1, description="单计划允许的 Requirement 上限。")
    max_sub_questions: int = Field(ge=1, description="单计划允许的 SubQuestion 上限。")


class ModelPlanningContext(BaseModel):
    """Planner 和 Reviewer 可见的清洗后能力上下文。"""

    model_config = ConfigDict(extra="forbid")

    available_source_types: list[AgentTaskExternalSourceType] = Field(
        description="模型可选择的外部来源类型。"
    )
    dataset_name: str | None = Field(default=None, description="非敏感 Dataset 展示名称。")
    dataset_domain: str | None = Field(default=None, description="非敏感 Dataset 业务领域。")
    dataset_schema_context: str | None = Field(
        default=None,
        description="被标记为不可信业务数据的白名单 Schema、COMMENT、关系和同义词。",
    )
    web_direct_allowed: bool = Field(description="是否允许明确 Web SubQuestion。")
    web_fallback_allowed: bool = Field(description="知识库不足时是否允许 Web fallback。")
    max_requirements: int = Field(ge=1, description="Planner 可生成的 Requirement 上限。")
    max_sub_questions: int = Field(ge=1, description="Planner 可生成的 SubQuestion 上限。")


class InternalPlanningContext(BaseModel):
    """服务端规划上下文；权限事实不得直接序列化到模型 Prompt。"""

    model_config = ConfigDict(extra="forbid")

    request: ResolvedPlanningRequest = Field(description="统一的解析后规划请求。")
    capability_snapshot: AgentTaskCapabilitySnapshot = Field(description="当前可信能力摘要。")
    model_context: ModelPlanningContext = Field(description="允许发送给 Planner/Reviewer 的清洗后上下文。")


class ResearchTaskPolicy(BaseModel):
    """Research TaskPlan 创建时冻结的非授权执行参数。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["vector", "keyword", "hybrid"] = Field(description="知识库检索模式。")
    top_k: int = Field(ge=1, le=20, description="每次检索最终保留的文档数量。")
    candidate_k: int | None = Field(default=None, ge=1, le=50, description="rerank 前候选数量。")
    min_score: float = Field(ge=0.0, le=1.0, description="知识库证据最低分数。")
    source_path: str | None = Field(default=None, description="限定知识库源路径；为空表示不限定。")
    section_path: list[str] = Field(default_factory=list, description="限定章节路径；空列表表示不限定。")
    dataset_id: str | None = Field(default=None, description="服务端绑定 Dataset ID。")
    nl2sql_action: Literal["query"] | None = Field(default=None, description="Research 允许的 NL2SQL 动作。")
    allow_direct_web: bool = Field(description="用户请求是否允许明确 Web 子任务。")
    allow_web_fallback: bool = Field(description="知识库不足时是否允许升级 Web。")


class ResearchWorkerProgress(BaseModel):
    """一个正式 Research SubQuestion 的公开执行进度。"""

    model_config = ConfigDict(extra="forbid")

    status: ResearchSubQuestionStatus = Field(default="pending", description="Worker 当前执行状态。")
    wave: int = Field(default=0, ge=0, description="Worker 所属依赖波次。")
    attempt: int = Field(default=0, ge=0, description="当前研究尝试次数。")
    error_code: str | None = Field(default=None, description="Worker 当前错误码。")


class ResearchProgressEvent(BaseModel):
    """可恢复的 Research 执行进度事件。"""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(description="结构化进度事件名。")
    sub_question_id: str | None = Field(default=None, description="相关 SubQuestion ID。")
    wave: int | None = Field(default=None, ge=0, description="相关依赖波次。")
    status: str | None = Field(default=None, description="事件对应的状态。")
    reason_code: str | None = Field(default=None, description="事件对应的稳定原因码。")


class ResearchTaskProgress(BaseModel):
    """Research TaskPlan 的结构化进度快照。"""

    model_config = ConfigDict(extra="forbid")

    current_wave: int = Field(default=0, ge=0, description="最近已启动的依赖波次。")
    workers: dict[str, ResearchWorkerProgress] = Field(default_factory=dict, description="按 SubQuestion ID 保存的 Worker 进度。")
    events: list[ResearchProgressEvent] = Field(default_factory=list, description="按发生顺序保存的有限进度事件。")


class ResearchTaskFinalOutput(BaseModel):
    """通过 Output Guard 后才能持久化的最终研究输出。"""

    model_config = ConfigDict(extra="forbid")

    answer: str | None = Field(default=None, description="经过 Output Guard 的安全最终答案。")
    included_requirement_ids: list[str] = Field(default_factory=list, description="最终答案实际综合的 Requirement ID。")
    evidence_ids: list[str] = Field(default_factory=list, description="最终答案实际使用的合法 Evidence ID。")
    used_tools: list[str] = Field(default_factory=list, description="服务端记录的实际成功 Tool 名称。")
    warnings: list[str] = Field(default_factory=list, description="部分完成和输出安全限制。")
    guard_action: Literal["allow", "sanitize", "block"] = Field(description="Output Guard 对最终答案的处理动作。")
    guard_reason_codes: list[str] = Field(default_factory=list, description="Output Guard 的安全原因码。")
    completed_at: datetime = Field(description="最终输出完成时间。")


class ResearchTaskPlan(BaseModel):
    """问题拆解研究链路唯一权威的 TaskPlan v2 Schema。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = Field(default=2, description="Research TaskPlan Schema 版本。")
    task_plan_id: str = Field(description="服务端生成的 Research TaskPlan 唯一 ID。")
    task_kind: Literal["question_decomposition"] = Field(default="question_decomposition", description="服务端绑定的研究任务类型。")
    task_type: Literal["analysis"] = Field(default="analysis", description="兼容展示类型，不参与 Router 决策。")
    user_id: str = Field(description="创建计划的认证用户 ID。")
    original_query: str = Field(description="用户当前原始问题，仅保存在内部模型。")
    source_query: str = Field(description="服务端绑定的 resolved query。")
    objective: str = Field(description="服务端从 resolved query 派生的研究目标。")
    final_synthesis_instruction: str = Field(description="服务端生成的最终综合约束。")
    requirements: list[AgentTaskRequirement] = Field(description="通过质量门禁的原子需求。")
    sub_questions: list[ResearchTaskSubQuestion] = Field(description="通过校验并由服务端补全策略的正式子问题。")
    quality_review: AgentTaskPlanQualityReview = Field(description="最终 Reviewer 质量评审。")
    validation_issues: list[AgentTaskPlanValidationIssue] = Field(default_factory=list, description="Final Validation 后允许保存的 warning。")
    capability_snapshot: AgentTaskCapabilitySnapshot = Field(description="计划创建时的非敏感能力摘要。")
    research_policy: ResearchTaskPolicy = Field(description="服务端冻结的非授权研究参数。")
    progress: ResearchTaskProgress = Field(default_factory=ResearchTaskProgress, description="结构化执行进度。")
    sub_question_results: list[ResearchTaskSubQuestionResult] = Field(default_factory=list, description="已原子提交的子问题结果。")
    evidence_registry: AgentTaskEvidenceRegistry = Field(default_factory=AgentTaskEvidenceRegistry, description="完整 Typed Evidence 唯一事实来源。")
    requirement_evidence_statuses: list[AgentTaskRequirementEvidenceStatus] = Field(default_factory=list, description="Aggregator 计算的 Requirement 状态。")
    status: AgentTaskPlanStatus = Field(description="Research TaskPlan 生命周期状态。")
    final_output: ResearchTaskFinalOutput | None = Field(default=None, description="通过 Output Guard 的最终输出。")
    created_at: datetime = Field(description="TaskPlan 创建时间。")
    updated_at: datetime = Field(description="最近一次成功持久化时间。")
    error_code: str | None = Field(default=None, description="TaskPlan 失败时的稳定错误码。")
    error_message: str | None = Field(default=None, description="经过清洗的失败说明。")


class CapabilitySnapshotPublicView(BaseModel):
    """只暴露任务依赖的非敏感能力事实。"""

    model_config = ConfigDict(extra="forbid")

    available_source_types: list[AgentTaskExternalSourceType] = Field(description="计划可使用的公开来源类型。")
    web_direct_allowed: bool = Field(description="计划创建时是否允许 direct Web。")
    web_fallback_allowed: bool = Field(description="计划创建时是否允许 Web fallback。")
    knowledge_retrieval_available: bool = Field(description="知识库检索是否可用。")
    nl2sql_query_available: bool = Field(description="绑定 Dataset 的 NL2SQL 是否可用。")
    dataset_name: str | None = Field(default=None, description="非敏感 Dataset 展示名称。")
    dataset_domain: str | None = Field(default=None, description="非敏感 Dataset 业务领域。")


class AgentTaskEvidencePublicView(BaseModel):
    """Evidence Registry 中允许返回给当前任务拥有者的字段。"""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Evidence 稳定 ID。")
    evidence_type: AgentTaskEvidenceType = Field(description="Evidence 类型。")
    source_type: AgentTaskExternalSourceType | None = Field(default=None, description="外部来源类型；派生证据为空。")
    sub_question_id: str = Field(description="产生 Evidence 的 SubQuestion ID。")
    reference_id: str | None = Field(default=None, description="公开安全的证据引用。")
    url: str | None = Field(default=None, description="公开 Web citation URL。")
    query_id: str | None = Field(default=None, description="NL2SQL 查询审计 ID。")


class ResearchTaskSubQuestionResultPublicView(BaseModel):
    """隐藏 Tool 参数和原始输出后的 Worker 结果。"""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(description="对应 SubQuestion ID。")
    status: ResearchSubQuestionStatus = Field(description="Worker 执行状态。")
    answer: str | None = Field(default=None, description="经过边界控制的子问题回答。")
    attempt_count: int = Field(description="执行尝试次数。")
    evidence_ids: list[str] = Field(description="合法 Evidence ID。")
    warnings: list[str] = Field(description="结果限制说明。")
    error_code: str | None = Field(default=None, description="稳定错误码。")


class ResearchTaskPlanPublicView(BaseModel):
    """Research TaskPlan v2 的 API/SSE 安全公开视图。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = Field(description="Research TaskPlan Schema 版本。")
    task_plan_id: str = Field(description="TaskPlan ID。")
    task_kind: Literal["question_decomposition"] = Field(description="研究任务类型。")
    task_type: Literal["analysis"] = Field(description="展示任务类型。")
    source_query: str = Field(description="服务端解析后的当前任务语义。")
    objective: str = Field(description="研究目标。")
    final_synthesis_instruction: str = Field(description="最终综合约束。")
    requirements: list[AgentTaskRequirement] = Field(description="原子需求和证据契约。")
    sub_questions: list[ResearchTaskSubQuestion] = Field(description="正式子问题和 WebUsage。")
    quality_review: AgentTaskPlanQualityReview = Field(description="质量评审和初始校验历史。")
    validation_issues: list[AgentTaskPlanValidationIssue] = Field(description="最终仍保留的 warning。")
    capability_snapshot: CapabilitySnapshotPublicView = Field(description="非敏感能力公开摘要。")
    progress: ResearchTaskProgress = Field(description="结构化执行进度。")
    sub_question_results: list[ResearchTaskSubQuestionResultPublicView] = Field(description="公开安全的 Worker 结果。")
    evidence: list[AgentTaskEvidencePublicView] = Field(description="公开安全的 Evidence 引用。")
    requirement_evidence_statuses: list[AgentTaskRequirementEvidenceStatus] = Field(description="Requirement 聚合状态。")
    status: AgentTaskPlanStatus = Field(description="TaskPlan 生命周期状态。")
    final_output: ResearchTaskFinalOutput | None = Field(default=None, description="通过 Output Guard 的最终输出。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")
    error_code: str | None = Field(default=None, description="失败错误码。")
    error_message: str | None = Field(default=None, description="经过清洗的失败说明。")


def build_research_task_plan_public_view(plan: ResearchTaskPlan) -> ResearchTaskPlanPublicView:
    """从内部 TaskPlan 构造不会泄露 ACL、Scope、结果行或 Tool 参数的视图。"""

    capability = plan.capability_snapshot
    return ResearchTaskPlanPublicView(
        schema_version=plan.schema_version,
        task_plan_id=plan.task_plan_id,
        task_kind=plan.task_kind,
        task_type=plan.task_type,
        source_query=plan.source_query,
        objective=plan.objective,
        final_synthesis_instruction=plan.final_synthesis_instruction,
        requirements=plan.requirements,
        sub_questions=plan.sub_questions,
        quality_review=plan.quality_review,
        validation_issues=plan.validation_issues,
        capability_snapshot=CapabilitySnapshotPublicView(
            available_source_types=capability.available_source_types,
            web_direct_allowed=capability.web_direct_allowed,
            web_fallback_allowed=capability.web_fallback_allowed,
            knowledge_retrieval_available=capability.knowledge_retrieval_available,
            nl2sql_query_available=capability.nl2sql_query_available,
            dataset_name=capability.dataset_name,
            dataset_domain=capability.dataset_domain,
        ),
        progress=plan.progress,
        sub_question_results=[
            ResearchTaskSubQuestionResultPublicView(
                sub_question_id=item.sub_question_id,
                status=item.status,
                answer=item.answer,
                attempt_count=item.attempt_count,
                evidence_ids=item.evidence_ids,
                warnings=item.warnings,
                error_code=item.error_code,
            )
            for item in plan.sub_question_results
        ],
        evidence=[
            AgentTaskEvidencePublicView(
                evidence_id=item.evidence_id,
                evidence_type=item.evidence_type,
                source_type=item.source_type,
                sub_question_id=item.sub_question_id,
                reference_id=item.reference_id,
                url=item.url,
                query_id=item.query_id,
            )
            for item in plan.evidence_registry.evidence_by_id.values()
        ],
        requirement_evidence_statuses=plan.requirement_evidence_statuses,
        status=plan.status,
        final_output=plan.final_output,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        error_code=plan.error_code,
        error_message=plan.error_message,
    )


__all__ = [
    name
    for name in globals()
    if name.startswith(
        (
            "AgentTask",
            "Capability",
            "Research",
            "Requirement",
            "Resolved",
            "Frozen",
            "WebUsage",
        )
    )
] + ["build_research_task_plan_public_view"]
