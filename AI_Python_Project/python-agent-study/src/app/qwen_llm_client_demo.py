import asyncio

from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.core.config import get_settings
from fast_app.domain.rag_models import RagContext, RetrievedDoc


async def main() -> None:
    settings = get_settings()

    client = QwenLangChainLLMClient(settings=settings)

    docs = [
        RetrievedDoc(
            id="doc_001",
            content="混合检索会结合向量检索和关键词检索。",
            score=0.91,
            source="milvus",
        ),
        RetrievedDoc(
            id="doc_002",
            content="关键词检索通常基于 BM25 等算法。",
            score=0.88,
            source="elasticsearch",
        ),
    ]

    context = RagContext(
        text="""
[0] source=milvus, score=0.91
混合检索会结合向量检索和关键词检索。

[1] source=elasticsearch, score=0.88
关键词检索通常基于 BM25 等算法。
""",
        docs=docs,
    )

    answer = await client.generate(
        query="什么是混合检索？",
        context=context,
    )

    print("普通生成结果：")
    print(answer)

    print("\n流式生成结果：")
    async for token in client.stream(
        query="什么是混合检索？",
        context=context,
    ):
        print(token, end="", flush=True)

    print()


if __name__ == "__main__":
    asyncio.run(main())