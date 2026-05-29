from collections.abc import AsyncGenerator
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from fast_app.components.llms.base import BaseLLMClient
from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.domain.rag_models import RagContext
from fast_app.services.exceptions import LLMCallError
from fast_app.services.rag_pipeline_service import RagPipeline


logger = get_logger(__name__)


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
                    "system",
                    """
你是一个严谨的 RAG 问答助手。

请遵守以下规则：
1. 优先根据给定的检索上下文回答。
2. 如果上下文不足以回答，请明确说明“无法从给定上下文中确定”。
3. 不要编造上下文中不存在的信息。
4. 使用中文回答。
""",
                ),
                (
                    "human",
                    """
用户问题：
{query}

检索上下文：
<context>
{context}
</context>

请基于上述上下文给出回答。
""",
                ),
            ]
        )

        self.chain = self.prompt | self.model


    async def generate(self, query: str, context: RagContext) -> str:
        try:
            logger.info(
                "开始调用 qwen-plus: model=%s, query=%s",
                self.settings.llm_model_name,
                query,
            )

            response = await self.chain.ainvoke(
                {
                    "query": query,
                    "context": context.text,
                }
            )

            answer = self._extract_message_content(response)

            logger.info("qwen-plus 调用完成: answer_length=%s", len(answer))

            return answer

        except LLMCallError:
            raise

        except Exception as exc:
            logger.exception("qwen-plus 调用失败")
            raise LLMCallError(f"qwen-plus 调用失败: {exc}") from exc


    async def stream(
        self,
        query: str,
        context: RagContext,
    ) -> AsyncGenerator[str, None]:
        try:
            logger.info(
                "开始流式调用 qwen-plus: model=%s, query=%s",
                self.settings.llm_model_name,
                query,
            )

            async for chunk in self.chain.astream(
                {
                    "query": query,
                    "context": context.text,
                }
            ):
                content = getattr(chunk, "content", "")

                if content:
                    yield str(content)

            logger.info("qwen-plus 流式调用完成")

        # LangChain / qwen-plus 的底层异常属于组件内部细节。
        # RagPipeline 不应该知道具体 SDK 抛了什么异常。
        except Exception as exc:
            logger.exception("qwen-plus 流式调用失败")
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