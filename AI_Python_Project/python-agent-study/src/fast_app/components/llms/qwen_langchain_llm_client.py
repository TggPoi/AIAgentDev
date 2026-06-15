from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext
from fast_app.services.exceptions import LLMCallError



logger = get_logger(__name__)


RAG_SYSTEM_PROMPT = """你是一个严谨的 RAG 问答助手。

你必须遵守以下规则：

1. 只能根据【检索上下文】回答用户问题。
2. 如果【检索上下文】中没有足够信息回答问题，请直接回答：
   “当前知识库中没有足够信息回答这个问题。”
3. 不要编造【检索上下文】中没有出现的事实、代码、配置、版本、结论。
4. 如果可以回答，请尽量引用相关文档 id，例如：[rag_hybrid_001]。
5. 如果多个文档都支持你的回答，可以引用多个文档 id。
6. 回答要清晰、直接，不要输出无关背景知识。
"""

# 让模型回答更保守
# RAG_SYSTEM_PROMPT = """你是一个严谨的 RAG 问答助手。

# 你必须严格遵守以下规则：

# 1. 你只能根据【检索上下文】回答用户问题。
# 2. 你不能使用自己的外部知识补充答案。
# 3. 如果【检索上下文】没有直接或间接支持答案，请回答：
#    “当前知识库中没有足够信息回答这个问题。”
# 4. 不要猜测，不要推断上下文之外的事实。
# 5. 如果可以回答，请在关键结论后标注支持该结论的文档 id，例如：[rag_hybrid_001]。
# 6. 如果上下文中多个文档互相冲突，请指出冲突，而不是自行选择一个没有依据的结论。
# 7. 回答要简洁、准确、直接。
# """


RAG_HUMAN_PROMPT = """用户问题：
{query}

{context}

请根据以上检索上下文回答用户问题。"""


def get_response_metadata(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "response_metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def get_usage_metadata(response: Any) -> dict[str, Any]:
    usage_metadata = getattr(response, "usage_metadata", None)

    if isinstance(usage_metadata, dict):
        return usage_metadata

    response_metadata = get_response_metadata(response)
    token_usage = response_metadata.get("token_usage")
    return token_usage if isinstance(token_usage, dict) else {}


def get_usage_int(usage: dict[str, Any], key: str) -> int | None:
    fallback_keys = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
    }
    value = usage.get(key)

    if value is None:
        value = usage.get(fallback_keys.get(key, ""))

    if isinstance(value, bool):
        return None

    return int(value) if isinstance(value, int) else None


def get_finish_reason(response: Any) -> str | None:
    value = get_response_metadata(response).get("finish_reason")
    return str(value) if value else None


def get_response_model_name(response: Any) -> str | None:
    value = get_response_metadata(response).get("model_name")
    return str(value) if value else None


class QwenLangChainLLMClient(BaseLLMClient):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise LLMCallError("OPENAI_API_KEY 为空，无法调用 qwen-plus")

        self.settings = settings

        self.model = ChatOpenAI(
            model=settings.llm_model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.3,
        )

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",RAG_SYSTEM_PROMPT,
                ),
                (
                    "human",
                    RAG_HUMAN_PROMPT,
                ),
            ]
        )

        self.chain = self.prompt | self.model


    async def generate(self, query: str, context: RagContext) -> str:
        start_time = perf_counter()

        try:
            logger.info(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.start",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="generate",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    timeout_seconds=self.settings.llm_timeout_seconds,
                ),
            )

            response = await self.chain.ainvoke(
                {
                    "query": query,
                    "context": context.context_text,
                }
            )

            answer = self._extract_message_content(response)
            usage = get_usage_metadata(response)
            latency_ms = (perf_counter() - start_time) * 1000

            logger.info(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.finish",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="generate",
                    answer_length=len(answer),
                    latency_ms=round(latency_ms, 2),
                    prompt_tokens=get_usage_int(usage, "prompt_tokens"),
                    completion_tokens=get_usage_int(usage, "completion_tokens"),
                    total_tokens=get_usage_int(usage, "total_tokens"),
                    finish_reason=get_finish_reason(response),
                    model_name_from_response=get_response_model_name(response),
                    usage_available=bool(usage),
                ),
            )

            return answer

        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.failed",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="generate",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    timeout_seconds=self.settings.llm_timeout_seconds,
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )

            if isinstance(exc, LLMCallError):
                raise

            raise LLMCallError(f"qwen-plus 调用失败: {exc}") from exc


    async def stream(
        self,
        query: str,
        context: RagContext,
    ) -> AsyncGenerator[str, None]:
        start_time = perf_counter()
        chunk_count = 0
        output_length = 0

        try:
            logger.info(
                "llm_stream %s",
                format_log_fields(
                    event="llm.stream.start",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="stream",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    timeout_seconds=self.settings.llm_timeout_seconds,
                ),
            )

            async for chunk in self.chain.astream(
                {
                    "query": query,
                    "context": context.context_text,
                }
            ):
                content = getattr(chunk, "content", "")

                if content:
                    text = str(content)
                    chunk_count += 1
                    output_length += len(text)
                    yield text

            latency_ms = (perf_counter() - start_time) * 1000
            logger.info(
                "llm_stream %s",
                format_log_fields(
                    event="llm.stream.finish",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="stream",
                    chunk_count=chunk_count,
                    output_length=output_length,
                    latency_ms=round(latency_ms, 2),
                    usage_available=False,
                    usage_reason="stream_usage_not_available",
                ),
            )

        # LangChain / qwen-plus 的底层异常属于组件内部细节。
        # RagPipeline 不应该知道具体 SDK 抛了什么异常。
        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "llm_stream %s",
                format_log_fields(
                    event="llm.stream.failed",
                    provider="qwen_langchain",
                    model_name=self.settings.llm_model_name,
                    operation="stream",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    timeout_seconds=self.settings.llm_timeout_seconds,
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise LLMCallError(f"qwen-plus 流式调用失败: {exc}") from exc


    # 防御性适配
    # 如果是 AIMessage：取 response.content
    # 如果有 content 属性：取 content
    # 否则：直接 str(response)
    def _extract_message_content(self, response: Any) -> str:
        if isinstance(response, AIMessage):
            return str(response.content)
        
        # Get a named attribute from an object.
        content = getattr(response, "content", None)

        if content is not None:
            return str(content)

        return str(response)
