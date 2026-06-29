from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from pymilvus import MilvusClient

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.rag_store_admin import (
    StoreResetOptions,
    reset_es_index,
    reset_milvus_collection,
    verify_es_ik_analyzers,
)
from fast_app.ingestion.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_CREATED_AT_FIELD,
    ES_ID_FIELD,
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
IngestionWriteMode = Literal["recreate", "upsert", "replace_docs"]


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


def get_ingestion_write_mode(settings: Settings) -> IngestionWriteMode:
    mode = settings.ingestion_write_mode.strip().lower()

    if mode not in {"recreate", "upsert", "replace_docs"}:
        raise RuntimeError(
            f"不支持的 ingestion 写入模式: {settings.ingestion_write_mode}"
        )

    return mode


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
        "visibility",
        "allowed_departments",
        "allowed_users",
        "permission_source",
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


def collect_doc_ids(chunks: list[KnowledgeChunk]) -> list[str]:
    doc_ids = {str(chunk.metadata["doc_id"]) for chunk in chunks}
    return sorted(doc_ids)


def escape_milvus_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def ensure_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
) -> None:
    await verify_es_ik_analyzers(client)

    if await client.indices.exists(index=settings.elasticsearch_index_name):
        return

    await client.indices.create(
        index=settings.elasticsearch_index_name,
        **build_es_mapping(),
    )


