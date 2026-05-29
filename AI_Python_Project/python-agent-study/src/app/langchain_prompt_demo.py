import asyncio

from langchain_core.prompts import ChatPromptTemplate
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
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages(
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

    query = "什么是混合检索？"
    context = """
[0] source=milvus, score=0.91
混合检索会结合向量检索和关键词检索。

[1] source=elasticsearch, score=0.88
关键词检索通常基于 BM25 等算法。
"""

    messages = await prompt.ainvoke(
        {
            "query": query,
            "context": context,
        }
    )

    print("Prompt 生成的 messages：")
    print(messages)

    response = await model.ainvoke(messages)

    print("\n模型回复：")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())


# Prompt 生成的 messages：
# messages=[
# SystemMessage(content='\n你是一个严谨的 RAG 问答助手。\n\n请遵守以下规则：\n1. 优先根据给定的检索上下文回答。\n2. 如果上下文不足以回答，请明确说明“无法从给定上下文中确定”。\n3. 不要编造上下文中不存在的信息。\n4. 使用中文回答。\n', 
# additional_kwargs={}, response_metadata={}), 
# HumanMessage(content='\n用户问题：\n什么是混合检索？\n\n检索上下文：\n\n[0] source=milvus, score=0.91\n混合检索会结合向量检索和关键词检索。\n\n[1] source=elasticsearch, score=0.88\n关键词检索通常基于 BM25 等算法。\n\n', 
# additional_kwargs={}, response_metadata={})]

# 模型回复：
# 混合检索是一种结合向量检索和关键词检索的检索方法，旨在兼顾语义相关性和字面匹配精度。根据上下文，它通过融合两种互补的检索方式（如基于嵌入向量的语义搜索与基于 BM25 等算法的关键词匹配）来提升整体检索效果。