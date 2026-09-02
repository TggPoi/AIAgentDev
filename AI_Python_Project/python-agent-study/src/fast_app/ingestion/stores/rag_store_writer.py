from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
from typing import Any, Literal

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk, async_scan
from pymilvus import AsyncMilvusClient

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.stores.rag_store_admin import (
    StoreResetOptions,
    reset_es_index,
    reset_milvus_collection,
    verify_es_ik_analyzers,
)
from fast_app.ingestion.stores.rag_store_schema import (
    ES_CONTENT_FIELD,
    ES_DOC_ID_FIELD,
    ES_SEARCH_TEXT_FIELD,
    ES_RECORD_TYPE_FIELD,
    ES_LOGICAL_PARENT_ID_FIELD,
    ES_PHYSICAL_PARENT_ID_FIELD,
    ES_PHYSICAL_RECORD_ID_FIELD,
    ES_CREATED_AT_FIELD,
    ES_ID_FIELD,
    ES_METADATA_FIELD,
    ES_LOGICAL_RECORD_ID_FIELD,
    ES_SOURCE_ID_FIELD,
    ES_SOURCE_REVISION_FIELD,
    ES_VALID_FROM_VERSION_FIELD,
    ES_VALID_TO_VERSION_FIELD,
    ES_SOURCE_FIELD,
    ES_TITLE_FIELD,
    MILVUS_CHUNK_INDEX_FIELD,
    MILVUS_DOC_ID_FIELD,
    MILVUS_DOCUMENT_TYPE_FIELD,
    MILVUS_METADATA_FIELD,
    MILVUS_PHYSICAL_RECORD_ID_FIELD,
    MILVUS_LOGICAL_RECORD_ID_FIELD,
    MILVUS_RECORD_TYPE_FIELD,
    MILVUS_LOGICAL_PARENT_ID_FIELD,
    MILVUS_PHYSICAL_PARENT_ID_FIELD,
    MILVUS_SOURCE_ID_FIELD,
    MILVUS_SOURCE_REVISION_FIELD,
    MILVUS_VALID_FROM_VERSION_FIELD,
    MILVUS_VALID_TO_VERSION_FIELD,
    MILVUS_SOURCE_FIELD,
    MILVUS_SOURCE_PATH_FIELD,
    MILVUS_TITLE_FIELD,
    build_es_mapping,
    build_es_mappings,
    build_milvus_index_params,
    build_milvus_schema,
)
from fast_app.ingestion.processing.markdown_hierarchy import (
    MARKDOWN_CHILD_RECORD_TYPE,
    MARKDOWN_PARENT_RECORD_TYPE,
    MarkdownParentChunk,
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


def validate_parent_write_inputs(parents: list[MarkdownParentChunk]) -> None:
    parent_ids = [parent.id for parent in parents]
    if len(parent_ids) != len(set(parent_ids)):
        raise RuntimeError("写入 store 失败: parent.id 存在重复")
    for parent in parents:
        if parent.metadata.get("parent_id") != parent.id:
            raise RuntimeError(f"父块 parent_id 不一致: {parent.id}")
        for key in (
            "doc_id",
            "source_path",
            "document_type",
            "visibility",
            "allowed_departments",
            "allowed_users",
            "record_type",
        ):
            if key not in parent.metadata:
                raise RuntimeError(f"父块缺少 metadata.{key}: {parent.id}")


def validate_markdown_hierarchy_inputs(
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk],
) -> None:
    markdown_children = [
        chunk
        for chunk in chunks
        if chunk.metadata.get("record_type") == MARKDOWN_CHILD_RECORD_TYPE
    ]
    if not markdown_children and not parents:
        return
    parent_map = {parent.id: parent for parent in parents}
    child_parent_ids: set[str] = set()
    for child in markdown_children:
        parent_id = str(child.metadata.get("parent_id") or "")
        parent = parent_map.get(parent_id)
        if parent is None:
            raise RuntimeError(f"Markdown child 缺少父块: {child.id}")
        child_parent_ids.add(parent_id)
        if (
            parent.metadata.get("record_type") != MARKDOWN_PARENT_RECORD_TYPE
            or parent.metadata.get("doc_id") != child.metadata.get("doc_id")
            or parent.metadata.get("chunk_strategy_version")
            != child.metadata.get("chunk_strategy_version")
            or any(
                parent.metadata.get(key) != child.metadata.get(key)
                for key in (
                    "visibility",
                    "allowed_departments",
                    "allowed_users",
                    "permission_source",
                )
            )
        ):
            raise RuntimeError(f"Markdown 父子 metadata 不一致: {child.id}")
    parent_ids = set(parent_map)
    if parent_ids != child_parent_ids:
        raise RuntimeError("Markdown 父块存在无子块记录")
    for parent in parents:
        if (
            parent.metadata.get("content_hash")
            != hashlib.sha256(parent.content.encode("utf-8")).hexdigest()
        ):
            raise RuntimeError(f"Markdown 父块 content_hash 不一致: {parent.id}")


