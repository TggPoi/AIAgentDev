"""TaskPlan confirm-stream 的严格公共事件模型与安全投影。"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError

from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.domain.research_task_plan import ResearchWorkerStage
from fast_app.schemas.rag_chat_schema import RagSource
from fast_app.schemas.rag_stream_schema import RAG_SSE_CONTRACT_VERSION


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_RESEARCH_STATUSES = {
    "pending",
    "running",
    "completed",
    "partial",
    "failed",
    "skipped",
    "retrying",
}
_DOCUMENT_STATUSES = {
    "running",
    "completed",
    "partial",
    "failed",
    "skipped",
}
_RESEARCH_STAGES = {
    "starting",
    "tool_setup",
    "tool_selection",
    "tool_execution",
    "answer_generation",
    "evidence_evaluation",
    "retry_preparation",
    "completed",
}
_RESEARCH_EVENT_NAMES = {
    "sub_question_started",
    "agent_task_research_wave_started",
    "agent_task_research_worker_progress",
    "agent_task_research_worker_timed_out",
    "agent_task_evidence_evaluated",
    "agent_task_sub_question_retrying",
}
_DOCUMENT_EVENT_NAMES = {
    "agent_task_document_supervised",
    "agent_task_document_subagent_started",
    "agent_task_document_subagent_completed",
    "agent_task_document_subagent_failed",
    "agent_task_document_draft_created",
    "agent_task_document_review_completed",
    "agent_task_document_revision_started",
    "agent_task_document_action_prepared",
}


class TaskPlanEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1.0"] = Field(
        description="TaskPlan 公共 SSE 契约版本，当前固定为 1.0。"
    )
    request_id: str | None = Field(
        default=None,
        description="与当前 HTTP 请求和 X-Request-ID 对齐的公开请求关联 ID。",
    )
    task_plan_id: str = Field(
        min_length=1,
        max_length=128,
        description="当前公开事件所属且已经过入口授权的 TaskPlan ID。",
    )


class TaskPlanExecutionStartedData(TaskPlanEventData):
    pass


class TaskPlanStatusData(TaskPlanEventData):
    status: AgentTaskPlanStatus = Field(description="当前持久化 TaskPlan 状态。")


class TaskPlanResearchProgressData(TaskPlanEventData):
    sub_question_id: str | None = Field(
        default=None,
        max_length=128,
        description="研究子问题公开 ID；事件不关联单题时为空。",
    )
    wave: int | None = Field(
        default=None, ge=0, description="研究调度波次；事件不关联波次时为空。"
    )
    status: Literal[
        "pending",
        "running",
        "completed",
        "partial",
        "failed",
        "skipped",
        "retrying",
    ] | None = Field(default=None, description="公开研究工作状态；无状态事实时为空。")
    reason_code: str | None = Field(
        default=None,
        max_length=128,
        description="稳定公开原因码；不存在或不安全时为空。",
    )
    attempt: int | None = Field(
        default=None, ge=0, description="当前研究尝试序号；不适用时为空。"
    )
    stage: ResearchWorkerStage | None = Field(
        default=None, description="当前研究 worker 的稳定公开阶段；不适用时为空。"
    )
    active_operation_count: int = Field(
        default=0,
        ge=0,
        description="活动操作数量；不公开操作名称或参数。",
    )
    tool_call_count: int | None = Field(
        default=None, ge=0, description="已执行工具调用数量；未知时为空。"
    )
    evidence_count: int | None = Field(
        default=None, ge=0, description="当前有效证据数量；未知时为空。"
    )


class TaskPlanSubQuestionCompletedData(TaskPlanEventData):
    sub_question_id: str = Field(
        min_length=1, max_length=128, description="已完成研究子问题的公开 ID。"
    )
    status: Literal["completed", "partial", "failed", "skipped"] = Field(
        description="该子问题的稳定终态。"
    )
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="稳定公开错误码；没有失败或无法安全映射时为空。",
    )
    evidence_count: int = Field(
        default=0, ge=0, description="该子问题关联的公开证据数量。"
    )


class TaskPlanRequirementProgressData(TaskPlanEventData):
    requirement_id: str = Field(
        min_length=1, max_length=128, description="研究证据要求的公开 ID。"
    )
    status: Literal["pending", "partially_satisfied", "satisfied", "failed"] = Field(
        description="证据要求的稳定满足状态。"
    )
    evidence_count: int = Field(
        default=0, ge=0, description="满足该要求的公开证据数量。"
    )
    reason_codes: list[str] = Field(
        default_factory=list, description="经过 allowlist 格式约束的稳定原因码。"
    )


class TaskPlanDocumentProgressData(TaskPlanEventData):
    deliverable_id: str | None = Field(
        default=None, max_length=128, description="文档交付物公开 ID；不适用时为空。"
    )
    step_id: str | None = Field(
        default=None, max_length=128, description="关联 TaskPlan 步骤 ID；不适用时为空。"
    )
    operation: Literal["create", "update", "delete"] | None = Field(
        default=None, description="文档操作类型；事件不关联具体操作时为空。"
    )
    status: Literal["running", "completed", "partial", "failed", "skipped"] | None = Field(
        default=None, description="文档工作流稳定状态；不适用时为空。"
    )
    verdict: Literal["approved", "revision_required", "rejected"] | None = Field(
        default=None, description="文档审查结论；非审查事件为空。"
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="文档审查公开置信度；非审查事件为空。",
    )
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="稳定公开文档工作流错误码；无失败时为空。",
    )
    deliverable_count: int | None = Field(
        default=None, ge=0, description="文档交付物数量；事件未提供时为空。"
    )


class TaskPlanStepData(TaskPlanEventData):
    step_id: str = Field(
        min_length=1, max_length=128, description="已结束 TaskPlan 步骤的公开 ID。"
    )
    tool_name: str = Field(
        min_length=1,
        max_length=128,
        description="该步骤使用的稳定工具名称；不包含参数或输出。",
    )
    status: Literal["completed", "failed"] = Field(description="步骤稳定终态。")
    error_code: str | None = Field(
        default=None,
        max_length=128,
        description="步骤失败的稳定公开错误码；成功时为空。",
    )


class TaskPlanFinalSynthesisData(TaskPlanEventData):
    status: AgentTaskPlanStatus = Field(description="最终合成时的 TaskPlan 状态。")
    used_tool_count: int = Field(
        ge=0, description="最终合成使用的工具数量；不公开工具参数或输出。"
    )
    warning_count: int = Field(ge=0, description="最终合成产生的公开警告数量。")


class TaskPlanSourcesData(TaskPlanEventData):
    sources: list[RagSource] = Field(description="经过公共 RagSource 校验的安全来源列表。")


class TaskPlanAnswerDeltaData(TaskPlanEventData):
    text: str = Field(max_length=20_000, description="已通过输出安全边界的回答增量。")


class TaskPlanGuardData(TaskPlanEventData):
    text: str = Field(max_length=20_000, description="允许展示的脱敏或阻断文本。")
    action: Literal["sanitize", "block"] = Field(description="Prompt Guard 公开处理动作。")
    risk_level: str = Field(max_length=64, description="Prompt Guard 公开风险级别。")
    categories: list[str] = Field(description="经过格式约束的 Prompt Guard 分类码。")
    reason: str = Field(max_length=256, description="允许展示的稳定安全处理原因。")


class TaskPlanDoneData(TaskPlanEventData):
    status: Literal["done"] = Field(description="TaskPlan SSE 正常完成标记。")
    task_status: AgentTaskPlanStatus = Field(description="流结束时的最终 TaskPlan 状态。")


class TaskPlanErrorData(TaskPlanEventData):
    code: str = Field(min_length=1, max_length=128, description="稳定公开错误码。")
    message: Literal["TaskPlan 执行失败"] = Field(description="固定且不回显内部异常的公开错误消息。")
    error_category: Literal["system_error"] = Field(description="TaskPlan 流失败的稳定公开错误分类。")
    trace_id: str | None = Field(
        default=None,
        max_length=128,
        description="允许公开的链路追踪 ID；未提供或不安全时为空。",
    )


class TaskPlanExecutionStartedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["agent_task_execution_started"] = Field(description="TaskPlan 执行开始事件名。")
    data: TaskPlanExecutionStartedData = Field(description="TaskPlan 执行开始的安全公开 payload。")


class TaskPlanStatusFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["agent_task_status"] = Field(description="TaskPlan 状态快照事件名。")
    data: TaskPlanStatusData = Field(description="TaskPlan 状态快照的安全公开 payload。")


class TaskPlanResearchProgressFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal[
        "sub_question_started",
        "agent_task_research_wave_started",
        "agent_task_research_worker_progress",
        "agent_task_research_worker_timed_out",
        "agent_task_evidence_evaluated",
        "agent_task_sub_question_retrying",
    ] = Field(description="Research TaskPlan 公开进度事件名。")
    data: TaskPlanResearchProgressData = Field(description="Research 进度的安全公开 payload。")


class TaskPlanSubQuestionCompletedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["sub_question_completed"] = Field(description="研究子问题完成事件名。")
    data: TaskPlanSubQuestionCompletedData = Field(description="研究子问题完成的安全公开 payload。")


class TaskPlanRequirementProgressFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal[
        "requirement_evidence_updated",
        "requirement_satisfied",
        "requirement_insufficient",
    ] = Field(description="研究证据要求进度事件名。")
    data: TaskPlanRequirementProgressData = Field(description="研究证据要求进度的安全公开 payload。")


class TaskPlanDocumentProgressFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal[
        "agent_task_document_supervised",
        "agent_task_document_subagent_started",
        "agent_task_document_subagent_completed",
        "agent_task_document_subagent_failed",
        "agent_task_document_draft_created",
        "agent_task_document_review_completed",
        "agent_task_document_revision_started",
        "agent_task_document_action_prepared",
    ] = Field(description="Document TaskPlan 公开进度事件名。")
    data: TaskPlanDocumentProgressData = Field(description="Document 进度的安全公开 payload。")


class TaskPlanStepFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["agent_task_step_completed", "agent_task_step_failed"] = Field(
        description="TaskPlan 步骤终态事件名。"
    )
    data: TaskPlanStepData = Field(description="TaskPlan 步骤终态的安全公开 payload。")


class TaskPlanFinalSynthesisFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["agent_task_final_synthesis_completed"] = Field(
        description="TaskPlan 最终合成完成事件名。"
    )
    data: TaskPlanFinalSynthesisData = Field(description="最终合成完成的安全公开 payload。")


class TaskPlanSourcesFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["sources"] = Field(description="TaskPlan 回答来源事件名。")
    data: TaskPlanSourcesData = Field(description="TaskPlan 回答来源的安全公开 payload。")


class TaskPlanAnswerDeltaFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["answer_delta"] = Field(description="TaskPlan 安全回答增量事件名。")
    data: TaskPlanAnswerDeltaData = Field(description="TaskPlan 安全回答增量 payload。")


class TaskPlanGuardFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["guard_sanitized", "guard_blocked"] = Field(
        description="TaskPlan Prompt Guard 处理事件名。"
    )
    data: TaskPlanGuardData = Field(description="Prompt Guard 处理后的安全公开 payload。")


class TaskPlanDoneFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["done"] = Field(description="TaskPlan SSE 正常终止事件名。")
    data: TaskPlanDoneData = Field(description="TaskPlan SSE 正常终止的安全公开 payload。")


class TaskPlanErrorFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["error"] = Field(description="TaskPlan SSE 失败终止事件名。")
    data: TaskPlanErrorData = Field(description="TaskPlan SSE 失败终止的安全公开 payload。")


TaskPlanPublicEvent = Annotated[
    TaskPlanExecutionStartedFrame
    | TaskPlanStatusFrame
    | TaskPlanResearchProgressFrame
    | TaskPlanSubQuestionCompletedFrame
    | TaskPlanRequirementProgressFrame
    | TaskPlanDocumentProgressFrame
    | TaskPlanStepFrame
    | TaskPlanFinalSynthesisFrame
    | TaskPlanSourcesFrame
    | TaskPlanAnswerDeltaFrame
    | TaskPlanGuardFrame
    | TaskPlanDoneFrame
    | TaskPlanErrorFrame,
    Field(discriminator="event"),
]


class TaskPlanPublicEventFrame(RootModel[TaskPlanPublicEvent]):
    """OpenAPI 使用的 TaskPlan 业务事件判别式 union。"""


def project_task_plan_public_event(
    event: str,
    data: object,
    *,
    request_id: str | None,
) -> TaskPlanPublicEventFrame | None:
    """只读取批准字段；未知事件或不安全关键标识直接丢弃。"""

    if not isinstance(data, dict):
        return None
    task_plan_id = _safe_identifier(data.get("task_plan_id"))
    if task_plan_id is None:
        return None
    base = {
        "contract_version": RAG_SSE_CONTRACT_VERSION,
        "request_id": request_id,
        "task_plan_id": task_plan_id,
    }
    payload: dict[str, object]

    if event == "agent_task_execution_started":
        payload = base
    elif event == "agent_task_status":
        status = _task_status(data.get("status"))
        if status is None:
            return None
        payload = {**base, "status": status}
    elif event in _RESEARCH_EVENT_NAMES:
        payload = {
            **base,
            "sub_question_id": _safe_identifier(data.get("sub_question_id")),
            "wave": _safe_count(data.get("wave")),
            "status": _safe_enum(data.get("status"), _RESEARCH_STATUSES),
            "reason_code": _safe_identifier(data.get("reason_code")),
            "attempt": _safe_count(data.get("attempt")),
            "stage": _safe_enum(data.get("stage"), _RESEARCH_STAGES),
            "active_operation_count": _safe_list_count(data.get("active_operations")),
            "tool_call_count": _safe_count(data.get("tool_call_count")),
            "evidence_count": _safe_count(data.get("evidence_count")),
        }
    elif event == "sub_question_completed":
        sub_question_id = _safe_identifier(data.get("sub_question_id"))
        status = _safe_enum(
            data.get("status"), {"completed", "partial", "failed", "skipped"}
        )
        if sub_question_id is None or status is None:
            return None
        payload = {
            **base,
            "sub_question_id": sub_question_id,
            "status": status,
            "error_code": _safe_identifier(data.get("error_code")),
            "evidence_count": _safe_list_count(data.get("evidence_ids")),
        }
    elif event in {
        "requirement_evidence_updated",
        "requirement_satisfied",
        "requirement_insufficient",
    }:
        requirement_id = _safe_identifier(data.get("requirement_id"))
        status = _safe_enum(
            data.get("status"),
            {"pending", "partially_satisfied", "satisfied", "failed"},
        )
        if requirement_id is None or status is None:
            return None
        payload = {
            **base,
            "requirement_id": requirement_id,
            "status": status,
            "evidence_count": _safe_list_count(data.get("evidence_ids")),
            "reason_codes": _safe_codes(data.get("reason_codes")),
        }
    elif event in _DOCUMENT_EVENT_NAMES:
        payload = {
            **base,
            "deliverable_id": _safe_identifier(data.get("deliverable_id")),
            "step_id": _safe_identifier(data.get("step_id")),
            "operation": _safe_enum(data.get("operation"), {"create", "update", "delete"}),
            "status": _safe_enum(data.get("status"), _DOCUMENT_STATUSES),
            "verdict": _safe_enum(
                data.get("verdict"), {"approved", "revision_required", "rejected"}
            ),
            "confidence": _safe_confidence(data.get("confidence")),
            "error_code": _safe_identifier(data.get("error_code")),
            "deliverable_count": _safe_count(data.get("deliverable_count")),
        }
    elif event in {"agent_task_step_completed", "agent_task_step_failed"}:
        step_id = _safe_identifier(data.get("step_id"))
        tool_name = _safe_identifier(data.get("tool_name"))
        status = _safe_enum(data.get("status"), {"completed", "failed"})
        if step_id is None or tool_name is None or status is None:
            return None
        payload = {
            **base,
            "step_id": step_id,
            "tool_name": tool_name,
            "status": status,
            "error_code": (
                _safe_identifier(data.get("error_code"))
                or ("AGENT_TASK_STEP_FAILED" if status == "failed" else None)
            ),
        }
    elif event == "agent_task_final_synthesis_completed":
        status = _task_status(data.get("status"))
        if status is None:
            return None
        payload = {
            **base,
            "status": status,
            "used_tool_count": _safe_list_count(data.get("used_tools")),
            "warning_count": _safe_list_count(data.get("warnings")),
        }
    elif event == "sources":
        payload = {**base, "sources": _safe_sources(data.get("sources"))}
    elif event == "answer_delta":
        text = _safe_text(data.get("text"), 20_000)
        if text is None:
            return None
        payload = {**base, "text": text}
    elif event in {"guard_sanitized", "guard_blocked"}:
        text = _safe_text(data.get("text"), 20_000)
        action = _safe_enum(data.get("action"), {"sanitize", "block"})
        if text is None or action is None:
            return None
        payload = {
            **base,
            "text": text,
            "action": action,
            "risk_level": _safe_text(data.get("risk_level"), 64) or "unknown",
            "categories": _safe_codes(data.get("categories")),
            "reason": _safe_text(data.get("reason"), 256) or "guarded_output",
        }
    elif event == "done":
        task_status = _task_status(data.get("status"))
        if task_status is None:
            return None
        payload = {**base, "status": "done", "task_status": task_status}
    elif event == "error":
        payload = {
            **base,
            "code": _safe_identifier(data.get("error_code"))
            or "AGENT_TASK_PLAN_STREAM_FAILED",
            "message": "TaskPlan 执行失败",
            "error_category": "system_error",
            "trace_id": _safe_identifier(data.get("trace_id")),
        }
    else:
        return None

    try:
        return TaskPlanPublicEventFrame.model_validate(
            {"event": event, "data": payload}
        )
    except ValidationError:
        return None


def _safe_identifier(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        return None
    return value


def _safe_enum(value: object, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _task_status(value: object) -> str | None:
    return _safe_enum(value, {item.value for item in AgentTaskPlanStatus})


def _safe_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _safe_list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _safe_confidence(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
        return result if 0.0 <= result <= 1.0 else None
    return None


def _safe_text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:max_length]


def _safe_codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if _safe_identifier(item) is not None][:100]


def _safe_sources(value: object) -> list[RagSource]:
    if not isinstance(value, list):
        return []
    sources: list[RagSource] = []
    for item in value[:100]:
        try:
            source = RagSource.model_validate(item)
        except ValidationError:
            continue
        sources.append(source.model_copy(update={"metadata": {}}))
    return sources


__all__ = [
    "TaskPlanPublicEventFrame",
    "project_task_plan_public_event",
]
