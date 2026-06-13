from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

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
StoreName = Literal["elasticsearch", "milvus"]


@dataclass(frozen=True)
class StoreWriteResult:
    store_name: StoreName
    success_count: int
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DualStoreWriteResult:
    chunk_count: int
    es: StoreWriteResult
    milvus: StoreWriteResult


def validate_store_write_inputs(
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> None:
    if not chunks:
        raise RuntimeError("写入 store 失败: chunks 不能为空")

    if len(chunks) != len(vectors):
        raise RuntimeError(
            "写入 store 失败: chunks 和 vectors 数量不一致: "
            f"chunks={len(chunks)}, vectors={len(vectors)}"
        )

    chunk_ids = [chunk.id for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise RuntimeError("写入 store 失败: chunk.id 存在重复")

    required_metadata_keys = [
        "doc_id",
        "chunk_id",
        "source_path",
        "document_type",
        "chunk_index",
    ]

    for chunk in chunks:
        if chunk.metadata.get("chunk_id") != chunk.id:
            raise RuntimeError(
                "写入 store 失败: metadata.chunk_id 与 chunk.id 不一致: "
                f"{chunk.id}"
            )

        for key in required_metadata_keys:
            if key not in chunk.metadata:
                raise RuntimeError(
                    f"写入 store 失败: chunk 缺少 metadata.{key}: {chunk.id}"
                )


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

# 双链路 写入 es milvus数据库入口
async def recreate_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)

    es_success_count = await recreate_es_index(
        client=elasticsearch_client,
        settings=settings,
        chunks=chunks,
    )

    milvus_insert_result = recreate_milvus_collection(
        client=milvus_client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
    )

    return DualStoreWriteResult(
        chunk_count=len(chunks),
        es=StoreWriteResult(
            store_name="elasticsearch",
            success_count=es_success_count,
            detail={
                "index_name": settings.elasticsearch_index_name,
            },
        ),
        milvus=StoreWriteResult(
            store_name="milvus",
            success_count=len(chunks),
            detail={
                "collection_name": settings.milvus_collection_name,
                "insert_result": milvus_insert_result,
            },
        ),
    )
