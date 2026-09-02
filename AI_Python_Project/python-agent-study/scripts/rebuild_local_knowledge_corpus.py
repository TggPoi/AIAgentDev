"""本地语料 prebuild、审查后 scoped commit 与崩溃恢复入口。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from fast_app.core.config import Settings, get_settings
from fast_app.db.ingestion_tables import KnowledgeDocumentTable, KnowledgeIngestionJobTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.cli import (
    build_elasticsearch_client,
    build_embedding_client,
    build_milvus_client,
)
from fast_app.ingestion.processing.local_corpus_builder import (
    LocalCorpusPrebuildResult,
    LocalKnowledgeCorpusBuilder,
    RegisteredDocumentOwnership,
)
from fast_app.ingestion.processing.markdown_hierarchy import MarkdownParentChunk
from fast_app.ingestion.stores.scoped_corpus_writer import (
    ScopedLocalCorpusWriter,
)
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock


ARTIFACT_ROOT = Path("runtime/local-corpus/prebuild")
ACTIVE_JOB_STATUSES = {"pending", "running", "awaiting_configuration"}


async def load_registered_documents(session_factory) -> list[RegisteredDocumentOwnership]:
    async with session_factory() as session:
        documents = list((await session.scalars(select(KnowledgeDocumentTable))).all())
        jobs = list((await session.scalars(select(KnowledgeIngestionJobTable))).all())
    active_job_doc_ids = {
        str(job.doc_id) for job in jobs if job.status in ACTIVE_JOB_STATUSES
    }
    return [
        RegisteredDocumentOwnership(
            doc_id=str(row.doc_id),
            source_path=str(row.source_path),
            status=str(row.status),
            has_active_job=str(row.doc_id) in active_job_doc_ids,
        )
        for row in documents
    ]


async def run_prebuild(args, settings: Settings, session_factory) -> int:
    registry = await load_registered_documents(session_factory)
    builder = LocalKnowledgeCorpusBuilder(
        settings=settings,
        embedding_client=build_embedding_client(settings, args.mock_embeddings),
    )
    result = await builder.prebuild(
        source_dir=args.source_dir,
        registered_documents=registry,
        excel_default_mode=args.excel_default_mode,
        expected_document_count=args.expect_document_count,
    )
    report_body = {
        "schema_version": "local-corpus-prebuild-report.v1",
        "local_corpus_id": result.local_corpus_id,
        "source_dir": Path(args.source_dir).as_posix(),
        "document_count": result.document_count,
        "parent_count": len(result.parents),
        "chunk_count": len(result.chunks),
        "embedding_count": len(result.vectors),
        "embedding_dim": settings.embedding_dim,
        "vision_enabled": settings.vision_enabled,
        "vision_model_name": settings.vision_model_name,
        "warnings": result.warnings,
        "excluded_source_paths": result.excluded_source_paths,
        "documents": result.manifest_documents,
        "fatal_processing_failure_count": 0,
    }
    canonical = json.dumps(
        report_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    report_sha = hashlib.sha256(canonical).hexdigest()
    report = {**report_body, "report_sha256": report_sha}
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    _atomic_json(ARTIFACT_ROOT / f"{report_sha}.report.json", report)
    _atomic_json(ARTIFACT_ROOT / f"{report_sha}.bundle.json", _serialize_prebuild(result))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


async def run_commit(args, settings: Settings, engine) -> int:
    report_sha = str(args.accept_report_sha256 or "").strip().lower()
    if len(report_sha) != 64:
        raise RuntimeError("--commit 必须提供 --accept-report-sha256")
    report_path = ARTIFACT_ROOT / f"{report_sha}.report.json"
    bundle_path = ARTIFACT_ROOT / f"{report_sha}.bundle.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("report_sha256") != report_sha:
        raise RuntimeError("prebuild report SHA 不一致")
    if report.get("local_corpus_id") != settings.local_corpus_id:
        raise RuntimeError("prebuild report 的 local_corpus_id 与当前配置不一致")
    for item in report.get("documents", []):
        path = Path(item["source_path"])
        if not path.is_file() or _sha256_file(path) != item["source_revision"]:
            raise RuntimeError(f"prebuild 后源文件已变化: {path}")
    prebuild = _deserialize_prebuild(
        json.loads(bundle_path.read_text(encoding="utf-8"))
    )
    elasticsearch = build_elasticsearch_client(settings)
    milvus = build_milvus_client(settings)
    try:
        manifest = await ScopedLocalCorpusWriter(
            settings=settings,
            elasticsearch_client=elasticsearch,
            milvus_client=milvus,
            mutation_lock=StoreMutationLock(engine),
        ).commit(prebuild, report_sha256=report_sha)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    finally:
        await elasticsearch.close()
        await milvus.close()


async def run_recovery(args, settings: Settings, engine) -> int:
    elasticsearch = build_elasticsearch_client(settings)
    milvus = build_milvus_client(settings)
    try:
        state = await ScopedLocalCorpusWriter(
            settings=settings,
            elasticsearch_client=elasticsearch,
            milvus_client=milvus,
            mutation_lock=StoreMutationLock(engine),
        ).recover(args.recover_generation)
        print(json.dumps({"generation": args.recover_generation, "state": state}))
        return 0
    finally:
        await elasticsearch.close()
        await milvus.close()


def _serialize_prebuild(result: LocalCorpusPrebuildResult) -> dict:
    return {
        "schema_version": "local-corpus-prebuild-bundle.v1",
        "local_corpus_id": result.local_corpus_id,
        "document_count": result.document_count,
        "parents": [
            {
                "id": item.id,
                "content": item.content,
                "source": item.source,
                "title": item.title,
                "metadata": item.metadata,
            }
            for item in result.parents
        ],
        "chunks": [
            {
                "id": item.id,
                "content": item.content,
                "source": item.source,
                "title": item.title,
                "metadata": item.metadata,
                "search_text": item.search_text,
            }
            for item in result.chunks
        ],
        "vectors": result.vectors,
        "manifest_documents": result.manifest_documents,
        "warnings": result.warnings,
        "excluded_source_paths": result.excluded_source_paths,
    }


def _deserialize_prebuild(value: dict) -> LocalCorpusPrebuildResult:
    return LocalCorpusPrebuildResult(
        local_corpus_id=value["local_corpus_id"],
        document_count=int(value["document_count"]),
        parents=[MarkdownParentChunk(**item) for item in value["parents"]],
        chunks=[KnowledgeChunk(**item) for item in value["chunks"]],
        vectors=value["vectors"],
        manifest_documents=value["manifest_documents"],
        warnings=value.get("warnings", []),
        excluded_source_paths=value.get("excluded_source_paths", []),
    )


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地知识语料 scoped rebuild")
    parser.add_argument("--source-dir", default="docs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--accept-report-sha256")
    parser.add_argument("--recover-generation")
    parser.add_argument("--local-corpus-id", default="local-knowledge-base")
    parser.add_argument("--expect-document-count", type=int)
    parser.add_argument("--excel-default-mode", choices=["section"])
    parser.add_argument("--mock-embeddings", action="store_true")
    parser.add_argument("--vision-enabled", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--no-es-auth", action="store_true")
    return parser


async def async_main(args) -> int:
    base = get_settings()
    updates = {
        "knowledge_base_dir": args.source_dir,
        "local_corpus_id": args.local_corpus_id,
    }
    if args.vision_enabled is not None:
        updates["vision_enabled"] = args.vision_enabled
    if args.no_es_auth:
        updates.update(elasticsearch_username="", elasticsearch_password="")
    settings = base.model_copy(update=updates)
    engine = create_database_engine(settings)
    try:
        if args.recover_generation:
            return await run_recovery(args, settings, engine)
        if args.commit:
            return await run_commit(args, settings, engine)
        return await run_prebuild(args, settings, create_session_factory(engine))
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(async_main(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
