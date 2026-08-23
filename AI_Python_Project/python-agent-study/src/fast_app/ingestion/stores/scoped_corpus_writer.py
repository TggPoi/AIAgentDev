"""只变更一个 local corpus ownership 范围的双 Store 提交与恢复。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from elasticsearch.helpers import async_bulk, async_scan

from fast_app.core.config import Settings
from fast_app.ingestion.processing.local_corpus_builder import LocalCorpusPrebuildResult
from fast_app.ingestion.stores.incremental_store import (
    delete_es_chunks_by_ids,
    delete_milvus_chunks_by_ids,
)
from fast_app.ingestion.stores.rag_store_schema import (
    ES_SOURCE_ID_FIELD,
    MILVUS_SOURCE_ID_FIELD,
)
from fast_app.ingestion.stores.rag_store_writer import (
    ensure_es_index,
    ensure_milvus_collection,
    escape_milvus_string,
    upsert_rag_stores,
)
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock


class ScopedCorpusCommitError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalCorpusManifestStore:
    def __init__(self, root: str | Path = "runtime/local-corpus") -> None:
        self.root = Path(root)
        self.active_path = self.root / "active-manifest.json"
        self.journal_dir = self.root / "journals"
        self.recovery_dir = self.root / "recovery"

    def read_active(self) -> dict | None:
        try:
            return json.loads(self.active_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def write_active(self, value: dict) -> None:
        _atomic_json_write(self.active_path, value)

    def write_journal(self, generation: str, value: dict) -> Path:
        path = self.journal_dir / f"{generation}.json"
        _atomic_json_write(path, value)
        return path

    def write_recovery(self, generation: str, value: dict) -> Path:
        path = self.recovery_dir / f"{generation}.json"
        _atomic_json_write(path, value)
        return path


class ScopedLocalCorpusWriter:
    """预构建完成后，在一个全局 Store 临界区提交 local corpus。"""

    def __init__(
        self,
        *,
        settings: Settings,
        elasticsearch_client,
        milvus_client,
        mutation_lock: StoreMutationLock,
        manifest_store: LocalCorpusManifestStore | None = None,
    ) -> None:
        self.settings = settings
        self.elasticsearch = elasticsearch_client
        self.milvus = milvus_client
        self.lock = mutation_lock
        self.manifests = manifest_store or LocalCorpusManifestStore()

    async def commit(
        self,
        prebuild: LocalCorpusPrebuildResult,
        *,
        report_sha256: str,
    ) -> dict:
        if prebuild.local_corpus_id != self.settings.local_corpus_id:
            raise ScopedCorpusCommitError(
                "LOCAL_CORPUS_ID_MISMATCH", "prebuild 与运行时 local_corpus_id 不一致"
            )
        generation = uuid4().hex
        target_manifest = {
            "schema_version": "local-corpus-manifest.v1",
            "generation": generation,
            "local_corpus_id": prebuild.local_corpus_id,
            "source_id": f"local:{prebuild.local_corpus_id}",
            "report_sha256": report_sha256,
            "created_at": datetime.now(UTC).isoformat(),
            "documents": prebuild.manifest_documents,
            "es_record_ids": sorted(
                [*(item.id for item in prebuild.parents), *(item.id for item in prebuild.chunks)]
            ),
            "milvus_record_ids": sorted(item.id for item in prebuild.chunks),
        }
        async with self.lock.hold():
            old_manifest = self.manifests.read_active()
            if old_manifest and old_manifest.get("local_corpus_id") != prebuild.local_corpus_id:
                raise ScopedCorpusCommitError(
                    "LOCAL_CORPUS_OWNERSHIP_MIGRATION_REQUIRED",
                    "现有 manifest 使用不同 local_corpus_id",
                )
            snapshot = await self._snapshot(prebuild.local_corpus_id)
            recovery_path = self.manifests.write_recovery(
                generation, {"old_manifest": old_manifest, **snapshot}
            )
            journal = {
                "schema_version": "local-corpus-journal.v1",
                "generation": generation,
                "state": "prepared",
                "report_sha256": report_sha256,
                "recovery_path": recovery_path.as_posix(),
                "target_manifest": target_manifest,
            }
            self.manifests.write_journal(generation, journal)
            try:
                journal["state"] = "mutating"
                self.manifests.write_journal(generation, journal)
                await upsert_rag_stores(
                    elasticsearch_client=self.elasticsearch,
                    milvus_client=self.milvus,
                    settings=self.settings,
                    chunks=prebuild.chunks,
                    vectors=prebuild.vectors,
                    parents=prebuild.parents,
                    verify_convergence=False,
                )
                target_es = set(target_manifest["es_record_ids"])
                target_milvus = set(target_manifest["milvus_record_ids"])
                await delete_es_chunks_by_ids(
                    self.elasticsearch,
                    self.settings,
                    sorted(set(snapshot["es_record_ids"]) - target_es),
                )
                delete_milvus_chunks_by_ids(
                    self.milvus,
                    self.settings,
                    sorted(set(snapshot["milvus_record_ids"]) - target_milvus),
                )
                await self._verify(target_manifest)
                journal["state"] = "stores_verified"
                self.manifests.write_journal(generation, journal)
                self.manifests.write_active(target_manifest)
                journal["state"] = "manifest_published"
                self.manifests.write_journal(generation, journal)
                journal["state"] = "committed"
                self.manifests.write_journal(generation, journal)
                return target_manifest
            except Exception as exc:
                await self._restore(snapshot, old_manifest=old_manifest)
                journal["state"] = "rolled_back"
                journal["error_type"] = type(exc).__name__
                self.manifests.write_journal(generation, journal)
                raise ScopedCorpusCommitError(
                    "LOCAL_CORPUS_COMMIT_FAILED", "本地语料提交失败，已尝试恢复旧快照"
                ) from exc

    async def recover(self, generation: str) -> str:
        journal_path = self.manifests.journal_dir / f"{generation}.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("state") in {"committed", "rolled_back"}:
            return str(journal["state"])
        async with self.lock.hold():
            target = dict(journal["target_manifest"])
            active = self.manifests.read_active()
            if active and active.get("generation") == generation:
                try:
                    await self._verify(target)
                except Exception:
                    pass
                else:
                    journal["state"] = "committed"
                    self.manifests.write_journal(generation, journal)
                    return "committed"
            recovery = json.loads(
                Path(journal["recovery_path"]).read_text(encoding="utf-8")
            )
            await self._restore(recovery, old_manifest=recovery.get("old_manifest"))
            journal["state"] = "rolled_back"
            self.manifests.write_journal(generation, journal)
            return "rolled_back"

    async def _snapshot(self, local_corpus_id: str) -> dict:
        source_id = f"local:{local_corpus_id}"
        es_records: list[dict] = []
        if await self.elasticsearch.indices.exists(index=self.settings.elasticsearch_index_name):
            async for hit in async_scan(
                client=self.elasticsearch,
                index=self.settings.elasticsearch_index_name,
                query={"query": {"term": {ES_SOURCE_ID_FIELD: source_id}}},
            ):
                es_records.append({"id": hit["_id"], "source": hit.get("_source", {})})
        milvus_records: list[dict] = []
        if self.milvus.has_collection(self.settings.milvus_collection_name):
            offset = 0
            while True:
                rows = self.milvus.query(
                    collection_name=self.settings.milvus_collection_name,
                    filter=(
                        f'{MILVUS_SOURCE_ID_FIELD} == '
                        f'"{escape_milvus_string(source_id)}"'
                    ),
                    output_fields=["*", self.settings.milvus_vector_field],
                    limit=1000,
                    offset=offset,
                )
                milvus_records.extend(rows)
                if len(rows) < 1000:
                    break
                offset += len(rows)
        return {
            "es_records": es_records,
            "milvus_records": milvus_records,
            "es_record_ids": [item["id"] for item in es_records],
            "milvus_record_ids": [
                str(item[self.settings.milvus_id_field]) for item in milvus_records
            ],
        }

    async def _verify(self, manifest: dict) -> None:
        snapshot = await self._snapshot(str(manifest["local_corpus_id"]))
        if set(snapshot["es_record_ids"]) != set(manifest["es_record_ids"]):
            raise ScopedCorpusCommitError("LOCAL_CORPUS_ES_NOT_CONVERGED", "ES ID 集合未收敛")
        if set(snapshot["milvus_record_ids"]) != set(manifest["milvus_record_ids"]):
            raise ScopedCorpusCommitError(
                "LOCAL_CORPUS_MILVUS_NOT_CONVERGED", "Milvus ID 集合未收敛"
            )

    async def _restore(self, snapshot: dict, *, old_manifest: dict | None) -> None:
        current = await self._snapshot(self.settings.local_corpus_id)
        await delete_es_chunks_by_ids(
            self.elasticsearch, self.settings, current["es_record_ids"]
        )
        delete_milvus_chunks_by_ids(
            self.milvus, self.settings, current["milvus_record_ids"]
        )
        if snapshot.get("es_records"):
            await ensure_es_index(self.elasticsearch, self.settings)
            await async_bulk(
                self.elasticsearch,
                [
                    {
                        "_op_type": "index",
                        "_index": self.settings.elasticsearch_index_name,
                        "_id": item["id"],
                        "_source": item["source"],
                    }
                    for item in snapshot["es_records"]
                ],
                refresh="wait_for",
            )
        if snapshot.get("milvus_records"):
            ensure_milvus_collection(self.milvus, self.settings)
            self.milvus.upsert(
                collection_name=self.settings.milvus_collection_name,
                data=snapshot["milvus_records"],
            )
            self.milvus.flush(collection_name=self.settings.milvus_collection_name)
        if old_manifest is not None:
            self.manifests.write_active(old_manifest)
        elif self.manifests.active_path.is_file():
            self.manifests.active_path.unlink()


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(
            _json_safe(value),
            stream,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _json_safe(value):
    """把 Milvus SDK 可能返回的数组标量转换成可恢复的 JSON 值。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _json_safe(tolist())
    item = getattr(value, "item", None)
    if callable(item):
        return _json_safe(item())
    raise TypeError(f"recovery bundle 包含不可序列化类型: {type(value).__name__}")


__all__ = [
    "LocalCorpusManifestStore",
    "ScopedCorpusCommitError",
    "ScopedLocalCorpusWriter",
]
