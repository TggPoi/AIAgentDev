from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fast_app.core.config import Settings
from fast_app.core.structured_output import invoke_structured_model
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.conversation.conversation_history import (
    ConversationHistoryWindow,
    ConversationMemoryContext,
    build_conversation_memory_context,
)
from fast_app.services.exceptions import AgentTaskPlanningServiceUnavailableError


logger = get_logger(__name__)


QUERY_REWRITE_SYSTEM_PROMPT = """你是一个多轮 RAG 检索问题改写助手。

你的任务是把【当前用户问题】改写成可以独立用于知识库检索的问题。

规则：
1. 如果当前问题依赖历史中的指代、省略或上下文，请补全必要上下文。
2. 如果当前问题已经可以独立检索，请原样返回当前问题。
3. 返回结构化解析结果，不回答问题本身。
4. 不要回答问题本身。
5. 不要引入历史和当前问题之外的新事实。
6. 只有上下文确实不足时才返回 unresolved，并提供一个澄清问题。
7. relevant_message_ids 只能选择输入中真实存在且确实用于解析指代的消息 ID。
"""


QUERY_REWRITE_HUMAN_PROMPT = """【会话记忆上下文】
{memory_context}

【当前用户问题】
{query}

请输出一个可以独立用于知识库检索的问题。

注意：
1. 最近对话优先于会话摘要。
2. 会话摘要只用于补充窗口外的目标、约束、决策和明确偏好。
3. 如果当前问题已经独立清楚，请原样返回。"""


class QueryRewriteResult(BaseModel):
    """query rewrite 的可观察结果。"""

    original_query: str = Field(description="用户本次提交的原始问题。")
    rewritten_query: str = Field(description="结合有限会话上下文后可独立检索的问题。")
    used_history: bool = Field(description="改写是否实际使用了最近消息窗口。")
    used_summary: bool = Field(default=False, description="改写是否实际使用了会话摘要。")
    summary_version: int | None = Field(
        default=None,
        description="使用的会话摘要版本；未使用摘要时为空。",
    )
    reason: str = Field(description="保持原问题或执行改写的简短理由。")
    resolution_status: Literal["resolved", "unresolved"] = Field(
        default="resolved",
        description="resolved 表示语义完整；unresolved 表示必须向用户澄清。",
    )
    relevant_message_ids: list[str] = Field(
        default_factory=list,
        description="本次指代解析实际使用且经服务端验证的历史消息 ID。",
    )
    clarification_question: str | None = Field(
        default=None,
        description="仅 unresolved 时返回的单个澄清问题。",
    )


