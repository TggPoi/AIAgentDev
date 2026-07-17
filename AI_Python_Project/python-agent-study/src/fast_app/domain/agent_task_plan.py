from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentTaskKind = Literal[
    "knowledge_document_management",
    "question_decomposition",
]
AgentTaskType = Literal["qa", "comparison", "report_generation", "analysis", "unknown"]
AgentTaskInformationSourceHint = Literal["knowledge_retrieval", "web_search", "none"]
AgentTaskSubQuestionResultStatus = Literal["completed", "partial", "failed", "skipped"]
AgentTaskToolCallStatus = Literal["completed", "failed"]
AgentResearchWebPolicy = Literal["disabled", "fallback", "required"]


class AgentTaskPlanStatus(StrEnum):
    """任务整体状态：LLM 多步骤任务计划状态。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentToolStepStatus(StrEnum):
    """TaskPlan 中单个工具步骤的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentToolStep(BaseModel):
    """Agent 多步骤任务中的一个工具步骤。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="步骤唯一 ID，当前 task plan 内稳定。")
    tool_name: str = Field(description="本步骤调用的工具名。")
    status: AgentToolStepStatus = Field(
        default=AgentToolStepStatus.PENDING,
        description="本步骤当前执行状态。",
    )
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用输入，必须是 JSON 可序列化结构。",
    )
    output: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用输出摘要，供后续步骤和 React 展示使用。",
    )
    risk_level: str = Field(default="low", description="步骤风险等级。")
    requires_confirmation: bool = Field(
        default=False,
        description="该步骤是否需要人工确认后才能真实执行。",
    )
    error: str | None = Field(default=None, description="步骤失败原因。")


class AgentTaskSubQuestion(BaseModel):
    """复杂问题拆解后的一个待回答子问题，不表示工具执行步骤。"""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(description="子问题唯一 ID，当前 task plan 内稳定。")
    order: int = Field(description="子问题在最终推理中的建议处理顺序。")
    question: str = Field(description="真正需要被回答的子问题，不能是执行动作指令。")
    purpose: str = Field(description="拆出该子问题的目的。")
    depends_on: list[str] = Field(
        default_factory=list,
        description="该子问题依赖的前置 sub_question_id 列表。",
    )
    information_source_hint: AgentTaskInformationSourceHint = Field(
        description="建议的信息来源；本字段不代表本阶段会真实调用工具。",
    )
    reason: str = Field(description="为什么该子问题有助于回答原始复杂问题。")
    expected_evidence: str | None = Field(
        default=None,
        description="理想情况下回答该子问题需要的证据类型。",
    )


class AgentResearchPolicy(BaseModel):
    """跨确认请求保存的研究参数；权限与认证状态必须在执行时重新读取。"""

    model_config = ConfigDict(extra="forbid")

    # Worker 执行本计划时使用的检索模式。
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    # 每次检索最终保留的文档数量。
    top_k: int = Field(default=5, ge=1, le=20)
    # rerank 前的候选文档数量；None 表示沿用服务端默认值。
    candidate_k: int | None = Field(default=None, ge=1, le=50)
    # 检索结果被视为可用证据前必须达到的最低分数。
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # 将研究范围限定到某个知识库源文件；None 表示不按文件收窄。
    source_path: str | None = None
    # 将研究范围限定到文档标题层级路径；空列表表示不按章节过滤。
    section_path: list[str] = Field(default_factory=list)
    # 本计划是否禁止、允许兜底或必须执行联网研究。
    web_policy: AgentResearchWebPolicy = "disabled"


class ResearchEvidenceEvaluation(BaseModel):
    """Evaluator 对一个 Worker 当前证据充分性的结构化判断。"""

    model_config = ConfigDict(extra="forbid")
    # 证据总体结论：足够、部分覆盖、不足或互相冲突。
    verdict: Literal["sufficient", "partial", "insufficient", "conflict"]
    # Evaluator 对当前总体结论的置信度。
    confidence: float = Field(ge=0.0, le=1.0)
    # 当前证据与子问题语义是否相关的评分。
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    # 当前证据覆盖子问题所需要点的程度。
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    # 当前证据来源的可信程度评分。
    authority: float = Field(default=0.0, ge=0.0, le=1.0)
    # 回答是否必须补充近期或实时信息，避免只依赖旧知识库。
    freshness_required: bool = False
    # 尚未被现有证据覆盖的具体问题点。
    missing_points: list[str] = Field(default_factory=list)
    # Executor 下一次应采取的研究动作，不直接等同于立即执行的工具调用。
    recommended_action: Literal[
        "accept",
        "rewrite_local_query",
        "search_web",
        "combine_local_and_web",
        "clarify",
        "stop_with_limitation",
    ] = "stop_with_limitation"
    # 供 trace、前端和后续排查阅读的评估理由。
    reason: str = ""


class AgentTaskToolCallTrace(BaseModel):
    """子问题执行过程中的一次工具调用轨迹。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(description="工具调用唯一 ID，当前子问题内稳定。")
    round: int = Field(description="该工具调用在当前子问题 tool loop 中的轮次。")
    tool_name: str = Field(description="实际调用的工具名。")
    tool_input: dict[str, Any] = Field(
        default_factory=dict,
        description="传给工具的结构化参数。",
    )
    tool_output: dict[str, Any] = Field(
        default_factory=dict,
        description="工具输出摘要，必须保持 JSON 可序列化。",
    )
    status: AgentTaskToolCallStatus = Field(description="本次工具调用状态。")
    error: str | None = Field(default=None, description="工具调用失败原因。")
    reason: str = Field(default="", description="LLM 选择该工具的原因。")


