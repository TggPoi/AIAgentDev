import asyncio

from langchain_openai import OpenAIEmbeddings

from fast_app.core.config import get_settings


async def main() -> None:
    settings = get_settings()

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 为空，请先在 .env 中配置阿里云 API Key")

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.embedding_dim,
        check_embedding_ctx_length=False,
    )

    query_text = "什么是混合检索？"

    query_vector = await embeddings.aembed_query(query_text)

    print("Query 文本：")
    print(query_text)

    print("\nQuery 向量类型：")
    print(type(query_vector))

    print("\nQuery 向量维度：")
    print(len(query_vector))

    print("\nQuery 向量前 5 个元素：")
    print(query_vector[:5])

    document_texts = [
        "混合检索会结合向量检索和关键词检索。",
        "关键词检索通常基于 BM25 等算法。",
    ]

    document_vectors = await embeddings.aembed_documents(document_texts)

    print("\nDocument 数量：")
    print(len(document_vectors))

    print("\n第一个 Document 向量维度：")
    print(len(document_vectors[0]))

    print("\n第一个 Document 向量前 5 个元素：")
    print(document_vectors[0][:5])


if __name__ == "__main__":
    asyncio.run(main())
