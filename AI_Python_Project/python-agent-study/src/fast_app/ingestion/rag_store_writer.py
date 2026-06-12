from datetime import UTC, datetime

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from pymilvus import MilvusClient

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.rag_store_schema import (
    build_es_mapping,
    build_milvus_index_params,
    build_milvus_schema,
)

# 负责把 `KnowledgeChunk` 写入 ES 和 Milvus 存储

async def recreate_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> int:
    index_name = settings.elasticsearch_index_name

    if await client.indices.exists(index=index_name):
        await client.indices.delete(index=index_name)

    await client.indices.create(index=index_name, **build_es_mapping())

    now = datetime.now(UTC).isoformat()
    actions = [
        {
            "_op_type": "index",
            "_index": index_name,
            "_id": chunk.id,
            "_source": {
                "id": chunk.id,
                "content": chunk.content,
                "title": chunk.title,
                "source": chunk.source,
                "metadata": chunk.metadata,
                "created_at": now,
            },
        }
        for chunk in chunks
    ]

    success_count, errors = await async_bulk(
        client=client,
        actions=actions,
        refresh=True,
    )

    if errors:
        raise RuntimeError(f"ES bulk 写入存在错误: {errors}")

    return int(success_count)


def recreate_milvus_collection(
    client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> dict:
    collection_name = settings.milvus_collection_name

    if client.has_collection(collection_name):
        client.drop_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        schema=build_milvus_schema(settings),
        index_params=build_milvus_index_params(settings),
    )

    rows = [
        {
            settings.milvus_id_field: chunk.id,
            settings.milvus_vector_field: vector,
            settings.milvus_content_field: chunk.content,
            "source": chunk.source,
            "title": chunk.title,
            "metadata": chunk.metadata,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    result = client.insert(
        collection_name=collection_name,
        data=rows,
    )

    client.flush(collection_name=collection_name)
    client.load_collection(collection_name=collection_name)

    return result