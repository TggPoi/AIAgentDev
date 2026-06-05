import asyncio

from langchain_openai import OpenAIEmbeddings
from pymilvus import DataType, MilvusClient

from app.build_demo_chunks import build_demo_chunks
from fast_app.core.config import get_settings


def build_milvus_uri(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def create_collection_if_needed(
    client: MilvusClient,
    collection_name: str,
    vector_field: str,
    id_field: str,
    content_field: str,
    dim: int,
) -> None:
    if client.has_collection(collection_name):
        print(f"Collection 已存在: {collection_name}")
        return

    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )

    schema.add_field(
        field_name=id_field,
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=128,
    )
    schema.add_field(
        field_name=vector_field,
        datatype=DataType.FLOAT_VECTOR,
        dim=dim,
    )
    schema.add_field(
        field_name=content_field,
        datatype=DataType.VARCHAR,
        max_length=4096,
    )
    schema.add_field(
        field_name="source",
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name="title",
        datatype=DataType.VARCHAR,
        max_length=512,
    )

    index_params = MilvusClient.prepare_index_params()

    index_params.add_index(
        field_name=vector_field,
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )

    print(f"Collection 创建完成: {collection_name}")


async def build_embeddings(texts: list[str]) -> list[list[float]]:
    settings = get_settings()

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.embedding_dim,
        check_embedding_ctx_length=False,
    )

    return await embeddings.aembed_documents(texts)


async def main() -> None:
    settings = get_settings()

    uri = build_milvus_uri(
        host=settings.milvus_host,
        port=settings.milvus_port,
    )

    client = MilvusClient(uri=uri)

    chunks = build_demo_chunks()

    print(f"准备写入 chunk 数量: {len(chunks)}")
    print(f"Milvus URI: {uri}")
    print(f"Collection: {settings.milvus_collection_name}")
    print(f"Embedding model: {settings.embedding_model_name}")
    print(f"Embedding dim: {settings.embedding_dim}")

    create_collection_if_needed(
        client=client,
        collection_name=settings.milvus_collection_name,
        vector_field=settings.milvus_vector_field,
        id_field=settings.milvus_id_field,
        content_field=settings.milvus_content_field,
        dim=settings.embedding_dim,
    )

    texts = [chunk.content for chunk in chunks]
    vectors = await build_embeddings(texts)

    if len(vectors) == 0:
        raise RuntimeError("embedding 结果为空")

    actual_dim = len(vectors[0])

    if actual_dim != settings.embedding_dim:
        raise RuntimeError(
            f"embedding 维度不匹配: actual={actual_dim}, settings={settings.embedding_dim}"
        )

    rows = []

    for chunk, vector in zip(chunks, vectors, strict=True):
        rows.append(
            {
                settings.milvus_id_field: chunk.id,
                settings.milvus_vector_field: vector,
                settings.milvus_content_field: chunk.content,
                "source": chunk.source,
                "title": chunk.title,
            }
        )

    result = client.upsert(
        collection_name=settings.milvus_collection_name,
        data=rows,
    )

    print("Upsert 结果:")
    print(result)

    client.flush(
        collection_name=settings.milvus_collection_name,
    )

    client.load_collection(
        collection_name=settings.milvus_collection_name,
    )

    print("Milvus 写入完成并已 load collection")

    await search_smoke_test(client)


async def search_smoke_test(client: MilvusClient) -> None:
    settings = get_settings()

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        dimensions=settings.embedding_dim,
        check_embedding_ctx_length=False,
    )

    query = "什么是混合检索？"
    query_vector = await embeddings.aembed_query(query)

    results = client.search(
        collection_name=settings.milvus_collection_name,
        data=[query_vector],
        anns_field=settings.milvus_vector_field,
        limit=3,
        output_fields=[
            settings.milvus_id_field,
            settings.milvus_content_field,
            "source",
            "title",
        ],
        search_params={
            "metric_type": "COSINE",
            "params": {},
        },
    )

    print("\nSearch smoke test:")
    print(f"query: {query}")

    for hit in results[0]:
        print("-" * 80)
        print(f"id: {hit['entity'][settings.milvus_id_field]}")
        print(f"distance: {hit['distance']}")
        print(f"title: {hit['entity']['title']}")
        print(f"source: {hit['entity']['source']}")
        print(f"content: {hit['entity'][settings.milvus_content_field]}")


if __name__ == "__main__":
    asyncio.run(main())


# python -m app.ingest_milvus_docs
# 准备写入 chunk 数量: 7
# Milvus URI: http://127.0.0.1:19530
# Collection: python_agent_demo_chunks
# Embedding model: text-embedding-v4
# Embedding dim: 1024
# Collection 创建完成: python_agent_demo_chunks
# Upsert 结果:
# {'upsert_count': 7, 'ids': ['rag_basic_001', 'rag_vector_001', 'rag_keyword_001', 'rag_hybrid_001', 'milvus_basic_001', 'es_basic_001', 'langgraph_basic_001']}
# Milvus 写入完成并已 load collection

# Search smoke test:
# query: 什么是混合检索？
# --------------------------------------------------------------------------------
# id: rag_hybrid_001
# distance: 0.8325591087341309
# title: 混合检索
# source: demo
# content: 混合检索会同时结合向量检索和关键词检索。向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。
# --------------------------------------------------------------------------------
# id: rag_keyword_001
# distance: 0.6006093621253967
# title: 关键词检索
# source: demo
# content: 关键词检索通常基于倒排索引和 BM25 等相关性算法。它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。ElasticSearch 是常见的关键词检索引擎。
# --------------------------------------------------------------------------------
# id: rag_vector_001
# distance: 0.592630922794342
# title: 向量检索
# source: demo
# content: 向量检索会先把文本转换成 embedding 向量，然后通过向量相似度查找语义接近的内容。它适合处理表达方式不同但语义相似的问题，例如用户没有使用原文关键词，但问题含义和某段知识非常接近。