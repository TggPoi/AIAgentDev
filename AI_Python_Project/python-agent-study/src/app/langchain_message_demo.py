import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from fast_app.core.config import get_settings


async def main() -> None:
    settings = get_settings()

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 为空，请先在 .env 中配置阿里云 API Key")

    model = ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.7,
    )

    messages = [
        SystemMessage(content="你是一个专业的 Python / FastAPI 后端工程导师。"),
        HumanMessage(content="请用三句话解释什么是 RAG。"),
    ]

    response = await model.ainvoke(messages)

    print("response 类型：")
    print(type(response))

    print("\nresponse.content：")
    print(response.content)

    print("\nresponse.response_metadata：")
    print(response.response_metadata)

    print("\nresponse.usage_metadata：")
    print(response.usage_metadata)


if __name__ == "__main__":
    asyncio.run(main())


# response 类型：
# <class 'langchain_core.messages.ai.AIMessage'>

# response.content：
# RAG（Retrieval-Augmented Generation，检索增强生成）是一种将信息检索与大语言模型（LLM）生成能力相结合的技术框架。  
# 它首先从外部知识库（如文档、数据库或向量库）中检索与用户问题最相关的上下文片段，再将这些片段连同原始问题一起输入给 LLM，引导其生成更准确、可溯源、且基于最新/专有数据的回答。  
# 相比纯参数化模型，RAG 无需重新训练即可动态更新知识、降低幻觉风险，并支持领域定制化，是落地企业级 AI 应用的主流范式之一。

# response.response_metadata：
# {'token_usage': {'completion_tokens': 134, 'prompt_tokens': 35, 'total_tokens': 169, 'completion_tokens_details': None, 'prompt_tokens_details': {'audio_tokens': None, 'cached_tokens': 0}}, 'model_provider': 'openai', 'model_name': 'qwen-plus', 'system_fingerprint': None, 'id': 'chatcmpl-06af1bad-fa7c-98b5-ba53-a09257025868', 'finish_reason': 'stop', 'logprobs': None}

# response.usage_metadata：
# {'input_tokens': 35, 'output_tokens': 134, 'total_tokens': 169, 'input_token_details': {'cache_read': 0}, 'output_token_details': {}}