def validate_vector_dimensions(
    settings: Settings,
    vectors: list[list[float]],
) -> None:
    if any(len(vector) != settings.embedding_dim for vector in vectors):
        raise RuntimeError("写入 store 失败: embedding 向量维度不匹配")


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
        # 旧索引不会经过 create；显式补充可兼容新增 keyword metadata 字段。
        mappings = build_es_mappings()
        await client.indices.put_mapping(
            index=settings.elasticsearch_index_name,
            properties=mappings["properties"],
        )
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
                ES_PHYSICAL_RECORD_ID_FIELD: str(
                    chunk.metadata.get("physical_record_id") or chunk.id
                ),
                ES_DOC_ID_FIELD: str(chunk.metadata["doc_id"]),
                ES_CONTENT_FIELD: chunk.content,
                ES_SEARCH_TEXT_FIELD: chunk.search_text or chunk.content,
                ES_RECORD_TYPE_FIELD: chunk.metadata.get(
                    "record_type", "chunk"
                ),
                ES_LOGICAL_PARENT_ID_FIELD: str(
                    chunk.metadata.get("logical_parent_id") or ""
                ),
                ES_PHYSICAL_PARENT_ID_FIELD: str(
                    chunk.metadata.get("physical_parent_id") or ""
                ),
                ES_TITLE_FIELD: chunk.title,
                ES_SOURCE_FIELD: chunk.source,
                ES_LOGICAL_RECORD_ID_FIELD: str(
                    chunk.metadata.get("logical_record_id") or chunk.id
                ),
                ES_SOURCE_ID_FIELD: str(chunk.metadata.get("source_id") or ""),
                ES_SOURCE_REVISION_FIELD: str(
                    chunk.metadata.get("source_revision") or ""
                ),
                ES_VALID_FROM_VERSION_FIELD: int(
                    chunk.metadata.get("valid_from_version", 0)
                ),
                ES_VALID_TO_VERSION_FIELD: int(
                    chunk.metadata.get("valid_to_version", 0)
                ),
                ES_METADATA_FIELD: chunk.metadata,
                ES_CREATED_AT_FIELD: now,
            },
        }
        for chunk in chunks
    ]


