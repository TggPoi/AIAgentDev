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
        try:
            logger.info(
                "开始调用 qwen-plus: model=%s, query=%s",
                self.settings.llm_model_name,
                query,
            )

            response = await self.chain.ainvoke(
                {
                    "query": query,
                    "context": context.context_text,
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
                    "context": context.context_text,
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