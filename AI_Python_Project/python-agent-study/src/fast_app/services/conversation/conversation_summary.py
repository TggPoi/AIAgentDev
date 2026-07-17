import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.conversation_models import (
    ConversationMessage,
    ConversationStructuredSummary,
    ConversationSummary,
    utc_now,
)
from fast_app.services.conversation.conversation_history import (
    ConversationHistoryWindow,
    ConversationMemoryContext,
    build_conversation_memory_context,
    format_history_messages,
)
from fast_app.services.conversation.conversation_repository import PostgresConversationRepository


logger = get_logger(__name__)


SUMMARY_SYSTEM_PROMPT = """你是一个 Agent 会话记忆压缩助手。

你的任务是把窗口外的旧对话压缩成可追溯的会话摘要，供后续 query rewrite 使用。

规则：
1. 只总结对话中明确出现的信息，不要写入猜测。
2. 优先保留目标、约束、已完成决策、未解决问题、用户明确偏好和关键实体。
3. 不要把临时推测写成稳定事实。
4. 如果已有摘要，请在已有摘要基础上增量更新。
5. 按调用方绑定的结构化输出 schema 返回；如果运行环境使用 JSON 模式，只输出 JSON。
"""


SUMMARY_HUMAN_PROMPT = """【已有摘要】
{existing_summary}

【待压缩的旧消息】
{messages}

请输出 JSON，字段必须是：
{{
  "summary_text": "一段中文摘要",
  "goals": ["..."],
  "constraints": ["..."],
  "decisions": ["..."],
  "open_questions": ["..."],
  "user_preferences": ["..."],
  "important_entities": ["..."]
}}"""


class SummaryModelOutput(BaseModel):
    """摘要模型的 JSON 输出结构。"""

    summary_text: str = Field(description="窗口外旧消息的中文摘要")
    goals: list[str] = Field(default_factory=list, description="对话中明确出现的目标")
    constraints: list[str] = Field(default_factory=list, description="对话中明确出现的约束")
    decisions: list[str] = Field(default_factory=list, description="已经确认的决策或结论")
    open_questions: list[str] = Field(default_factory=list, description="仍未解决的问题")
    user_preferences: list[str] = Field(default_factory=list, description="用户明确表达的偏好")
    important_entities: list[str] = Field(default_factory=list, description="关键实体、系统或文件名")


