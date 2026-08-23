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
AgentTaskInformationSourceHint = Literal[
    "knowledge_retrieval",
    "nl2sql_query",
    "web_search",
    "none",
]
AgentTaskSubQuestionResultStatus = Literal["completed", "partial", "failed", "skipped"]
AgentTaskToolCallStatus = Literal["completed", "failed"]
AgentResearchWebPolicy = Literal["disabled", "fallback", "required"]
AgentTaskFailurePhase = Literal[
    "preparing_confirmation",
    "executing_confirmed",
]


class AgentTaskPlanStatus(StrEnum):
    """任务整体状态：LLM 多步骤任务计划状态。"""

    CREATED = "created"
    PREPARING_CONFIRMATION = "preparing_confirmation"
    WAITING_CONFIRMATION = "waiting_confirmation"
    EXECUTING_CONFIRMED = "executing_confirmed"
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
        description="建议的信息来源：知识库、已绑定 Dataset、公开网络或无需工具；不代表已执行工具。",
    )
    reason: str = Field(description="为什么该子问题有助于回答原始复杂问题。")
    expected_evidence: str | None = Field(
        default=None,
        description="理想情况下回答该子问题需要的证据类型。",
    )


class AgentResearchPolicy(BaseModel):
    """跨确认请求保存的研究参数；权限与认证状态必须在执行时重新读取。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["vector", "keyword", "hybrid"] = Field(
        default="hybrid",
        description="Worker 执行本计划时使用的本地检索模式。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="每次检索最终保留的文档数量。",
    )
    candidate_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="rerank 前的候选数量；None 表示使用服务端默认值。",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="检索结果被视为可用证据前必须达到的最低分数。",
    )
    source_path: str | None = Field(
        default=None,
        description="限定检索到一个知识库源文件；None 表示不按文件收窄。",
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="限定检索到指定章节层级；空列表表示不按章节过滤。",
    )
    web_policy: AgentResearchWebPolicy = Field(
        default="disabled",
        description="联网策略：禁止、仅证据不足时兜底，或必须联网。",
    )
    dataset_id: str | None = Field(
        default=None,
        description="服务端请求绑定的 NL2SQL Dataset ID；为空表示普通文档或研究任务。",
    )
    nl2sql_action: Literal["query", "report"] | None = Field(
        default=None,
        description="服务端绑定的 Dataset 查询或报告动作；执行和恢复时必须重新鉴权。",
    )


class ResearchEvidenceEvaluation(BaseModel):
    """Evaluator 对一个 Worker 当前证据充分性的结构化判断。"""

    model_config = ConfigDict(extra="forbid")
    verdict: Literal["sufficient", "partial", "insufficient", "conflict"] = Field(
        description="证据总体结论：充分、部分覆盖、不足或相互冲突。"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Evaluator 对 verdict 的置信度，范围 0 到 1。",
    )
    relevance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="当前证据与子问题语义的相关性评分。",
    )
    coverage: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="当前证据覆盖子问题关键点的程度。",
    )
    authority: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="当前证据来源的可信程度评分。",
    )
    freshness_required: bool = Field(
        default=False,
        description="回答是否必须补充近期或实时信息。",
    )
    missing_points: list[str] = Field(
        default_factory=list,
        description="现有证据尚未覆盖、下一轮研究应补齐的具体问题点。",
    )
    recommended_action: Literal[
        "accept",
        "rewrite_local_query",
        "search_web",
        "combine_local_and_web",
        "clarify",
        "stop_with_limitation",
    ] = Field(
        default="stop_with_limitation",
        description="建议的下一步研究动作；Executor 仍会按权限和预算决定是否执行。",
    )
    reason: str = Field(
        default="",
        description="支持当前评估结论和建议动作的简要理由。",
    )


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
    attempt_count: int = Field(
        default=1,
        ge=0,
        description="已执行的研究尝试次数；因依赖失败跳过时为 0。",
    )
    attempts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="各次研究尝试的工具、证据和评估摘要。",
    )
    evaluation: ResearchEvidenceEvaluation | None = Field(
        default=None,
        description="最近一次证据充分性评估；未进入 Evaluator 时为空。",
    )
    source_types: list[str] = Field(
        default_factory=list,
        description="最终证据实际使用的来源类型，例如 knowledge_base 或 web。",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="不一定导致失败但会影响答案完整性或可靠性的提示。",
    )


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
    session_id: str | None = Field(
        default=None,
        max_length=128,
        description="创建该计划的外部会话 ID；旧计划或非会话任务为空。",
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
    failure_phase: AgentTaskFailurePhase | None = Field(
        default=None,
        description=(
            "最近一次 failed 发生前的权威活动阶段；仅由服务端写入，"
            "用于 retry 区分确认前恢复与已确认执行恢复，非 failed 时为空。"
        ),
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
    "AgentTaskFailurePhase",
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