class AgentTaskSubQuestionResult(BaseModel):
    """一个子问题的执行结果，不反写到规划字段。"""

    model_config = ConfigDict(extra="forbid")

    sub_question_id: str = Field(description="对应的子问题 ID。")
    question: str = Field(description="实际被回答的子问题。")
    selected_tool: str = Field(description="LLM 选择的工具名；none 表示不调用工具。")
    tool_input: dict[str, Any] = Field(
        default_factory=dict,
        description="传给工具的结构化参数。",
    )
    tool_output: dict[str, Any] = Field(
        default_factory=dict,
        description="工具输出摘要，供后续整合和前端展示。",
    )
    tool_calls: list[AgentTaskToolCallTrace] = Field(
        default_factory=list,
        description="该子问题完整的多轮工具调用轨迹。",
    )
    answer: str = Field(default="", description="该子问题的回答。")
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="支撑该子问题回答的证据摘要。",
    )
    status: AgentTaskSubQuestionResultStatus = Field(description="子问题执行状态。")
    error: str | None = Field(default=None, description="子问题失败原因。")
    # 本子问题已经执行的研究尝试次数；因依赖失败跳过时为 0。
    attempt_count: int = Field(default=1, ge=0)
    # 每次研究尝试的工具、证据和评估摘要，供恢复、审计和前端展开查看。
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    # 最近一次证据充分性评估；未进入 Evaluator 时为 None。
    evaluation: ResearchEvidenceEvaluation | None = None
    # 合并证据后实际使用的来源类型，例如 knowledge_base 或 web。
    source_types: list[str] = Field(default_factory=list)
    # 虽未必导致失败、但会影响答案完整性或可靠性的提示。
    warnings: list[str] = Field(default_factory=list)


class AgentTaskPlan(BaseModel):
    """LLM 生成的 Agent 多步骤任务计划。"""

    model_config = ConfigDict(extra="forbid")

    # 一个 plan 同时服务两类前端展示：
    # - question_decomposition：展示问题拆解，用户确认后按子问题执行工具循环。
    # - knowledge_document_management：保存原生文档 ToolCall 形成的待确认步骤。
    task_plan_id: str = Field(description="任务计划唯一 ID。")
    task_kind: AgentTaskKind = Field(
        description="任务计划类型；question_decomposition 表达复杂问题拆解并在确认后执行。",
    )
    user_id: str | None = Field(
        default=None,
        description="创建该任务计划的用户 ID，用于查询和审计。",
    )
    original_query: str = Field(description="用户输入的原始复杂问题。")
    objective: str = Field(description="用户最终希望完成的目标。")
    task_type: AgentTaskType = Field(description="复杂问题的任务类型。")
    goal: str = Field(description="兼容字段，语义上等同于 objective。")
    sub_questions: list[AgentTaskSubQuestion] = Field(
        description="复杂问题拆解出的待回答子问题列表，不是执行 TODO list。",
    )
    research_policy: AgentResearchPolicy | None = Field(
        default=None,
        description="问题研究确认后仍需使用的检索参数；不包含权限或认证事实。",
    )
    final_synthesis_instruction: str = Field(
        description="最终如何整合多个子问题答案的说明。",
    )
    source_query: str = Field(
        description="给当前 legacy executor 使用的一次检索 condensed query。",
    )
    target_path: str | None = Field(
        default=None,
        description="报告要保存到的知识库相对路径；纯问题拆解计划为空。",
    )
    report_title: str = Field(default="知识库报告", description="报告标题。")
    status: AgentTaskPlanStatus = Field(
        default=AgentTaskPlanStatus.CREATED,
        description="任务计划整体状态。",
    )
    steps: list[AgentToolStep] = Field(description="顺序执行的工具步骤列表。")
    final_output: dict[str, Any] = Field(
        default_factory=dict,
        description="任务最终输出摘要，例如确认接口或报告长度。",
    )
    created_at: datetime = Field(description="任务计划创建时间。")
    updated_at: datetime = Field(description="任务计划最后更新时间。")
    error: str | None = Field(default=None, description="任务失败原因。")


__all__ = [
    "AgentTaskInformationSourceHint",
    "AgentTaskKind",
    "AgentTaskPlan",
    "AgentTaskPlanStatus",
    "AgentResearchPolicy",
    "AgentResearchWebPolicy",
    "AgentTaskSubQuestion",
    "AgentTaskSubQuestionResult",
    "AgentTaskSubQuestionResultStatus",
    "AgentTaskToolCallStatus",
    "AgentTaskToolCallTrace",
    "AgentTaskType",
    "ResearchEvidenceEvaluation",
    "AgentToolStep",
    "AgentToolStepStatus",
]