class ConversationSummaryService:
    """会话摘要压缩服务。

    它负责把 PostgreSQL 中窗口外的旧消息压缩成带版本和来源的 summary。
    Redis recent window 仍然负责短期上下文，summary 只补充窗口外信息。
    """

    def __init__(
        self,
        settings: Settings,
        repository: PostgresConversationRepository,
        model: ChatOpenAI | None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SUMMARY_SYSTEM_PROMPT),
                ("human", SUMMARY_HUMAN_PROMPT),
            ]
        )

        # 构建LCEL执行链
        self.chain = self.prompt | model if model is not None else None

        if model is None:
            self.structured_chain = None
            self.json_mode_chain = None

        else:
            # 阿里云 Qwen structured output 对应 OpenAI-compatible 的 JSON mode：
            # 请求里设置 response_format={"type": "json_object"}，再由 Pydantic 校验字段。
            # 不优先使用 function_calling，避免 DashScope 返回 BadRequestError。
            self.structured_chain = None
            self.json_mode_chain = self.prompt | model.with_structured_output(
                SummaryModelOutput,
                method="json_mode",
                include_raw=True,
            )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        repository: PostgresConversationRepository,
    ) -> "ConversationSummaryService":
        """按当前工程的 OpenAI-compatible 配置创建 summary 专用模型。"""

        if not settings.summary_memory_enabled:
            return cls(settings=settings, repository=repository, model=None)

        if settings.llm_provider.lower().strip() != "qwen":
            return cls(settings=settings, repository=repository, model=None)

        if not settings.openai_api_key:
            return cls(settings=settings, repository=repository, model=None)

        model_name = settings.summary_memory_model_name or settings.llm_model_name
        model = ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=settings.summary_memory_temperature,
        )

        return cls(settings=settings, repository=repository, model=model)

    async def maybe_update_summary(
        self,
        conversation_id: str,
        recent_window: ConversationHistoryWindow,
    ) -> ConversationSummary | None:
        """必要时生成新版本 summary，并返回可用于 query rewrite 的最新 summary。"""

        if not self.settings.summary_memory_enabled:
            return None

        latest_summary = await self.repository.get_latest_summary(conversation_id)

        # 如果模型不可用，降级返回已有 summary
        if self.chain is None:
            logger.info(
                "conversation_summary %s",
                format_log_fields(
                    event="conversation_summary.model_unavailable",
                    conversation_id=conversation_id,
                ),
            )
            return latest_summary

        # memory_history_max_turns 范围内的消息不参与压缩 保留最近几轮对话细节

        recent_message_count = max(self.settings.memory_history_max_turns, 0) * 2

        # 计算读取消息数量 判断是否有足够多的旧消息可以压缩 但是需要排除最近窗口
        limit = self.settings.summary_memory_trigger_messages + recent_message_count
        candidate_messages = await self.repository.list_messages_after_summary(
            conversation_id=conversation_id,
            after_message_id=(
                latest_summary.covered_until_message_id
                if latest_summary is not None
                else None
            ),
            limit=limit,
        )

        # 排除最近窗口
        summarizable_messages = _exclude_recent_messages(
            messages=candidate_messages,
            recent_message_count=recent_message_count,
        )

        # 判断是否达到触发阈值
        if len(summarizable_messages) < self.settings.summary_memory_trigger_messages:
            return latest_summary

        try:
            # 开始生成 summary
            summary = await self._generate_summary(
                conversation_id=conversation_id,
                latest_summary=latest_summary,
                source_messages=summarizable_messages,
            )
        except Exception as exc:
            logger.exception(
                "conversation_summary %s",
                format_log_fields(
                    event="conversation_summary.generate_failed",
                    conversation_id=conversation_id,
                    error_type=type(exc).__name__,
                ),
            )
            return latest_summary

        await self.repository.append_summary(summary)
        logger.info(
            "conversation_summary %s",
            format_log_fields(
                event="conversation_summary.saved",
                conversation_id=conversation_id,
                version=summary.version,
                source_message_count=summary.source_message_count,
                covered_until_message_id=summary.covered_until_message_id,
            ),
        )
        return summary

    def build_memory_context(
        self,
        conversation_id: str,
        recent_window: ConversationHistoryWindow,
        summary: ConversationSummary | None,
    ) -> ConversationMemoryContext:
        """把最新 summary 和最近窗口组合成 query rewrite 输入。"""

        if not self.settings.summary_memory_enabled:
            summary = None

        return build_conversation_memory_context(
            conversation_id=conversation_id,
            recent_window=recent_window,
            summary=summary,
        )

    # 构建新的summary，更新version信息
    async def _generate_summary(
        self,
        conversation_id: str,
        latest_summary: ConversationSummary | None,
        source_messages: list[ConversationMessage],
    ) -> ConversationSummary:
        """调用摘要模型生成新的 summary 版本。"""

        if self.chain is None:
            raise RuntimeError("summary model is unavailable")

        output = await self._invoke_summary_model(
            {
                "existing_summary": (
                    latest_summary.summary_text
                    if latest_summary is not None
                    else "暂无"
                ),
                "messages": format_history_messages(source_messages),
            }
        )
        now = utc_now()
        source_message_ids = [message.id for message in source_messages]
        # 触发新的summary，version版本更新
        version = (latest_summary.version + 1) if latest_summary is not None else 1

        return ConversationSummary(
            conversation_id=conversation_id,
            summary_text=output.summary_text.strip(),
            structured_summary=ConversationStructuredSummary(
                goals=_normalize_list(output.goals),
                constraints=_normalize_list(output.constraints),
                decisions=_normalize_list(output.decisions),
                open_questions=_normalize_list(output.open_questions),
                user_preferences=_normalize_list(output.user_preferences),
                important_entities=_normalize_list(output.important_entities),
            ),
            version=version,
            source_message_ids=source_message_ids,
            source_message_count=len(source_message_ids),
            covered_until_message_id=(
                source_messages[-1].id if source_messages else None
            ),
            created_at=now,
            updated_at=now,
            metadata={
                "summary_strategy": "incremental_window_exclusion",
                "previous_summary_id": (
                    latest_summary.id if latest_summary is not None else None
                ),
            },
        )

    async def _invoke_summary_model(self, inputs: dict[str, str]) -> SummaryModelOutput:
        """优先使用结构化输出生成 summary，最后才退回文本 JSON 解析。

        这里保留三级策略：
        1. json_mode：要求模型输出合法 JSON，再由 Pydantic 校验字段。
        2. 普通文本链：兼容不支持结构化输出的 provider，但仅作为兜底。
        """

        if self.json_mode_chain is not None:
            try:
                response = await self.json_mode_chain.ainvoke(inputs)
                return _coerce_summary_output(response)
            except Exception as exc:
                logger.warning(
                    "conversation_summary %s",
                    format_log_fields(
                        event="conversation_summary.structured_output_failed",
                        method="json_mode",
                        error_type=type(exc).__name__,
                    ),
                )

        if self.chain is None:
            raise RuntimeError("summary model is unavailable")

        # 最后降级为Prompt约束
        response = await self.chain.ainvoke(inputs)
        return _parse_summary_output(_extract_message_content(response))


def _exclude_recent_messages(
    messages: list[ConversationMessage],
    recent_message_count: int,
) -> list[ConversationMessage]:
    if recent_message_count <= 0:
        return messages

    if len(messages) <= recent_message_count:
        return []

    return messages[:-recent_message_count]


def _extract_message_content(response: Any) -> str:
    if isinstance(response, AIMessage):
        return str(response.content)

    content = getattr(response, "content", None)
    if content is not None:
        return str(content)

    return str(response)

# 兼容 LangChain 不同返回格式
def _coerce_summary_output(response: Any) -> SummaryModelOutput:
    """把 LangChain 结构化输出结果统一转换为 SummaryModelOutput。"""

    if isinstance(response, SummaryModelOutput):
        return response

    if isinstance(response, dict):
        parsed = response.get("parsed") if "parsed" in response else response
        if isinstance(parsed, SummaryModelOutput):
            return parsed
        if isinstance(parsed, dict):
            return SummaryModelOutput.model_validate(parsed)

        raw = response.get("raw")
        if raw is not None:
            return _parse_summary_output(_extract_message_content(raw))

        parsing_error = response.get("parsing_error")
        if parsing_error is not None:
            raise parsing_error

    raise TypeError(f"Unsupported summary output type: {type(response).__name__}")

# 从文本中解析 JSON
def _parse_summary_output(content: str) -> SummaryModelOutput:
    raw = content.strip()
    try:
        return SummaryModelOutput.model_validate_json(raw)
    except ValidationError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise

        data = json.loads(raw[start : end + 1])
        return SummaryModelOutput.model_validate(data)

# 清洗列表字段格式
def _normalize_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)

    return normalized


__all__ = ["ConversationSummaryService"]