def build_es_parent_bulk_actions(
    index_name: str,
    parents: list[MarkdownParentChunk],
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    return [
        {
            "_op_type": "index",
            "_index": index_name,
            "_id": parent.id,
            "_source": {
                ES_ID_FIELD: parent.id,
                ES_PHYSICAL_RECORD_ID_FIELD: str(
                    parent.metadata.get("physical_record_id") or parent.id
                ),
                ES_DOC_ID_FIELD: str(parent.metadata["doc_id"]),
                ES_CONTENT_FIELD: parent.content,
                ES_SEARCH_TEXT_FIELD: parent.content,
                ES_RECORD_TYPE_FIELD: parent.metadata["record_type"],
                ES_LOGICAL_PARENT_ID_FIELD: str(
                    parent.metadata.get("logical_parent_id") or ""
                ),
                ES_PHYSICAL_PARENT_ID_FIELD: str(
                    parent.metadata.get("physical_parent_id") or ""
                ),
                ES_TITLE_FIELD: parent.title,
                ES_SOURCE_FIELD: parent.source,
                ES_LOGICAL_RECORD_ID_FIELD: str(
                    parent.metadata.get("logical_record_id") or parent.id
                ),
                ES_SOURCE_ID_FIELD: str(parent.metadata.get("source_id") or ""),
                ES_SOURCE_REVISION_FIELD: str(
                    parent.metadata.get("source_revision") or ""
                ),
                ES_VALID_FROM_VERSION_FIELD: int(
                    parent.metadata.get("valid_from_version", 0)
                ),
                ES_VALID_TO_VERSION_FIELD: int(
                    parent.metadata.get("valid_to_version", 0)
                ),
                ES_METADATA_FIELD: parent.metadata,
                ES_CREATED_AT_FIELD: now,
            },
        }
        for parent in parents
    ]


async def recreate_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk] | None = None,
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

    parent_records = parents or []
    success_count, errors = await async_bulk(
        client=client,
        actions=[
            *build_es_bulk_actions(index_name, chunks),
            *build_es_parent_bulk_actions(index_name, parent_records),
        ],
        refresh=True,
    )

    if errors:
        raise RuntimeError(f"ES bulk 写入存在错误: {errors}")

    return int(success_count)


async def upsert_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk] | None = None,
) -> int:
    index_name = settings.elasticsearch_index_name
    await ensure_es_index(client=client, settings=settings)

    success_count, errors = await async_bulk(
        client=client,
        actions=[
            *build_es_bulk_actions(index_name, chunks),
            *build_es_parent_bulk_actions(index_name, parents or []),
        ],
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


async def close_es_docs_for_version(
    *,
    client: AsyncElasticsearch,
    settings: Settings,
    doc_ids: list[str],
    valid_to_version: int,
) -> dict[str, Any]:
    """关闭旧 ES 记录，但保留它们供已冻结旧版本的请求读取。"""

    if not doc_ids:
        return {"updated": 0}
    await ensure_es_index(client=client, settings=settings)
    result = await client.update_by_query(
        index=settings.elasticsearch_index_name,
        body={
            "script": {
                "lang": "painless",
                "source": (
                    "ctx._source.valid_to_version = params.version; "
                    "ctx._source.metadata.valid_to_version = params.version"
                ),
                "params": {"version": valid_to_version},
            },
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"metadata.doc_id": doc_ids}},
                        {"term": {"valid_to_version": 0}},
                    ]
                }
            },
        },
        conflicts="proceed",
        refresh=True,
    )
    return dict(result)


async def replace_docs_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk] | None = None,
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
        parents=parents,
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
            MILVUS_PHYSICAL_RECORD_ID_FIELD: str(
                chunk.metadata.get("physical_record_id") or chunk.id
            ),
            MILVUS_LOGICAL_RECORD_ID_FIELD: str(
                chunk.metadata.get("logical_record_id") or chunk.id
            ),
            MILVUS_RECORD_TYPE_FIELD: str(
                chunk.metadata.get("record_type") or "chunk"
            ),
            MILVUS_LOGICAL_PARENT_ID_FIELD: str(
                chunk.metadata.get("logical_parent_id") or ""
            ),
            MILVUS_PHYSICAL_PARENT_ID_FIELD: str(
                chunk.metadata.get("physical_parent_id") or ""
            ),
            MILVUS_SOURCE_ID_FIELD: str(chunk.metadata.get("source_id") or ""),
            MILVUS_SOURCE_REVISION_FIELD: str(
                chunk.metadata.get("source_revision") or ""
            ),
            MILVUS_VALID_FROM_VERSION_FIELD: int(
                chunk.metadata.get("valid_from_version", 0)
            ),
            MILVUS_VALID_TO_VERSION_FIELD: int(
                chunk.metadata.get("valid_to_version", 0)
            ),
            MILVUS_METADATA_FIELD: chunk.metadata,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]


