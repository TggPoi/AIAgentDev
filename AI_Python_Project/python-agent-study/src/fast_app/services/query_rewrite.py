from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.conversation_history import ConversationHistoryWindow


logger = get_logger(__name__)


QUERY_REWRITE_SYSTEM_PROMPT = """你是一个多轮 RAG 检索问题改写助手。

你的任务是把【当前用户问题】改写成可以独立用于知识库检索的问题。

规则：
1. 如果当前问题依赖历史中的指代、省略或上下文，请补全必要上下文。
2. 如果当前问题已经可以独立检索，请原样返回当前问题。
3. 只输出改写后的检索问题，不要解释，不要输出编号，不要输出引号。
4. 不要回答问题本身。
5. 不要引入历史和当前问题之外的新事实。
"""


QUERY_REWRITE_HUMAN_PROMPT = """【最近对话历史】
{history}

【当前用户问题】
{query}

请输出一个可以独立用于知识库检索的问题。"""


class QueryRewriteResult(BaseModel):
    """query rewrite 的可观察结果。"""

    original_query: str
    rewritten_query: str
    used_history: bool
    reason: str


class ConversationQueryRewriter:
    """基于真实大模型的多轮 query rewrite 服务。"""

    def __init__(
        self,
        settings: Settings,
        model: ChatOpenAI | None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", QUERY_REWRITE_SYSTEM_PROMPT),
                ("human", QUERY_REWRITE_HUMAN_PROMPT),
            ]
        )
        self.chain = self.prompt | model if model is not None else None

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
        history_window: ConversationHistoryWindow | None,
    ) -> QueryRewriteResult:
        """结合历史窗口把当前追问改写成独立检索 query。"""

        if not self.settings.query_rewrite_enabled:
            return _fallback_result(query, "query_rewrite_disabled")

        if history_window is None or not history_window.formatted_text.strip():
            return _fallback_result(query, "history_window_empty")

        if self.chain is None:
            return _fallback_result(query, "query_rewrite_model_unavailable")

        try:
            response = await self.chain.ainvoke(
                {
                    "history": history_window.formatted_text,
                    "query": query,
                }
            )
            rewritten_query = _normalize_rewritten_query(
                _extract_message_content(response)
            )
            if rewritten_query == "":
                return _fallback_result(query, "query_rewrite_empty_response")

            used_history = rewritten_query != query
            reason = "rewritten_with_history" if used_history else "kept_original_query"
            logger.info(
                "query_rewrite %s",
                format_log_fields(
                    event="query_rewrite.finish",
                    original_query=query,
                    rewritten_query=rewritten_query,
                    used_history=used_history,
                    history_message_count=len(history_window.messages),
                    reason=reason,
                ),
            )

            return QueryRewriteResult(
                original_query=query,
                rewritten_query=rewritten_query,
                used_history=used_history,
                reason=reason,
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