def build_es_bulk_actions(
    index_name: str,
    chunks: list[KnowledgeChunk],
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()

    return [
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


async def recreate_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> int:
    index_name = settings.elasticsearch_index_name

    await reset_es_index(
        client=client,
        settings=settings,
        options=StoreResetOptions(
            target="elasticsearch",
            recreate_schema=True,
            confirm=True,
        ),
    )

    success_count, errors = await async_bulk(
        client=client,
        actions=build_es_bulk_actions(index_name, chunks),
        refresh=True,
    )

    if errors:
        raise RuntimeError(f"ES bulk 写入存在错误: {errors}")

    return int(success_count)


async def upsert_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> int:
    index_name = settings.elasticsearch_index_name
    await ensure_es_index(client=client, settings=settings)

    success_count, errors = await async_bulk(
        client=client,
        actions=build_es_bulk_actions(index_name, chunks),
        refresh=True,
    )

    if errors:
        raise RuntimeError(f"ES bulk upsert 存在错误: {errors}")

    return int(success_count)


async def delete_es_docs_by_doc_ids(
    client: AsyncElasticsearch,
    settings: Settings,
    doc_ids: list[str],
) -> dict[str, Any]:
    await ensure_es_index(client=client, settings=settings)

    if not doc_ids:
        return {"deleted": 0}

    result = await client.delete_by_query(
        index=settings.elasticsearch_index_name,
        body={
            "query": {
                "terms": {
                    "metadata.doc_id": doc_ids,
                }
            }
        },
        conflicts="proceed",
        refresh=True,
    )
    return dict(result)


async def replace_docs_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> tuple[int, dict[str, Any]]:
    doc_ids = collect_doc_ids(chunks)
    delete_result = await delete_es_docs_by_doc_ids(
        client=client,
        settings=settings,
        doc_ids=doc_ids,
    )
    success_count = await upsert_es_index(
        client=client,
        settings=settings,
        chunks=chunks,
    )
    return success_count, delete_result


def build_milvus_rows(
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> list[dict[str, Any]]:
    return [
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


def recreate_milvus_collection(
    client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> dict:
    collection_name = settings.milvus_collection_name

    reset_milvus_collection(
        client=client,
        settings=settings,
        options=StoreResetOptions(
            target="milvus",
            recreate_schema=True,
            confirm=True,
        ),
    )

    result = client.insert(
        collection_name=collection_name,
        data=build_milvus_rows(settings, chunks, vectors),
    )

    client.flush(collection_name=collection_name)
    client.load_collection(collection_name=collection_name)

    return result


def ensure_milvus_collection(
    client: MilvusClient,
    settings: Settings,
) -> None:
    collection_name = settings.milvus_collection_name

    if client.has_collection(collection_name):
        client.load_collection(collection_name=collection_name)
        return

    client.create_collection(
        collection_name=collection_name,
        schema=build_milvus_schema(settings),
        index_params=build_milvus_index_params(settings),
    )
    client.load_collection(collection_name=collection_name)


def upsert_milvus_collection(
    client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> dict:
    collection_name = settings.milvus_collection_name
    ensure_milvus_collection(client=client, settings=settings)

    result = client.upsert(
        collection_name=collection_name,
        data=build_milvus_rows(settings, chunks, vectors),
    )

    client.flush(collection_name=collection_name)
    client.load_collection(collection_name=collection_name)

    return result


def delete_milvus_docs_by_doc_ids(
    client: MilvusClient,
    settings: Settings,
    doc_ids: list[str],
) -> dict[str, Any]:
    ensure_milvus_collection(client=client, settings=settings)

    if not doc_ids:
        return {"delete_count": 0}

    quoted_doc_ids = ", ".join(
        f'"{escape_milvus_string(doc_id)}"' for doc_id in doc_ids
    )
    filter_expr = f'{MILVUS_DOC_ID_FIELD} in [{quoted_doc_ids}]'

    result = client.delete(
        collection_name=settings.milvus_collection_name,
        filter=filter_expr,
    )
    client.flush(collection_name=settings.milvus_collection_name)
    client.load_collection(collection_name=settings.milvus_collection_name)
    return result


def replace_docs_milvus_collection(
    client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    doc_ids = collect_doc_ids(chunks)
    delete_result = delete_milvus_docs_by_doc_ids(
        client=client,
        settings=settings,
        doc_ids=doc_ids,
    )
    upsert_result = upsert_milvus_collection(
        client=client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
    )
    return upsert_result, delete_result


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
                "write_mode": "recreate",
            },
        ),
        milvus=StoreWriteResult(
            store_name="milvus",
            success_count=len(chunks),
            detail={
                "collection_name": settings.milvus_collection_name,
                "write_mode": "recreate",
                "insert_result": milvus_insert_result,
            },
        ),
    )

# 增量写入 如果文档改动内容过多导致chunk index变动，会导致变动的chunk index 之后的chunk全部重新写入，并且旧的chunk 没有处理
async def upsert_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)

    es_success_count = await upsert_es_index(
        client=elasticsearch_client,
        settings=settings,
        chunks=chunks,
    )

    milvus_upsert_result = upsert_milvus_collection(
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
                "write_mode": "upsert",
            },
        ),
        milvus=StoreWriteResult(
            store_name="milvus",
            success_count=len(chunks),
            detail={
                "collection_name": settings.milvus_collection_name,
                "write_mode": "upsert",
                "upsert_result": milvus_upsert_result,
            },
        ),
    )

# 文档级替换：先按 doc_id 删除旧 chunks，再写入本次新 chunks。
async def replace_docs_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)
    doc_ids = collect_doc_ids(chunks)

    es_success_count, es_delete_result = await replace_docs_es_index(
        client=elasticsearch_client,
        settings=settings,
        chunks=chunks,
    )

    milvus_upsert_result, milvus_delete_result = replace_docs_milvus_collection(
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
                "write_mode": "replace_docs",
                "doc_ids": doc_ids,
                "delete_result": es_delete_result,
            },
        ),
        milvus=StoreWriteResult(
            store_name="milvus",
            success_count=len(chunks),
            detail={
                "collection_name": settings.milvus_collection_name,
                "write_mode": "replace_docs",
                "doc_ids": doc_ids,
                "delete_result": milvus_delete_result,
                "upsert_result": milvus_upsert_result,
            },
        ),
    )


async def write_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> DualStoreWriteResult:
    mode = get_ingestion_write_mode(settings)
    # 删除现有结构 数据，重新写入
    if mode == "recreate":
        return await recreate_rag_stores(
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            settings=settings,
            chunks=chunks,
            vectors=vectors,
        )
    # 文档级替换：先按 doc_id 删除旧 chunks，再写入本次新 chunks。
    # 适合文档内容变化导致 chunk 数量、chunk_index 或 chunk_id 变化的场景。
    if mode == "replace_docs":
        return await replace_docs_rag_stores(
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            settings=settings,
            chunks=chunks,
            vectors=vectors,
        )
    # 增量写入 如果文档改动内容过多导致chunk index变动，会导致变动的chunk index 之后的chunk全部重新写入，并且旧的chunk 没有处理
    return await upsert_rag_stores(
        elasticsearch_client=elasticsearch_client,
        milvus_client=milvus_client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
    )
