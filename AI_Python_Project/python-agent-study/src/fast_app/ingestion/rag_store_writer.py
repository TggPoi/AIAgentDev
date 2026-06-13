from datetime import UTC, datetime

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from pymilvus import MilvusClient

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_CREATED_AT_FIELD,
    ES_ID_FIELD,
    ES_IK_INDEX_ANALYZER,
    ES_IK_SEARCH_ANALYZER,
    ES_METADATA_FIELD,
    ES_SOURCE_FIELD,
    ES_TITLE_FIELD,
    MILVUS_CHUNK_INDEX_FIELD,
    MILVUS_DOC_ID_FIELD,
    MILVUS_DOCUMENT_TYPE_FIELD,
    MILVUS_METADATA_FIELD,
    MILVUS_SOURCE_FIELD,
    MILVUS_SOURCE_PATH_FIELD,
    MILVUS_TITLE_FIELD,
    build_es_mapping,
    build_milvus_index_params,
    build_milvus_schema,
)

# 负责把 `KnowledgeChunk` 写入 ES 和 Milvus 存储

async def verify_es_ik_analyzers(client: AsyncElasticsearch) -> None:
    sample_text = "混合检索结合向量召回和关键词召回"

    for analyzer in [ES_IK_INDEX_ANALYZER, ES_IK_SEARCH_ANALYZER]:
        await client.indices.analyze(
            analyzer=analyzer,
            text=sample_text,
        )


async def recreate_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> int:
    index_name = settings.elasticsearch_index_name

    await verify_es_ik_analyzers(client)

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
                ES_ID_FIELD: chunk.id,
                ES_CONTENT_FIELD: chunk.content,
                ES_TITLE_FIELD: chunk.title,
                ES_SOURCE_FIELD: chunk.source,
                ES_METADATA_FIELD: chunk.metadata,
                ES_CREATED_AT_FIELD: now,
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
            MILVUS_SOURCE_FIELD: chunk.source,
            MILVUS_TITLE_FIELD: chunk.title,
            MILVUS_DOC_ID_FIELD: str(chunk.metadata["doc_id"]),
            MILVUS_SOURCE_PATH_FIELD: str(chunk.metadata["source_path"]),
            MILVUS_DOCUMENT_TYPE_FIELD: str(chunk.metadata["document_type"]),
            MILVUS_CHUNK_INDEX_FIELD: int(chunk.metadata["chunk_index"]),
            MILVUS_METADATA_FIELD: chunk.metadata,
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
