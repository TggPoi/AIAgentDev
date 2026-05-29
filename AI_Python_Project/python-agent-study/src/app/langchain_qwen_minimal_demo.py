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
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())