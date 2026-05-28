import asyncio
from collections.abc import AsyncGenerator

from fast_app.components.llms.base import BaseLLMClient
from fast_app.domain.rag_models import RagContext


class MockLLMClient(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        await asyncio.sleep(1)

        return (
            f"根据检索到的上下文，回答问题：{query}\n"
            f"核心结论：混合检索会同时利用向量检索和关键词检索，"
            f"再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n"
            f"参考上下文：\n{context.text}"
        )

    async def stream(
        self,
        query: str,
        context: RagContext,
    ) -> AsyncGenerator[str, None]:
        answer = (
            f"根据检索到的上下文，回答问题：{query}\n"
            f"混合检索的核心是：同时使用向量检索和关键词检索，"
            f"然后合并、去重、排序，得到更稳定的结果。\n\n"
            f"上下文摘要：{context.text}"
        )

        for char in answer:
            await asyncio.sleep(0.02)
            yield char