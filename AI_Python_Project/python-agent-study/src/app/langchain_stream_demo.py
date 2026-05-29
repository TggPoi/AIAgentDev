import asyncio

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from fast_app.core.config import get_settings


RAG_INPUT = {
    "query": "什么是混合检索？",
    "context": """
[0] source=milvus, score=0.91
混合检索会结合向量检索和关键词检索。

[1] source=elasticsearch, score=0.88
关键词检索通常基于 BM25 等算法。
""",
}


def build_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
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


async def run_ainvoke(chain) -> None:
    print("===== ainvoke 一次性输出 =====")

    response = await chain.ainvoke(RAG_INPUT)

    print("response 类型：")
    print(type(response))

    print("\nresponse.content：")
    print(response.content)


async def run_astream(chain) -> None:
    print("\n===== astream 流式输出 =====")

    async for chunk in chain.astream(RAG_INPUT):
        content = chunk.content

        # 避免chunk里面有空白字符
        if content:
            print(content, end="", flush=True)

    print("\n\n===== astream 流式输出结束 =====")


async def main() -> None:
    settings = get_settings()

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 为空，请先在 .env 中配置阿里云 API Key")

    model = ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.3,
    )

    prompt = build_prompt()
    chain = prompt | model

    await run_ainvoke(chain)
    await run_astream(chain)


if __name__ == "__main__":
    asyncio.run(main())