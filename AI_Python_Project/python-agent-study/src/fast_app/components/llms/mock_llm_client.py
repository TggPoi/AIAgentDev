import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext


logger = get_logger(__name__)


class MockLLMClient(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        start_time = perf_counter()

        try:
            logger.info(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.start",
                    provider="mock",
                    model_name="mock",
                    operation="generate",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                ),
            )

            await asyncio.sleep(1)

            answer = (
                f"根据检索到的上下文，回答问题：{query}\n"
                f"核心结论：混合检索会同时利用向量检索和关键词检索，"
                f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
                f"参考上下文：\n{context.context_text}"
            )
            latency_ms = (perf_counter() - start_time) * 1000

            logger.info(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.finish",
                    provider="mock",
                    model_name="mock",
                    operation="generate",
                    answer_length=len(answer),
                    latency_ms=round(latency_ms, 2),
                    usage_available=False,
                    usage_reason="mock_llm",
                ),
            )

            return answer

        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "llm_generate %s",
                format_log_fields(
                    event="llm.generate.failed",
                    provider="mock",
                    model_name="mock",
                    operation="generate",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise

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
                    provider="mock",
                    model_name="mock",
                    operation="stream",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                ),
            )

            answer = (
                f"根据检索到的上下文，回答问题：{query}\n"
                f"混合检索的核心是：同时使用向量检索和关键词检索，"
                f"然后合并、去重、排序，得到更稳定的结果。\n\n"
                f"上下文摘要：{context.context_text}"
            )

            for char in answer:
                await asyncio.sleep(0.02)
                chunk_count += 1
                output_length += len(char)
                yield char

            latency_ms = (perf_counter() - start_time) * 1000
            logger.info(
                "llm_stream %s",
                format_log_fields(
                    event="llm.stream.finish",
                    provider="mock",
                    model_name="mock",
                    operation="stream",
                    chunk_count=chunk_count,
                    output_length=output_length,
                    latency_ms=round(latency_ms, 2),
                    usage_available=False,
                    usage_reason="mock_llm",
                ),
            )

        except Exception as exc:
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "llm_stream %s",
                format_log_fields(
                    event="llm.stream.failed",
                    provider="mock",
                    model_name="mock",
                    operation="stream",
                    query_length=len(query),
                    context_doc_count=len(context.docs),
                    context_length=len(context.context_text),
                    error_type=type(exc).__name__,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise
