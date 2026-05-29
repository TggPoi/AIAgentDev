import asyncio

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

    response = await model.ainvoke("请用一句话解释什么是 RAG。")

    print("模型回复：")
    # print(response.content)
    print(response)


if __name__ == "__main__":
    asyncio.run(main())


# 模型回复：                                       
# content='RAG（Retrieval-Augmented Generation，检索增强生成）是一种将外部知识检索与大语言模型生成能力相结合的技术：在回答问题前，先从可靠的知识库中检索相关文档片段，再将这些信息作为上下文输入给大语言模型，从而生成更准确、可溯源、且时效性更强的回答。' 
# additional_kwargs={'refusal': None} 
# response_metadata={'token_usage': {'completion_tokens': 71, 'prompt_tokens': 16, 'total_tokens': 87, 'completion_tokens_details': None, 'prompt_tokens_details': {'audio_tokens': None, 'cached_tokens': 0}}, 
# 'model_provider': 'openai', 
# 'model_name': 'qwen-plus', 
# 'system_fingerprint': None, 
# 'id': 'chatcmpl-59b5e2c6-2362-97d6-a3a8-7f82f061f42c', 
# 'finish_reason': 'stop', 
# 'logprobs': None} 
# id='lc_run--019e7236-e68d-7ea3-924a-25c23301a401-0' 
# tool_calls=[]
#  invalid_tool_calls=[] 
# usage_metadata={'input_tokens': 16, 'output_tokens': 71, 'total_tokens': 87, 
# 'input_token_details': {'cache_read': 0}, 'output_token_details': {}}