async def recreate_milvus_collection(
    client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> dict:
    collection_name = settings.milvus_collection_name

    await reset_milvus_collection(
        client=client,
        settings=settings,
        options=StoreResetOptions(
            target="milvus",
            recreate_schema=True,
            confirm=True,
        ),
    )

    result = await client.insert(
        collection_name=collection_name,
        data=build_milvus_rows(settings, chunks, vectors),
    )

    await client.flush(collection_name=collection_name)
    await client.load_collection(collection_name=collection_name)

    return result


async def ensure_milvus_collection(
    client: AsyncMilvusClient,
    settings: Settings,
) -> None:
    collection_name = settings.milvus_collection_name

    if await client.has_collection(collection_name):
        await client.load_collection(collection_name=collection_name)
        return

    await client.create_collection(
        collection_name=collection_name,
        schema=build_milvus_schema(settings),
        index_params=build_milvus_index_params(settings),
    )
    await client.load_collection(collection_name=collection_name)


async def upsert_milvus_collection(
    client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> dict:
    collection_name = settings.milvus_collection_name
    await ensure_milvus_collection(client=client, settings=settings)

    result = await client.upsert(
        collection_name=collection_name,
        data=build_milvus_rows(settings, chunks, vectors),
    )

    await client.flush(collection_name=collection_name)
    await client.load_collection(collection_name=collection_name)

    return result


async def delete_milvus_docs_by_doc_ids(
    client: AsyncMilvusClient,
    settings: Settings,
    doc_ids: list[str],
) -> dict[str, Any]:
    await ensure_milvus_collection(client=client, settings=settings)

    if not doc_ids:
        return {"delete_count": 0}

    quoted_doc_ids = ", ".join(
        f'"{escape_milvus_string(doc_id)}"' for doc_id in doc_ids
    )
    filter_expr = f'{MILVUS_DOC_ID_FIELD} in [{quoted_doc_ids}]'

    result = await client.delete(
        collection_name=settings.milvus_collection_name,
        filter=filter_expr,
    )
    await client.flush(collection_name=settings.milvus_collection_name)
    await client.load_collection(collection_name=settings.milvus_collection_name)
    return result


async def close_milvus_docs_for_version(
    *,
    client: AsyncMilvusClient,
    settings: Settings,
    doc_ids: list[str],
    valid_to_version: int,
) -> int:
    """查询并 upsert 完整 Milvus 行，以关闭旧子块版本。"""

    if not doc_ids:
        return 0
    await ensure_milvus_collection(client=client, settings=settings)
    quoted_doc_ids = ", ".join(
        f'"{escape_milvus_string(doc_id)}"' for doc_id in doc_ids
    )
    filter_expr = (
        f"{MILVUS_DOC_ID_FIELD} in [{quoted_doc_ids}] and "
        f"{MILVUS_VALID_TO_VERSION_FIELD} == 0"
    )
    output_fields = [
        settings.milvus_id_field,
        settings.milvus_vector_field,
        settings.milvus_content_field,
        MILVUS_SOURCE_FIELD,
        MILVUS_TITLE_FIELD,
        MILVUS_DOC_ID_FIELD,
        MILVUS_SOURCE_PATH_FIELD,
        MILVUS_DOCUMENT_TYPE_FIELD,
        MILVUS_CHUNK_INDEX_FIELD,
        MILVUS_PHYSICAL_RECORD_ID_FIELD,
        MILVUS_LOGICAL_RECORD_ID_FIELD,
        MILVUS_RECORD_TYPE_FIELD,
        MILVUS_LOGICAL_PARENT_ID_FIELD,
        MILVUS_PHYSICAL_PARENT_ID_FIELD,
        MILVUS_SOURCE_ID_FIELD,
        MILVUS_SOURCE_REVISION_FIELD,
        MILVUS_VALID_FROM_VERSION_FIELD,
        MILVUS_VALID_TO_VERSION_FIELD,
        MILVUS_METADATA_FIELD,
    ]
    updated = 0
    while True:
        rows = await client.query(
            collection_name=settings.milvus_collection_name,
            filter=filter_expr,
            output_fields=output_fields,
            limit=1000,
        )
        if not rows:
            break
        for row in rows:
            row[MILVUS_VALID_TO_VERSION_FIELD] = valid_to_version
            metadata = dict(row.get(MILVUS_METADATA_FIELD) or {})
            metadata["valid_to_version"] = valid_to_version
            row[MILVUS_METADATA_FIELD] = metadata
        await client.upsert(
            collection_name=settings.milvus_collection_name,
            data=rows,
        )
        updated += len(rows)
    if updated:
        await client.flush(collection_name=settings.milvus_collection_name)
    return updated


async def close_rag_docs_for_version(
    *,
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    doc_ids: list[str],
    valid_to_version: int,
) -> None:
    await close_es_docs_for_version(
        client=elasticsearch_client,
        settings=settings,
        doc_ids=doc_ids,
        valid_to_version=valid_to_version,
    )
    await close_milvus_docs_for_version(
        client=milvus_client,
        settings=settings,
        doc_ids=doc_ids,
        valid_to_version=valid_to_version,
    )


async def replace_docs_milvus_collection(
    client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    doc_ids = collect_doc_ids(chunks)
    delete_result = await delete_milvus_docs_by_doc_ids(
        client=client,
        settings=settings,
        doc_ids=doc_ids,
    )
    upsert_result = await upsert_milvus_collection(
        client=client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
    )
    return upsert_result, delete_result


async def verify_markdown_store_convergence(
    *,
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk],
) -> None:
    """验证 replace_docs 后 ES 父子记录与 Milvus 子块完全收敛。"""

    expected_es = {
        **{chunk.id: chunk.metadata for chunk in chunks},
        **{parent.id: parent.metadata for parent in parents},
    }
    actual_es: dict[str, dict[str, Any]] = {}
    doc_ids = collect_doc_ids(chunks)
    async for hit in async_scan(
        client=elasticsearch_client,
        index=settings.elasticsearch_index_name,
        query={"query": {"terms": {"metadata.doc_id": doc_ids}}},
        _source=[ES_ID_FIELD, ES_METADATA_FIELD],
    ):
        source = hit.get("_source", {})
        record_id = str(source.get(ES_ID_FIELD) or hit.get("_id") or "")
        if record_id:
            actual_es[record_id] = dict(source.get(ES_METADATA_FIELD) or {})
    if set(actual_es) != set(expected_es):
        raise RuntimeError("Markdown ES 父子 ID 集合未收敛")

    for record_id, expected_metadata in expected_es.items():
        actual_metadata = actual_es[record_id]
        for key in (
            "doc_id",
            "parent_id",
            "record_type",
            "content_hash",
            "chunk_strategy_version",
            "visibility",
            "allowed_departments",
            "allowed_users",
            "permission_source",
        ):
            if expected_metadata.get(key) != actual_metadata.get(key):
                raise RuntimeError(
                    f"Markdown ES metadata.{key} 未收敛: {record_id}"
                )

    expected_milvus = {chunk.id: chunk.metadata for chunk in chunks}
    actual_milvus: dict[str, dict[str, Any]] = {}
    quoted_doc_ids = ", ".join(
        f'"{escape_milvus_string(doc_id)}"' for doc_id in doc_ids
    )
    offset = 0
    while True:
        rows = await milvus_client.query(
            collection_name=settings.milvus_collection_name,
            filter=f"{MILVUS_DOC_ID_FIELD} in [{quoted_doc_ids}]",
            output_fields=[
                settings.milvus_id_field,
                settings.milvus_vector_field,
                MILVUS_METADATA_FIELD,
            ],
            limit=1000,
            offset=offset,
        )
        for row in rows:
            chunk_id = str(row.get(settings.milvus_id_field) or "")
            vector = row.get(settings.milvus_vector_field)
            if not chunk_id or vector is None:
                raise RuntimeError("Markdown Milvus 记录缺少 ID 或向量")
            if len(vector) != settings.embedding_dim:
                raise RuntimeError(f"Markdown Milvus 向量维度未收敛: {chunk_id}")
            actual_milvus[chunk_id] = dict(row.get(MILVUS_METADATA_FIELD) or {})
        if len(rows) < 1000:
            break
        offset += len(rows)
    if set(actual_milvus) != set(expected_milvus):
        raise RuntimeError("Markdown Milvus 子块 ID 集合未收敛")
    for chunk_id, expected_metadata in expected_milvus.items():
        actual_metadata = actual_milvus[chunk_id]
        for key in (
            "doc_id",
            "parent_id",
            "record_type",
            "content_hash",
            "chunk_strategy_version",
            "visibility",
            "allowed_departments",
            "allowed_users",
        ):
            if expected_metadata.get(key) != actual_metadata.get(key):
                raise RuntimeError(
                    f"Markdown Milvus metadata.{key} 未收敛: {chunk_id}"
                )


# 双链路 写入 es milvus数据库入口
async def recreate_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
    parents: list[MarkdownParentChunk] | None = None,
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)
    validate_parent_write_inputs(parents or [])
    validate_markdown_hierarchy_inputs(chunks, parents or [])
    validate_vector_dimensions(settings, vectors)

    es_success_count = (
        await recreate_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
            parents=parents,
        )
        if parents is not None
        else await recreate_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
        )
    )

    milvus_insert_result = await recreate_milvus_collection(
        client=milvus_client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
    )
    if parents:
        await verify_markdown_store_convergence(
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            settings=settings,
            chunks=chunks,
            parents=parents,
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
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
    parents: list[MarkdownParentChunk] | None = None,
    verify_convergence: bool = True,
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)
    validate_parent_write_inputs(parents or [])
    validate_markdown_hierarchy_inputs(chunks, parents or [])
    validate_vector_dimensions(settings, vectors)

    es_success_count = (
        await upsert_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
            parents=parents,
        )
        if parents is not None
        else await upsert_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
        )
    )

    milvus_upsert_result = await upsert_milvus_collection(
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
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
    parents: list[MarkdownParentChunk] | None = None,
    verify_convergence: bool = True,
) -> DualStoreWriteResult:
    validate_store_write_inputs(chunks, vectors)
    validate_parent_write_inputs(parents or [])
    validate_markdown_hierarchy_inputs(chunks, parents or [])
    validate_vector_dimensions(settings, vectors)
    doc_ids = collect_doc_ids(chunks)

    es_success_count, es_delete_result = (
        await replace_docs_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
            parents=parents,
        )
        if parents is not None
        else await replace_docs_es_index(
            client=elasticsearch_client,
            settings=settings,
            chunks=chunks,
        )
    )

    milvus_upsert_result, milvus_delete_result = (
        await replace_docs_milvus_collection(
            client=milvus_client,
            settings=settings,
            chunks=chunks,
            vectors=vectors,
        )
    )
    if parents and verify_convergence:
        await verify_markdown_store_convergence(
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            settings=settings,
            chunks=chunks,
            parents=parents,
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
    milvus_client: AsyncMilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
    parents: list[MarkdownParentChunk] | None = None,
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
            parents=parents,
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
            parents=parents,
        )
    # 增量写入 如果文档改动内容过多导致chunk index变动，会导致变动的chunk index 之后的chunk全部重新写入，并且旧的chunk 没有处理
    return await upsert_rag_stores(
        elasticsearch_client=elasticsearch_client,
        milvus_client=milvus_client,
        settings=settings,
        chunks=chunks,
        vectors=vectors,
        parents=parents,
    )