class QueryResolutionDecision(BaseModel):
    """Query Rewriter 模型唯一允许输出的结构。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resolution_status: Literal["resolved", "unresolved"] = Field(
        description="当前问题是否已经能被可靠解析为完整任务语义。"
    )
    resolved_query: str | None = Field(
        default=None,
        description="resolved 时的完整任务语义；当前 query 优先于历史。",
    )
    relevant_message_ids: list[str] = Field(
        default_factory=list,
        description="仅列出为解决当前指代实际使用的输入消息 ID。",
    )
    clarification_question: str | None = Field(
        default=None,
        description="unresolved 时询问用户的单个澄清问题。",
    )
    reason: str = Field(description="解析或需要澄清的简短原因。")

    @model_validator(mode="after")
    def validate_resolution(self) -> QueryResolutionDecision:
        if self.resolution_status == "resolved" and not self.resolved_query:
            raise ValueError("resolved 必须返回 resolved_query")
        if self.resolution_status == "unresolved" and not self.clarification_question:
            raise ValueError("unresolved 必须返回 clarification_question")
        return self


class ConversationQueryRewriter:
    """基于真实大模型的多轮 query rewrite 服务。"""

    def __init__(
        self,
        settings: Settings,
        model: ChatOpenAI | None,
    ) -> None:
        self.settings = settings
        self.model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "ConversationQueryRewriter":
        """用现有 OpenAI-compatible 配置创建 rewrite 专用模型。"""

        if not settings.query_rewrite_enabled:
            return cls(settings=settings, model=None)

        if settings.llm_provider.lower().strip() != "qwen":
            return cls(settings=settings, model=None)

        if not settings.openai_api_key:
            return cls(settings=settings, model=None)

        model_name = settings.query_rewrite_model_name or settings.llm_model_name
        model = ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=settings.query_rewrite_temperature,
        )

        return cls(settings=settings, model=model)

    async def rewrite(
        self,
        query: str,
        history_window: ConversationHistoryWindow | None = None,
        memory_context: ConversationMemoryContext | None = None,
        langchain_config: RunnableConfig | None = None,
        fail_on_error: bool = False,
    ) -> QueryRewriteResult:
        """结合历史窗口把当前追问改写成独立检索 query。"""

        if not self.settings.query_rewrite_enabled:
            return _fallback_result(query, "query_rewrite_disabled")

        if memory_context is None and history_window is not None:
            memory_context = build_conversation_memory_context(
                conversation_id=history_window.conversation_id,
                recent_window=history_window,
            )

        if memory_context is None or not memory_context.formatted_text.strip():
            return _fallback_result(query, "history_window_empty")

        if self.model is None:
            if fail_on_error:
                raise AgentTaskPlanningServiceUnavailableError(
                    "Query Rewriter 模型未配置"
                )
            return _fallback_result(query, "query_rewrite_model_unavailable")

        try:
            message_payload = [
                {
                    "message_id": item.id,
                    "role": item.role.value,
                    "content": item.content,
                }
                for item in memory_context.recent_window.messages
                if item.role.value in {"user", "assistant"}
            ]
            response = await invoke_structured_model(
                model=self.model,
                schema=QueryResolutionDecision,
                messages=[
                    SystemMessage(content=QUERY_REWRITE_SYSTEM_PROMPT),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "summary": memory_context.summary_text,
                                "recent_messages": message_payload,
                                "current_query": query,
                            },
                            ensure_ascii=False,
                        )
                    ),
                ],
                config=langchain_config,
            )
            valid_ids = {item["message_id"] for item in message_payload}
            if not set(response.relevant_message_ids).issubset(valid_ids):
                raise ValueError("Rewriter 返回了不存在的历史消息 ID")
            if response.resolution_status == "unresolved":
                return QueryRewriteResult(
                    original_query=query,
                    rewritten_query=query,
                    used_history=False,
                    used_summary=False,
                    reason=response.reason,
                    resolution_status="unresolved",
                    relevant_message_ids=response.relevant_message_ids,
                    clarification_question=response.clarification_question,
                )

            rewritten_query = _normalize_rewritten_query(response.resolved_query or "")
            if not rewritten_query:
                raise ValueError("Query Rewriter 返回空 resolved_query")

            used_history = rewritten_query != query
            used_summary = memory_context.summary_text is not None
            if used_history and used_summary:
                reason = "rewritten_with_summary_and_history"
            elif used_history:
                reason = "rewritten_with_history"
            else:
                reason = "kept_original_query"
            logger.info(
                "query_rewrite %s",
                format_log_fields(
                    event="query_rewrite.finish",
                    original_query=query,
                    rewritten_query=rewritten_query,
                    used_history=used_history,
                    used_summary=used_summary,
                    summary_version=memory_context.summary_version,
                    history_message_count=len(memory_context.recent_window.messages),
                    reason=reason,
                ),
            )

            return QueryRewriteResult(
                original_query=query,
                rewritten_query=rewritten_query,
                used_history=used_history,
                used_summary=used_summary,
                summary_version=memory_context.summary_version,
                reason=response.reason or reason,
                resolution_status="resolved",
                relevant_message_ids=response.relevant_message_ids,
            )

        except Exception as exc:
            logger.exception(
                "query_rewrite %s",
                format_log_fields(
                    event="query_rewrite.failed",
                    original_query=query,
                    error_type=type(exc).__name__,
                ),
            )
            if fail_on_error:
                raise AgentTaskPlanningServiceUnavailableError(
                    "Query Rewriter 技术调用失败"
                ) from exc
            return _fallback_result(query, f"query_rewrite_failed:{type(exc).__name__}")


def _fallback_result(query: str, reason: str) -> QueryRewriteResult:
    return QueryRewriteResult(
        original_query=query,
        rewritten_query=query,
        used_history=False,
        reason=reason,
    )


def _extract_message_content(response: Any) -> str:
    if isinstance(response, AIMessage):
        return str(response.content)

    content = getattr(response, "content", None)
    if content is not None:
        return str(content)

    return str(response)


def _normalize_rewritten_query(value: str) -> str:
    normalized = value.strip()
    return normalized.strip("\"'“”‘’")


__all__ = [
    "ConversationQueryRewriter",
    "QueryRewriteResult",
]
