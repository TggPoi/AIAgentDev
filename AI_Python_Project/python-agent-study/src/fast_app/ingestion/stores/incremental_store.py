from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_scan
from pymilvus import MilvusClient

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.stores.rag_store_writer import (
    ensure_es_index,
    ensure_milvus_collection,
    escape_milvus_string,
    upsert_es_index,
    upsert_milvus_collection,
)


@dataclass(frozen=True)
class ExistingChunkState:
    """从一个检索存储读取到的 Chunk Hash metadata 和可选向量。"""

    metadata: dict[str, Any]
    vector: list[float] | None = None


@dataclass
class ChunkDiff:
    """目标 Chunk 与双存储现状比较后得到的最小写入集合。"""

    embed: list[KnowledgeChunk] = field(default_factory=list)
    reuse: list[tuple[KnowledgeChunk, list[float]]] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


async def load_es_chunk_states(
    client: AsyncElasticsearch,
    settings: Settings,
    doc_id: str,
) -> dict[str, ExistingChunkState]:
    """按 doc_id 流式读取 ES 中所有 Chunk 的身份和 Hash。"""

    await ensure_es_index(client, settings)
    result: dict[str, ExistingChunkState] = {}
    async for hit in async_scan(
        client=client,
        index=settings.elasticsearch_index_name,
        query={"query": {"term": {"metadata.doc_id": doc_id}}},
        _source=["id", "metadata"],
    ):
        source = hit.get("_source", {})
        chunk_id = str(source.get("id") or hit.get("_id") or "")
        if chunk_id:
            result[chunk_id] = ExistingChunkState(
                metadata=dict(source.get("metadata") or {})
            )
    return result


def load_milvus_chunk_states(
    client: MilvusClient,
    settings: Settings,
    doc_id: str,
) -> dict[str, ExistingChunkState]:
    """分页读取 Milvus metadata，并同时取回可复用的原向量。"""

    ensure_milvus_collection(client, settings)
    escaped = escape_milvus_string(doc_id)
    result: dict[str, ExistingChunkState] = {}
    offset = 0
    while True:
        rows = client.query(
            collection_name=settings.milvus_collection_name,
            filter=f'doc_id == "{escaped}"',
            output_fields=[
                settings.milvus_id_field,
                settings.milvus_vector_field,
                "metadata",
            ],
            limit=1000,
            offset=offset,
        )
        for row in rows:
            chunk_id = str(row.get(settings.milvus_id_field) or "")
            if chunk_id:
                result[chunk_id] = ExistingChunkState(
                    metadata=dict(row.get("metadata") or {}),
                    vector=(
                        list(row[settings.milvus_vector_field])
                        if row.get(settings.milvus_vector_field) is not None
                        else None
                    ),
                )
        if len(rows) < 1000:
            break
        offset += len(rows)
    return result


def build_chunk_diff(
    chunks: list[KnowledgeChunk],
    es_states: dict[str, ExistingChunkState],
    milvus_states: dict[str, ExistingChunkState],
    *,
    embedding_dim: int,
) -> ChunkDiff:
    """按 Chunk ID/content_hash/index_hash 计算增量写入和删除计划。"""

    new_by_id = {chunk.id: chunk for chunk in chunks}
    if len(new_by_id) != len(chunks):
        raise RuntimeError("Office 增量分块产生重复 chunk_id")

    counts = {
        "unchanged": 0,
        "metadata_only": 0,
        "added": 0,
        "changed": 0,
        "removed": 0,
        "repaired": 0,
        "embedded": 0,
    }
    diff = ChunkDiff(counts=counts)
    for chunk in chunks:
        es_state = es_states.get(chunk.id)
        milvus_state = milvus_states.get(chunk.id)
        content_hash = chunk.metadata["content_hash"]
        index_hash = chunk.metadata["index_hash"]
        both_match = (
            es_state is not None
            and milvus_state is not None
            and es_state.metadata.get("content_hash") == content_hash
            and milvus_state.metadata.get("content_hash") == content_hash
            and es_state.metadata.get("index_hash") == index_hash
            and milvus_state.metadata.get("index_hash") == index_hash
        )
        if both_match:
            counts["unchanged"] += 1
            continue

        if es_state is None and milvus_state is None:
            counts["added"] += 1
        elif es_state is None or milvus_state is None:
            counts["repaired"] += 1

        # metadata-only 更新只有在 Milvus 中存在正确维度的旧向量时才能免 Embedding。
        reusable_vector = milvus_state.vector if milvus_state is not None else None
        same_content = (
            (es_state is None or es_state.metadata.get("content_hash") == content_hash)
            and (
                milvus_state is None
                or milvus_state.metadata.get("content_hash") == content_hash
            )
        )
        if (
            same_content
            and reusable_vector is not None
            and len(reusable_vector) == embedding_dim
        ):
            counts["metadata_only"] += 1
            diff.reuse.append((chunk, reusable_vector))
        else:
            if es_state is not None or milvus_state is not None:
                counts["changed"] += 1
            diff.embed.append(chunk)

    diff.removed_ids = sorted(
        (set(es_states) | set(milvus_states)) - set(new_by_id)
    )
    counts["removed"] = len(diff.removed_ids)
    counts["embedded"] = len(diff.embed)
    return diff


