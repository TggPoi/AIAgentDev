"""Local corpus ownership 与共享 Store mutation lock 回归。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fast_app.components.embeddings.mock_embedding_client import MockEmbeddingClient
from fast_app.core.config import Settings
from fast_app.ingestion.processing.local_corpus_builder import (
    LocalCorpusOwnershipConflict,
    LocalKnowledgeCorpusBuilder,
    RegisteredDocumentOwnership,
)
from fast_app.ingestion.processing.metadata_models import (
    apply_local_corpus_ownership,
    build_doc_id,
)
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock
from fast_app.ingestion.stores.scoped_corpus_writer import (
    LocalCorpusManifestStore,
    ScopedLocalCorpusWriter,
)


def test_local_ownership_is_stable_and_cannot_overwrite_gitlab() -> None:
    revision = "a" * 64
    owned = apply_local_corpus_ownership(
        {"doc_id": "doc-1", "source_path": "docs/one.md"},
        local_corpus_id="local-knowledge-base",
        source_revision=revision,
    )
    assert owned["ownership_type"] == "local_corpus"
    assert owned["source_id"] == "local:local-knowledge-base"
    assert owned["source_revision"] == revision
    assert owned["valid_from_version"] == 0
    assert owned["valid_to_version"] == 0

    try:
        apply_local_corpus_ownership(
            {"source_id": "gitlab:source-1"},
            local_corpus_id="local-knowledge-base",
            source_revision=revision,
        )
    except ValueError as exc:
        assert "非本地" in str(exc)
    else:
        raise AssertionError("local helper 不得覆盖 GitLab ownership")


class FakeConnection:
    def __init__(self, shared: asyncio.Lock, events: list[str], name: str) -> None:
        self.shared = shared
        self.events = events
        self.name = name

    async def __aenter__(self):
        self.events.append(f"connect:{self.name}")
        return self

    async def __aexit__(self, *_args):
        self.events.append(f"close:{self.name}")

    async def execute(self, statement, _parameters):
        sql = str(statement)
        if "pg_advisory_lock" in sql and "unlock" not in sql:
            await self.shared.acquire()
            self.events.append(f"acquired:{self.name}")
        elif "pg_advisory_unlock" in sql:
            self.events.append(f"released:{self.name}")
            self.shared.release()


class FakeEngine:
    def __init__(self) -> None:
        self.shared = asyncio.Lock()
        self.events: list[str] = []
        self.count = 0

    def connect(self):
        self.count += 1
        return FakeConnection(self.shared, self.events, f"writer-{self.count}")


async def test_store_mutations_are_serialized() -> None:
    engine = FakeEngine()
    lock = StoreMutationLock(engine)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with lock.hold():
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with lock.hold():
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert not second_entered.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set()
    assert engine.events.index("released:writer-1") < engine.events.index("acquired:writer-2")


async def test_local_builder_preserves_markdown_and_excludes_office_owned_path() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "public").mkdir()
        markdown = root / "public" / "guide.md"
        markdown.write_text("# Guide\n\nThis is the local guide body.", encoding="utf-8")
        office_owned = root / "public" / "managed.txt"
        office_owned.write_text("must not be adopted", encoding="utf-8")
        settings = Settings(
            _env_file=None,
            KNOWLEDGE_BASE_DIR=str(root),
            EMBEDDING_DIM=8,
            VISION_ENABLED=False,
            MARKDOWN_CHILD_MIN_TOKENS=1,
        )
        builder = LocalKnowledgeCorpusBuilder(
            settings=settings,
            embedding_client=MockEmbeddingClient(dim=8),
        )
        result = await builder.prebuild(
            source_dir=root,
            registered_documents=[
                RegisteredDocumentOwnership(
                    doc_id="office-doc",
                    source_path=office_owned.as_posix(),
                    status="active",
                    has_active_job=False,
                )
            ],
            excel_default_mode="section",
        )
        assert result.document_count == 1
        assert result.parents
        assert result.chunks
        assert len(result.vectors) == len(result.chunks)
        assert all(
            item.metadata["source_id"] == "local:local-knowledge-base"
            for item in [*result.parents, *result.chunks]
        )
        assert office_owned.as_posix() in result.excluded_source_paths


async def test_orphan_pending_registry_blocks_local_prebuild() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "pending.md"
        path.write_text("# Pending\n\nbody", encoding="utf-8")
        builder = LocalKnowledgeCorpusBuilder(
            settings=Settings(
                _env_file=None,
                KNOWLEDGE_BASE_DIR=str(root),
                EMBEDDING_DIM=8,
                MARKDOWN_CHILD_MIN_TOKENS=1,
            ),
            embedding_client=MockEmbeddingClient(dim=8),
        )
        try:
            await builder.prebuild(
                source_dir=root,
                registered_documents=[
                    RegisteredDocumentOwnership(
                        doc_id="pending-doc",
                        source_path=path.as_posix(),
                        status="pending",
                        has_active_job=False,
                    )
                ],
                excel_default_mode="section",
            )
        except LocalCorpusOwnershipConflict as exc:
            assert exc.code == "LOCAL_CORPUS_ORPHAN_PENDING_DOCUMENT"
        else:
            raise AssertionError("无活动任务的 pending registry 必须阻止重建")


async def test_registry_path_and_doc_id_cannot_select_different_owners() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "collision.md"
        path.write_text("# Collision\n\nbody", encoding="utf-8")
        actual_doc_id = build_doc_id(path.as_posix())
        builder = LocalKnowledgeCorpusBuilder(
            settings=Settings(
                _env_file=None,
                KNOWLEDGE_BASE_DIR=str(root),
                EMBEDDING_DIM=8,
                MARKDOWN_CHILD_MIN_TOKENS=1,
            ),
            embedding_client=MockEmbeddingClient(dim=8),
        )
        try:
            await builder.prebuild(
                source_dir=root,
                registered_documents=[
                    RegisteredDocumentOwnership(
                        doc_id="different-doc",
                        source_path=path.as_posix(),
                        status="active",
                        has_active_job=False,
                    ),
                    RegisteredDocumentOwnership(
                        doc_id=actual_doc_id,
                        source_path=(root / "other.md").as_posix(),
                        status="active",
                        has_active_job=False,
                    ),
                ],
                excel_default_mode="section",
            )
        except LocalCorpusOwnershipConflict as exc:
            assert exc.code == "LOCAL_CORPUS_REGISTRY_COLLISION"
        else:
            raise AssertionError("source_path 与 doc_id 指向不同 Office owner 时必须拒绝")


async def test_missing_active_office_file_is_reported_without_local_adoption() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        builder = LocalKnowledgeCorpusBuilder(
            settings=Settings(
                _env_file=None,
                KNOWLEDGE_BASE_DIR=str(root),
                EMBEDDING_DIM=8,
            ),
            embedding_client=MockEmbeddingClient(dim=8),
        )
        missing = root / "managed.docx"
        result = await builder.prebuild(
            source_dir=root,
            registered_documents=[
                RegisteredDocumentOwnership(
                    doc_id="managed-doc",
                    source_path=missing.as_posix(),
                    status="active",
                    has_active_job=False,
                )
            ],
            excel_default_mode="section",
        )
        assert any(
            item["code"] == "LOCAL_CORPUS_ACTIVE_OFFICE_FILE_MISSING"
            and item["source_path"] == missing.as_posix()
            for item in result.warnings
        )


class ImmediateMutationLock:
    @asynccontextmanager
    async def hold(self):
        yield


class RecoveryProbeWriter(ScopedLocalCorpusWriter):
    def __init__(self, *, settings, manifest_store) -> None:
        super().__init__(
            settings=settings,
            elasticsearch_client=None,
            milvus_client=None,
            mutation_lock=ImmediateMutationLock(),
            manifest_store=manifest_store,
        )
        self.verified: list[str] = []
        self.restored: list[dict | None] = []

    async def _verify(self, manifest: dict) -> None:
        self.verified.append(str(manifest["generation"]))

    async def _restore(self, snapshot: dict, *, old_manifest: dict | None) -> None:
        self.restored.append(old_manifest)


async def test_recovery_before_and_after_manifest_publish() -> None:
    with TemporaryDirectory() as directory:
        store = LocalCorpusManifestStore(Path(directory))
        settings = Settings(_env_file=None)
        writer = RecoveryProbeWriter(settings=settings, manifest_store=store)

        old_manifest = {
            "generation": "old-generation",
            "local_corpus_id": settings.local_corpus_id,
        }
        target = {
            "generation": "before-manifest",
            "local_corpus_id": settings.local_corpus_id,
            "es_record_ids": [],
            "milvus_record_ids": [],
        }
        recovery_path = store.write_recovery(
            "before-manifest", {"old_manifest": old_manifest}
        )
        store.write_active(old_manifest)
        store.write_journal(
            "before-manifest",
            {
                "generation": "before-manifest",
                "state": "mutating",
                "target_manifest": target,
                "recovery_path": recovery_path.as_posix(),
            },
        )
        assert await writer.recover("before-manifest") == "rolled_back"
        assert writer.restored == [old_manifest]

        published = {
            "generation": "after-manifest",
            "local_corpus_id": settings.local_corpus_id,
            "es_record_ids": [],
            "milvus_record_ids": [],
        }
        recovery_path = store.write_recovery(
            "after-manifest", {"old_manifest": old_manifest}
        )
        store.write_active(published)
        store.write_journal(
            "after-manifest",
            {
                "generation": "after-manifest",
                "state": "manifest_published",
                "target_manifest": published,
                "recovery_path": recovery_path.as_posix(),
            },
        )
        assert await writer.recover("after-manifest") == "committed"
        assert writer.verified[-1] == "after-manifest"
        assert writer.restored == [old_manifest]


async def main() -> None:
    test_local_ownership_is_stable_and_cannot_overwrite_gitlab()
    await test_store_mutations_are_serialized()
    await test_local_builder_preserves_markdown_and_excludes_office_owned_path()
    await test_orphan_pending_registry_blocks_local_prebuild()
    await test_registry_path_and_doc_id_cannot_select_different_owners()
    await test_missing_active_office_file_is_reported_without_local_adoption()
    await test_recovery_before_and_after_manifest_publish()
    print("local_corpus_and_store_lock=passed")


if __name__ == "__main__":
    asyncio.run(main())
