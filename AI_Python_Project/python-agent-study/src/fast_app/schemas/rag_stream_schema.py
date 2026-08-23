from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fast_app.schemas.rag_chat_schema import RagSource


RAG_SSE_CONTRACT_VERSION = "1.0"


class RagSseEventData(BaseModel):
    """所有公开 SSE payload 共用的版本和请求关联字段。"""

    model_config = ConfigDict(extra="allow")

    contract_version: Literal["1.0"] = Field(description="公开 SSE 契约版本。")
    request_id: str | None = Field(
        default=None,
        description="与 HTTP X-Request-ID 一致的请求关联 ID。",
    )


class RagSourcesEventData(RagSseEventData):
    sources: list[RagSource] = Field(description="本轮回答使用的稳定来源列表。")


class RagAnswerDeltaEventData(RagSseEventData):
    text: str = Field(description="已经通过输出安全边界的回答增量。")


class RagGuardEventData(RagSseEventData):
    text: str = Field(description="允许展示的安全或脱敏文本。")
    action: Literal["sanitize", "block"] = Field(description="Prompt Guard 处理动作。")
    risk_level: str = Field(description="Prompt Guard 风险级别。")
    categories: list[str] = Field(description="命中的安全分类 code。")
    reason: str = Field(description="安全处理原因。")


class RagDoneEventData(RagSseEventData):
    status: Literal["done"] = Field(description="结构化事件流正常结束标记。")


class RagErrorEventData(RagSseEventData):
    code: str = Field(description="稳定错误码。")
    message: str = Field(description="可安全展示的错误信息。")
    error_category: str = Field(description="用户、外部服务或系统错误分类。")
    trace_id: str | None = Field(default=None, description="服务端链路追踪 ID。")


class RagAgentRouteEventData(RagSseEventData):
    intent: str = Field(description="RagAgent Router 选择的稳定业务意图。")
    source: str = Field(description="路由结论来自规则、模型或安全兜底。")
    confidence: float = Field(ge=0.0, le=1.0, description="路由置信度。")
    reason: str = Field(description="路由原因或稳定原因 code。")


class RagAgentClarificationEventData(RagSseEventData):
    code: str = Field(description="要求澄清的稳定原因 code。")
    question: str = Field(description="需要用户补充回答的问题。")
    confidence: float = Field(ge=0.0, le=1.0, description="原路由置信度。")


class RagAgentTaskEventData(RagSseEventData):
    task_plan_id: str = Field(description="关联的 TaskPlan ID。")


class RagNl2SqlGeneratedEventData(RagSseEventData):
    query_id: str = Field(description="NL2SQL 查询审计 ID。")
    dataset_id: str = Field(description="服务端已授权 Dataset ID。")
    parameterized_sql: str = Field(description="只含绑定参数的审计 SQL。")
    attempt_count: int = Field(ge=1, description="SQL 生成尝试次数。")


class RagNl2SqlResultEventData(RagSseEventData):
    query_id: str = Field(description="NL2SQL 查询审计 ID。")
    dataset_id: str = Field(description="服务端已授权 Dataset ID。")


class RagSseEventFrame(BaseModel):
    """OpenAPI/fixture 使用的 SSE 逻辑帧；线上 wire 仍是 event/data 两行。"""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(description="SSE event 字段；未知新增事件应由前端安全忽略。")
    data: dict[str, Any] = Field(description="经过对应事件 Schema 校验的 JSON payload。")


_CORE_EVENT_MODELS: dict[str, type[RagSseEventData]] = {
    "sources": RagSourcesEventData,
    "answer_delta": RagAnswerDeltaEventData,
    "guard_sanitized": RagGuardEventData,
    "guard_blocked": RagGuardEventData,
    "done": RagDoneEventData,
    "error": RagErrorEventData,
    "agent_route_selected": RagAgentRouteEventData,
    "agent_route_clarification_required": RagAgentClarificationEventData,
    "nl2sql_sql_generated": RagNl2SqlGeneratedEventData,
    "nl2sql_result": RagNl2SqlResultEventData,
}


def normalize_and_validate_sse_event_data(
    event: str,
    data: object,
    *,
    request_id: str | None,
) -> dict[str, Any]:
    """补充公共契约字段并校验核心事件；未知事件保持向前兼容。"""

    if not isinstance(data, dict):
        raise TypeError("SSE event data 必须是 JSON object")
    normalized = {
        **data,
        "contract_version": RAG_SSE_CONTRACT_VERSION,
        "request_id": data.get("request_id") or request_id,
    }
    model = _CORE_EVENT_MODELS.get(event)
    if model is None and event.startswith("agent_task_"):
        model = RagAgentTaskEventData
    if model is None:
        return RagSseEventData.model_validate(normalized).model_dump(mode="json")
    return model.model_validate(normalized).model_dump(mode="json")


__all__ = [
    "RAG_SSE_CONTRACT_VERSION",
    "RagAnswerDeltaEventData",
    "RagDoneEventData",
    "RagErrorEventData",
    "RagGuardEventData",
    "RagSourcesEventData",
    "RagSseEventFrame",
    "normalize_and_validate_sse_event_data",
]