async def apply_chunk_diff(
    *,
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    diff: ChunkDiff,
    embedded_vectors: list[list[float]],
) -> None:
    """先 Upsert 新增/变化/修复项，再删除目标版本已消失的 Chunk。"""

    if len(embedded_vectors) != len(diff.embed):
        raise RuntimeError("增量 Embedding 数量与待向量化 Chunk 不一致")

    chunks = [chunk for chunk, _ in diff.reuse] + diff.embed
    vectors = [vector for _, vector in diff.reuse] + embedded_vectors
    if chunks:
        await upsert_es_index(elasticsearch_client, settings, chunks)
        upsert_milvus_collection(milvus_client, settings, chunks, vectors)
    if diff.removed_ids:
        await delete_es_chunks_by_ids(
            elasticsearch_client, settings, diff.removed_ids
        )
        delete_milvus_chunks_by_ids(milvus_client, settings, diff.removed_ids)


async def delete_es_chunks_by_ids(
    client: AsyncElasticsearch,
    settings: Settings,
    chunk_ids: list[str],
) -> None:
    """按稳定 ES `_id` 批量删除已消失的 Chunk。"""

    if not chunk_ids:
        return
    await ensure_es_index(client, settings)
    await client.delete_by_query(
        index=settings.elasticsearch_index_name,
        body={"query": {"ids": {"values": chunk_ids}}},
        conflicts="proceed",
        refresh=True,
    )


def delete_milvus_chunks_by_ids(
    client: MilvusClient,
    settings: Settings,
    chunk_ids: list[str],
) -> None:
    """按 Milvus 稳定主键删除 Chunk，并刷新可查询状态。"""

    if not chunk_ids:
        return
    ensure_milvus_collection(client, settings)
    client.delete(
        collection_name=settings.milvus_collection_name,
        ids=chunk_ids,
    )
    client.flush(collection_name=settings.milvus_collection_name)
    client.load_collection(collection_name=settings.milvus_collection_name)


async def verify_chunk_convergence(
    *,
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> None:
    """验证两个存储的 ID、Hash 和向量维度与目标版本完全一致。"""

    if not chunks:
        raise RuntimeError("Office 文档不能收敛为空 Chunk 集合")
    doc_id = str(chunks[0].metadata["doc_id"])
    es_states = await load_es_chunk_states(elasticsearch_client, settings, doc_id)
    milvus_states = load_milvus_chunk_states(milvus_client, settings, doc_id)
    expected = {chunk.id: chunk for chunk in chunks}
    if set(es_states) != set(expected) or set(milvus_states) != set(expected):
        raise RuntimeError("ES/Milvus Chunk ID 集合未收敛")
    for chunk_id, chunk in expected.items():
        for store_name, state in (
            ("ES", es_states[chunk_id]),
            ("Milvus", milvus_states[chunk_id]),
        ):
            if (
                state.metadata.get("content_hash") != chunk.metadata["content_hash"]
                or state.metadata.get("index_hash") != chunk.metadata["index_hash"]
            ):
                raise RuntimeError(f"{store_name} Chunk Hash 未收敛: {chunk_id}")
        vector = milvus_states[chunk_id].vector
        if vector is None or len(vector) != settings.embedding_dim:
            raise RuntimeError(f"Milvus Chunk 向量维度不匹配: {chunk_id}")


__all__ = [
    "ChunkDiff",
    "apply_chunk_diff",
    "build_chunk_diff",
    "load_es_chunk_states",
    "load_milvus_chunk_states",
    "verify_chunk_convergence",
]
