from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from collections.abc import Awaitable, Callable

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_scan
from pymilvus import AsyncMilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings
from fast_app.db.gitlab_tables import (
    GitLabDocumentTable,
    GitLabSourceTable,
    GitLabSyncJobTable,
)
from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.processing.chunk_builders import (
    ChunkBuildOptions,
    MarkdownChunkBuilder,
)
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
    MarkdownParentChunk,
)
from fast_app.ingestion.processing.metadata_models import (
    build_permission_metadata,
    normalize_permission_metadata,
)
from fast_app.ingestion.processing.structured_document_processor import (
    StructuredDocumentProcessor,
)
from fast_app.ingestion.validation.document_validation import (
    validate_knowledge_document_package,
)
from fast_app.ingestion.stores.rag_store_writer import (
    close_rag_docs_for_version,
    upsert_rag_stores,
)
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.project_source import (
    GitLabProjectSource,
    SUPPORTED_DOCUMENT_TYPES,
)
from fast_app.integrations.gitlab.repository import GitLabRepository


PROFILE_SUFFIX = ".profile.json"
PERMISSION_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class PreparedSync:
    manifests: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    changed_doc_ids: list[str]
    parents: list[MarkdownParentChunk]
    chunks: list[KnowledgeChunk]
    vectors: list[list[float]]


class GitDocumentSyncService:
    """组织一次固定 SHA 的 GitLab → RAG 同步与原子发布。"""

    def __init__(
        self,
        *,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        elasticsearch_client: AsyncElasticsearch,
        milvus_client: AsyncMilvusClient,
        store_mutation_lock: StoreMutationLock | None = None,
    ) -> None:
        self.settings = settings
        self.embedding_client = embedding_client
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client
        self.store_mutation_lock = store_mutation_lock
        self.markdown_builder = MarkdownHierarchyBuilder()
        self.text_builder = MarkdownChunkBuilder()
        self.document_processor = StructuredDocumentProcessor(settings=settings)

    async def run(
        self,
        *,
        job: GitLabSyncJobTable,
        source: GitLabSourceTable,
        repository: GitLabRepository,
        client: GitLabClient,
        worker_id: str,
    ) -> int:
        existing = {
            row.repository_path: row
            for row in await repository.list_documents(source.id)
        }
        await repository.update_job_phase(
            job_id=job.id, worker_id=worker_id, phase="fetching"
        )
        prepared = (
            await self._prepare_incremental(
                client,
                source,
                job,
                existing,
                before_external_call=lambda: repository.assert_job_owned(
                    job.id, worker_id
                ),
            )
            if job.mode == "incremental" and job.base_sha
            else await self._prepare_full(
                client,
                source,
                job,
                existing,
                before_external_call=lambda: repository.assert_job_owned(
                    job.id, worker_id
                ),
            )
        )
        if not prepared.changes:
            await repository.complete_noop(
                job_id=job.id,
                source_id=source.id,
                worker_id=worker_id,
                target_sha=job.target_sha,
            )
            return await repository.get_active_version()
        await repository.update_job_phase(
            job_id=job.id,
            worker_id=worker_id,
            phase="publishing",
            publishing=True,
        )
        publication = await repository.reserve_publication(
            source_id=source.id,
            job_id=job.id,
            target_sha=job.target_sha,
        )
        parents, chunks = version_artifacts(
            prepared.parents,
            prepared.chunks,
            publication.version,
        )
        async with self._store_mutation_guard():
            # 等待全局锁后重新检查租约，失租 Worker 不得开始 Store mutation。
            await repository.assert_job_owned(job.id, worker_id)
            # 修改/删除文档时不物理删除旧记录，而是把旧记录的有效结束版本设为 N。
            await close_rag_docs_for_version(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                doc_ids=prepared.changed_doc_ids,
                valid_to_version=publication.version,
            )
            if chunks:
                await repository.assert_job_owned(job.id, worker_id)
                await upsert_rag_stores(
                    elasticsearch_client=self.elasticsearch_client,
                    milvus_client=self.milvus_client,
                    settings=self.settings,
                    chunks=chunks,
                    vectors=prepared.vectors,
                    parents=parents,
                    verify_convergence=False,
                )
            # 只有 ES/Milvus 候选版本收敛，才允许切换 PostgreSQL 正式指针。
            await self._verify_candidate(
                source_id=source.id,
                version=publication.version,
                parents=parents,
                chunks=chunks,
            )
            await repository.assert_job_owned(job.id, worker_id)
            await repository.publish(
                job_id=job.id,
                source_id=source.id,
                version=publication.version,
                target_sha=job.target_sha,
                manifests=prepared.manifests,
                changes=prepared.changes,
                parent_count=len(parents),
                child_count=len(chunks),
                validation={
                    "es_parent_count": len(parents),
                    "es_child_count": len(chunks),
                    "milvus_child_count": len(chunks),
                },
                worker_id=worker_id,
            )
        return publication.version

    async def bootstrap_all(
        self,
        *,
        job: GitLabSyncJobTable,
        sources: list[GitLabSourceTable],
        clients: dict[str, GitLabClient],
        target_shas: dict[str, str],
        repository: GitLabRepository,
        worker_id: str,
    ) -> int:
        """把所有已启用 Source 固定到一个初始知识版本后联合发布。"""

        if await repository.get_active_version() != 0:
            raise RuntimeError("联合 Bootstrap 只允许在正式知识版本为 0 时执行")
        entries: list[tuple[GitLabSourceTable, str, PreparedSync]] = []
        for source in sources:
            existing = {
                row.repository_path: row
                for row in await repository.list_documents(source.id)
            }
            prepared = await self._prepare_full_at_sha(
                client=clients[source.id],
                source=source,
                target_sha=target_shas[source.id],
                existing=existing,
                before_external_call=lambda: repository.assert_job_owned(
                    job.id, worker_id
                ),
            )
            entries.append((source, target_shas[source.id], prepared))

        publication = await repository.reserve_publication(
            source_id=sources[0].id,
            job_id=job.id,
            target_sha=target_shas[sources[0].id],
        )
        all_parents: list[MarkdownParentChunk] = []
        all_chunks: list[KnowledgeChunk] = []
        all_vectors: list[list[float]] = []
        for _, _, prepared in entries:
            parents, chunks = version_artifacts(
                prepared.parents,
                prepared.chunks,
                publication.version,
            )
            all_parents.extend(parents)
            all_chunks.extend(chunks)
            all_vectors.extend(prepared.vectors)

        async with self._store_mutation_guard():
            await repository.assert_job_owned(job.id, worker_id)
            if all_chunks:
                await upsert_rag_stores(
                    elasticsearch_client=self.elasticsearch_client,
                    milvus_client=self.milvus_client,
                    settings=self.settings,
                    chunks=all_chunks,
                    vectors=all_vectors,
                    parents=all_parents,
                    verify_convergence=False,
                )
            for source, _, prepared in entries:
                source_parents = [
                    parent
                    for parent in all_parents
                    if parent.metadata.get("source_id") == source.id
                ]
                source_chunks = [
                    chunk
                    for chunk in all_chunks
                    if chunk.metadata.get("source_id") == source.id
                ]
                await self._verify_candidate(
                    source_id=source.id,
                    version=publication.version,
                    parents=source_parents,
                    chunks=source_chunks,
                )
            await repository.assert_job_owned(job.id, worker_id)
            await repository.publish_bootstrap(
                job_id=job.id,
                worker_id=worker_id,
                version=publication.version,
                entries=[
                    {
                        "source": source,
                        "target_sha": target_sha,
                        "manifests": prepared.manifests,
                        "changes": prepared.changes,
                    }
                    for source, target_sha, prepared in entries
                ],
                parent_count=len(all_parents),
                child_count=len(all_chunks),
            )
        return publication.version

    async def _prepare_full(
        self,
        client: GitLabClient,
        source: GitLabSourceTable,
        job: GitLabSyncJobTable,
        existing: dict[str, GitLabDocumentTable],
        before_external_call: Callable[[], Awaitable[None]] | None = None,
    ) -> PreparedSync:
        return await self._prepare_full_at_sha(
            client=client,
            source=source,
            target_sha=job.target_sha,
            existing=existing,
            before_external_call=before_external_call,
        )

    async def _prepare_full_at_sha(
        self,
        *,
        client: GitLabClient,
        source: GitLabSourceTable,
        target_sha: str,
        existing: dict[str, GitLabDocumentTable],
        before_external_call: Callable[[], Awaitable[None]] | None = None,
    ) -> PreparedSync:
        archive = await client.download_archive(source.project_id, target_sha)
        if len(archive) > self.settings.gitlab_archive_max_bytes:
            raise ValueError("GitLab Archive 超过大小限制")
        with tempfile.TemporaryDirectory(prefix="rag-gitlab-") as temp_dir:
            root = safe_extract_archive(
                archive,
                Path(temp_dir),
                max_files=self.settings.gitlab_archive_max_files,
                max_bytes=self.settings.gitlab_archive_max_bytes,
                max_file_bytes=self.settings.gitlab_source_file_max_bytes,
            )
            paths = sorted(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_DOCUMENT_TYPES
            )
            current_paths = {
                path.relative_to(root).as_posix(): path for path in paths
            }
            return await self._prepare_paths(
                source=source,
                target_sha=target_sha,
                current_paths=current_paths,
                existing=existing,
                root=root,
                before_external_call=before_external_call,
            )

    async def _prepare_incremental(
        self,
        client: GitLabClient,
        source: GitLabSourceTable,
        job: GitLabSyncJobTable,
        existing: dict[str, GitLabDocumentTable],
        before_external_call: Callable[[], Awaitable[None]] | None = None,
    ) -> PreparedSync:
        compare = await client.compare(
            source.project_id,
            str(job.base_sha),
            job.target_sha,
        )
        # GitLab 明确告诉我们 Compare 超时或截断时，增量结果不可信；
        # 自动退回固定 target_sha 的 Archive 全量同步，正确性优先于少下载数据。
        if compare.compare_timeout or compare.overflow:
            return await self._prepare_full(
                client, source, job, existing, before_external_call=before_external_call
            )
        changed_paths: set[str] = set()
        deleted_paths: set[str] = set()
        for diff in compare.diffs:
            old_path = _normalize_repository_path(diff.old_path)
            new_path = _normalize_repository_path(diff.new_path)
            if _is_policy_path(old_path) or _is_policy_path(new_path):
                # 权限规则或 Sidecar 可能影响不止一个正文文件，无法只凭当前 diff
                # 准确列出受影响文档，因此回退全量 Manifest 对账。
                return await self._prepare_full(
                    client, source, job, existing, before_external_call=before_external_call
                )
            if diff.deleted_file or diff.renamed_file:
                if _is_supported(old_path):
                    deleted_paths.add(old_path)
            if not diff.deleted_file and _is_supported(new_path):
                if PurePosixPath(new_path).suffix.lower() == ".xlsx":
                    return await self._prepare_full(
                        client, source, job, existing, before_external_call=before_external_call
                    )
                changed_paths.add(new_path)

        with tempfile.TemporaryDirectory(prefix="rag-gitlab-incremental-") as temp_dir:
            root = Path(temp_dir)
            current_paths: dict[str, Path] = {}
            await _download_optional_file(
                client=client,
                project_id=source.project_id,
                repository_path=".permission-rules.json",
                ref=job.target_sha,
                root=root,
                max_bytes=self.settings.gitlab_source_file_max_bytes,
            )
            for path in sorted(changed_paths):
                content = await client.get_file(
                    source.project_id, path, job.target_sha
                )
                if len(content) > self.settings.gitlab_source_file_max_bytes:
                    raise ValueError(f"GitLab 文件超过大小限制: {path}")
                target = root.joinpath(*PurePosixPath(path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                current_paths[path] = target
                await _download_optional_file(
                    client=client,
                    project_id=source.project_id,
                    repository_path=f"{path}{PERMISSION_SUFFIX}",
                    ref=job.target_sha,
                    root=root,
                    max_bytes=self.settings.gitlab_source_file_max_bytes,
                )

            prepared = await self._prepare_paths(
                source=source,
                target_sha=job.target_sha,
                current_paths=current_paths,
                existing=existing,
                root=root,
                preserve_unmentioned=True,
                explicit_deleted=deleted_paths,
                before_external_call=before_external_call,
            )
            return prepared

    async def _prepare_paths(
        self,
        *,
        source: GitLabSourceTable,
        target_sha: str,
        current_paths: dict[str, Path],
        existing: dict[str, GitLabDocumentTable],
        root: Path,
        preserve_unmentioned: bool = False,
        explicit_deleted: set[str] | None = None,
        before_external_call: Callable[[], Awaitable[None]] | None = None,
    ) -> PreparedSync:
        adapter = GitLabProjectSource(
            host_id=source.host_id,
            project_id=source.project_id,
            source_id=source.id,
            department_code=source.department_code,
            default_visibility=source.default_visibility,
        )
        manifests: dict[str, dict[str, Any]] = {
            path: _manifest_from_row(row) for path, row in existing.items()
        }
        parents: list[MarkdownParentChunk] = []
        chunks: list[KnowledgeChunk] = []
        changes: list[dict[str, Any]] = []
        changed_doc_ids: set[str] = set()
        explicit_deleted = explicit_deleted or set()
        if not preserve_unmentioned:
            # 全量同步中，Archive 已代表 target_sha 的完整仓库快照；
            # 旧 Manifest 有而快照没有的路径就是删除。
            explicit_deleted |= set(existing) - set(current_paths)

        for path in sorted(explicit_deleted):
            old = existing.get(path)
            if old is None:
                continue
            manifests.pop(path, None)
            changed_doc_ids.add(old.doc_id)
            changes.append(_change("deleted", old.doc_id, path, old.acl_json))

        for path, file_path in current_paths.items():
            raw = file_path.read_bytes()
            document_type = adapter.document_type(path)
            if document_type is None:
                continue
            content_hash = _document_content_hash(
                file_path=file_path,
                raw=raw,
                document_type=document_type,
            )
            acl = _load_narrow_acl(
                file_path,
                default_acl=adapter.default_acl(),
                root=root,
            )
            acl_hash = _stable_hash(acl)
            if document_type == "markdown":
                strategy_version = adapter.chunk_strategy_version
            elif document_type in {"powerpoint", "word", "pdf"}:
                strategy_version = f"{document_type}_builder_office_vision_v2"
            else:
                strategy_version = f"{document_type}_builder_v1"
            config_fingerprint = adapter.chunk_config_fingerprint(
                self._chunk_config(document_type)
            )
            old = existing.get(path)
            unchanged = (
                old is not None
                and old.content_hash == content_hash
                and old.acl_hash == acl_hash
                and old.parser_version == adapter.parser_version
                and old.chunk_strategy_version == strategy_version
                and old.chunk_config_fingerprint == config_fingerprint
            )
            if unchanged:
                # 不仅比较 Git 文件内容，还比较 ACL、解析器和分块配置。
                # 即使文件未改，只要策略升级，也必须重新生成完整文档父子块。
                continue

            doc_id = adapter.doc_id(path)
            doc_parents, doc_chunks = await self._build_artifacts(
                adapter=adapter,
                repository_path=path,
                file_path=file_path,
                raw=raw,
                target_sha=target_sha,
                acl=acl,
                before_external_call=before_external_call,
            )
            parents.extend(doc_parents)
            chunks.extend(doc_chunks)
            changed_doc_ids.add(doc_id)
            manifests[path] = {
                "doc_id": doc_id,
                "source_id": source.id,
                "repository_path": path,
                "blob_id": _git_blob_id(raw),
                "source_revision": target_sha,
                "content_hash": content_hash,
                "acl_hash": acl_hash,
                "parser_version": adapter.parser_version,
                "chunk_strategy_version": strategy_version,
                "chunk_config_fingerprint": config_fingerprint,
                "document_type": document_type,
                "acl_json": acl,
            }
            change_type = "added" if old is None else "modified"
            changes.append(_change(change_type, doc_id, path, acl))

        # 只对子块生成向量。Markdown 父块写入 ES 供命中后扩展上下文，
        # 不写 Milvus，避免同一正文以父块和子块两种粒度重复参与向量召回。
        vectors = (
            await self.embedding_client.embed_documents(
                [chunk.search_text or chunk.content for chunk in chunks]
            )
            if chunks
            else []
        )
        return PreparedSync(
            manifests=list(manifests.values()),
            changes=changes,
            changed_doc_ids=sorted(changed_doc_ids),
            parents=parents,
            chunks=chunks,
            vectors=vectors,
        )

    async def _build_artifacts(
        self,
        *,
        adapter: GitLabProjectSource,
        repository_path: str,
        file_path: Path,
        raw: bytes,
        target_sha: str,
        acl: dict[str, Any],
        before_external_call: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[list[MarkdownParentChunk], list[KnowledgeChunk]]:
        document_type = adapter.document_type(repository_path)
        options = self._chunk_options()
        if document_type in {"markdown", "text"}:
            document = adapter.build_text_document(
                repository_path=repository_path,
                content=raw.decode("utf-8"),
                source_revision=target_sha,
                acl=acl,
            )
            if document_type == "markdown":
                # GitLab 接入复用现有父子分块器：parents 用于最终上下文，
                # children 的 search_text 用于关键词检索和 Embedding。
                result = self.markdown_builder.build(
                    [document],
                    MarkdownHierarchyOptions(
                        source=self.settings.ingestion_source_name,
                        parent_target_tokens=self.settings.markdown_parent_target_tokens,
                        parent_max_tokens=self.settings.markdown_parent_max_tokens,
                        parent_max_chars=self.settings.markdown_parent_max_chars,
                        child_target_tokens=self.settings.markdown_child_target_tokens,
                        child_max_tokens=self.settings.markdown_child_max_tokens,
                        child_min_tokens=self.settings.markdown_child_min_tokens,
                        child_overlap_tokens=self.settings.markdown_child_overlap_tokens,
                    ),
                )
                return result.parents, result.children
            return [], self.text_builder.build([document], options)

        metadata = {
            "doc_id": adapter.doc_id(repository_path),
            "source_path": repository_path,
            "source_uri": adapter.source_uri(repository_path),
            "source_id": adapter.source_id,
            "source_revision": target_sha,
            "document_type": document_type,
            "file_name": PurePosixPath(repository_path).name,
            "file_extension": PurePosixPath(repository_path).suffix,
            **acl,
        }
        validate_knowledge_document_package(
            file_path, document_type=document_type
        )
        profile = None
        if document_type == "spreadsheet":
            profile_path = Path(f"{file_path}{PROFILE_SUFFIX}")
            if not profile_path.is_file():
                raise ValueError(
                    f"XLSX 缺少随仓库版本化的 Profile: {repository_path}{PROFILE_SUFFIX}"
                )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if document_type in {"powerpoint", "spreadsheet", "word", "pdf"}:
            processed = await self.document_processor.process_file(
                file_path,
                document_type=document_type,
                source_path=repository_path,
                options=options,
                document_metadata=metadata,
                excel_profile=profile,
                before_external_call=before_external_call,
            )
            return processed.parents, processed.chunks
        raise ValueError(f"不支持的 GitLab 文档类型: {repository_path}")

    @asynccontextmanager
    async def _store_mutation_guard(self):
        if self.store_mutation_lock is None:
            yield
            return
        async with self.store_mutation_lock.hold():
            yield

    def _chunk_options(self) -> ChunkBuildOptions:
        return ChunkBuildOptions(
            source=self.settings.ingestion_source_name,
            max_chars=self.settings.markdown_chunk_max_chars,
            overlap_chars=self.settings.markdown_chunk_overlap_chars,
            max_tokens=self.settings.markdown_chunk_max_tokens,
            min_chars=self.settings.markdown_chunk_min_chars,
        )

    def _chunk_config(self, document_type: str) -> dict[str, Any]:
        values = {
            "max_chars": self.settings.markdown_chunk_max_chars,
            "overlap_chars": self.settings.markdown_chunk_overlap_chars,
            "max_tokens": self.settings.markdown_chunk_max_tokens,
            "min_chars": self.settings.markdown_chunk_min_chars,
        }
        if document_type == "markdown":
            values.update(
                parent_target=self.settings.markdown_parent_target_tokens,
                parent_max=self.settings.markdown_parent_max_tokens,
                parent_max_chars=self.settings.markdown_parent_max_chars,
                child_target=self.settings.markdown_child_target_tokens,
                child_max=self.settings.markdown_child_max_tokens,
                child_min=self.settings.markdown_child_min_tokens,
                child_overlap=self.settings.markdown_child_overlap_tokens,
            )
        if document_type in {"powerpoint", "word", "pdf"}:
            values.update(
                builder_schema_version="office-vision-v2",
                vision_enabled=self.settings.vision_enabled,
                vision_model=self.settings.vision_model_name,
                vision_prompt=self.settings.vision_prompt_version,
                vision_preprocess=self.settings.vision_preprocess_version,
                vision_schema=self.settings.vision_schema_version,
                pdf_scanned_text_threshold=self.settings.pdf_scanned_text_threshold,
            )
        return values

    async def _verify_candidate(
        self,
        *,
        source_id: str,
        version: int,
        parents: list[MarkdownParentChunk],
        chunks: list[KnowledgeChunk],
    ) -> None:
        expected_es = {
            **{parent.id: parent.metadata for parent in parents},
            **{chunk.id: chunk.metadata for chunk in chunks},
        }
        # 候选版本写入共享索引/Collection 后，按 source_id + version 精确反查。
        # 验证失败时不会调用 repository.publish()，旧 active_version 继续服务。
        actual_es: dict[str, dict[str, Any]] = {}
        identity_fields = (
            "physical_record_id",
            "logical_record_id",
            "doc_id",
            "record_type",
            "source_id",
            "source_revision",
            "valid_from_version",
            "valid_to_version",
            "logical_parent_id",
            "physical_parent_id",
        )
        query = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"source_id": source_id}},
                        {"term": {"valid_from_version": version}},
                    ]
                }
            }
        }
        async for hit in async_scan(
            client=self.elasticsearch_client,
            index=self.settings.elasticsearch_index_name,
            query=query,
            _source=["id", "metadata", *identity_fields],
        ):
            source = hit.get("_source") or {}
            record_id = str(source.get("id") or hit.get("_id") or "")
            actual_es[record_id] = dict(source)
        if set(actual_es) != set(expected_es):
            raise RuntimeError("候选版本 ES 父子记录集合不一致")
        for record_id, expected in expected_es.items():
            actual_source = actual_es[record_id]
            for field in identity_fields:
                expected_value = (
                    record_id
                    if field == "physical_record_id"
                    else expected.get(field)
                )
                if field == "record_type":
                    expected_value = expected_value or "chunk"
                if field in {"logical_parent_id", "physical_parent_id"}:
                    expected_value = expected_value or ""
                if actual_source.get(field) != expected_value:
                    raise RuntimeError(
                        f"候选版本 ES 顶层字段 {field} 不一致: {record_id}"
                    )
            actual = dict(actual_source.get("metadata") or {})
            for field in (
                "doc_id",
                "record_type",
                "source_id",
                "source_revision",
                "valid_from_version",
                "valid_to_version",
                "chunk_strategy_version",
                "visibility",
                "allowed_departments",
                "allowed_users",
                "logical_parent_id",
                "physical_parent_id",
            ):
                if actual.get(field) != expected.get(field):
                    raise RuntimeError(
                        f"候选版本 ES metadata.{field} 不一致: {record_id}"
                    )

        milvus_count = 0
        actual_milvus: dict[str, dict[str, Any]] = {}
        while True:
            milvus_rows = await self.milvus_client.query(
                collection_name=self.settings.milvus_collection_name,
                filter=(
                    f'source_id == "{_escape_milvus(source_id)}" and '
                    f"valid_from_version == {version}"
                ),
                output_fields=[
                    self.settings.milvus_id_field,
                    self.settings.milvus_vector_field,
                    *identity_fields,
                    "metadata",
                ],
                limit=1000,
                offset=milvus_count,
            )
            for row in milvus_rows:
                vector = row.get(self.settings.milvus_vector_field)
                if vector is None or len(vector) != self.settings.embedding_dim:
                    raise RuntimeError("候选版本 Milvus 向量维度不一致")
                actual_milvus[str(row[self.settings.milvus_id_field])] = dict(row)
            milvus_count += len(milvus_rows)
            if len(milvus_rows) < 1000:
                break
        expected_milvus = {chunk.id: chunk.metadata for chunk in chunks}
        if milvus_count != len(chunks) or set(actual_milvus) != set(expected_milvus):
            raise RuntimeError("候选版本 Milvus 子块集合不一致")
        parent_ids = {parent.id for parent in parents}
        for record_id, expected in expected_milvus.items():
            actual_row = actual_milvus[record_id]
            for field in identity_fields:
                expected_value = (
                    record_id
                    if field == "physical_record_id"
                    else expected.get(field)
                )
                if field == "record_type":
                    expected_value = expected_value or "chunk"
                if field in {"logical_parent_id", "physical_parent_id"}:
                    expected_value = expected_value or ""
                if actual_row.get(field) != expected_value:
                    raise RuntimeError(
                        f"候选版本 Milvus 顶层字段 {field} 不一致: {record_id}"
                    )
            actual = dict(actual_row.get("metadata") or {})
            if expected.get("physical_parent_id") and expected.get(
                "physical_parent_id"
            ) not in parent_ids:
                raise RuntimeError("候选版本子块引用了不存在的父块")
            for field in (
                "doc_id",
                "record_type",
                "source_id",
                "source_revision",
                "valid_from_version",
                "valid_to_version",
                "chunk_strategy_version",
                "visibility",
                "allowed_departments",
                "allowed_users",
                "logical_parent_id",
                "physical_parent_id",
            ):
                if actual.get(field) != expected.get(field):
                    raise RuntimeError(
                        f"候选版本 Milvus metadata.{field} 不一致: {record_id}"
                    )


def version_artifacts(
    parents: list[MarkdownParentChunk],
    chunks: list[KnowledgeChunk],
    version: int,
) -> tuple[list[MarkdownParentChunk], list[KnowledgeChunk]]:
    # Builder 产生的是跨版本稳定的逻辑 ID；发布时再派生物理 ID。
    # 同一逻辑块在版本 N 和 N+1 中拥有不同物理记录，因此可以安全共存。
    parent_ids = {
        parent.id: _physical_id(parent.id, version) for parent in parents
    }
    versioned_parents: list[MarkdownParentChunk] = []
    for parent in parents:
        physical_id = parent_ids[parent.id]
        metadata = dict(parent.metadata)
        metadata.update(
            {
                "logical_record_id": parent.id,
                "physical_record_id": physical_id,
                "logical_parent_id": parent.id,
                "physical_parent_id": physical_id,
                "parent_id": physical_id,
                "valid_from_version": version,
                "valid_to_version": 0,
            }
        )
        versioned_parents.append(
            MarkdownParentChunk(
                id=physical_id,
                content=parent.content,
                source=parent.source,
                title=parent.title,
                metadata=metadata,
            )
        )

    versioned_chunks: list[KnowledgeChunk] = []
    for chunk in chunks:
        physical_id = _physical_id(chunk.id, version)
        metadata = dict(chunk.metadata)
        logical_parent_id = metadata.get("parent_id")
        physical_parent_id = (
            parent_ids.get(str(logical_parent_id))
            if logical_parent_id
            else None
        )
        # 子块必须引用“同一个候选版本”的物理父块，不能只保存逻辑 parent_id，
        # 否则旧子块可能在父块扩展时错误读取到新版本正文。
        metadata.update(
            {
                "logical_record_id": chunk.id,
                "physical_record_id": physical_id,
                "logical_parent_id": logical_parent_id,
                "physical_parent_id": physical_parent_id,
                "valid_from_version": version,
                "valid_to_version": 0,
                "chunk_id": physical_id,
            }
        )
        if physical_parent_id:
            metadata["parent_id"] = physical_parent_id
        versioned_chunks.append(
            KnowledgeChunk(
                id=physical_id,
                content=chunk.content,
                source=chunk.source,
                title=chunk.title,
                metadata=metadata,
                search_text=chunk.search_text,
            )
        )
    return versioned_parents, versioned_chunks


def safe_extract_archive(
    archive: bytes,
    destination: Path,
    *,
    max_files: int,
    max_bytes: int,
    max_file_bytes: int,
) -> Path:
    total = 0
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle.getmembers():
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("GitLab Archive 包含不允许的链接或特殊文件")
            count += 1
            total += member.size
            if count > max_files or total > max_bytes or member.size > max_file_bytes:
                raise ValueError("GitLab Archive 解压限制被触发")
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("GitLab Archive 路径穿越")
            target = destination.joinpath(*relative.parts).resolve()
            if destination.resolve() not in target.parents:
                raise ValueError("GitLab Archive 路径越界")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("GitLab Archive 文件读取失败")
            target.write_bytes(source.read())
    children = list(destination.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination


def _load_narrow_acl(
    file_path: Path,
    *,
    default_acl: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    if (
        not Path(f"{file_path}{PERMISSION_SUFFIX}").is_file()
        and not (root / ".permission-rules.json").is_file()
    ):
        return dict(default_acl)
    requested = normalize_permission_metadata(
        build_permission_metadata(
            source_path=str(file_path),
            knowledge_base_dir=str(root),
        )
    )
    if requested["visibility"] == "public":
        if default_acl["visibility"] != "public":
            raise ValueError("GitLab 文档权限规则不能扩大 Project 安全边界")
        return dict(default_acl)

    allowed_departments = set(requested["allowed_departments"])
    project_departments = set(default_acl["allowed_departments"])
    if (
        default_acl["visibility"] != "public"
        and (
            not allowed_departments
            or not allowed_departments.issubset(project_departments)
        )
    ):
        raise ValueError("GitLab 文档 allowed_departments 超出 Project 安全边界")
    if requested["allowed_users"]:
        raise ValueError("本阶段不允许 Git 仓库 ACL 按用户扩大访问范围")
    return {
        **requested,
        "allowed_departments": sorted(allowed_departments),
        "allowed_users": [],
    }


async def _download_optional_file(
    *,
    client: GitLabClient,
    project_id: int,
    repository_path: str,
    ref: str,
    root: Path,
    max_bytes: int,
) -> None:
    content = await client.get_file_optional(project_id, repository_path, ref)
    if content is None:
        return
    if len(content) > max_bytes:
        raise ValueError(f"GitLab 辅助文件超过大小限制: {repository_path}")
    target = root.joinpath(*PurePosixPath(repository_path).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _manifest_from_row(row: GitLabDocumentTable) -> dict[str, Any]:
    return {
        "doc_id": row.doc_id,
        "source_id": row.source_id,
        "repository_path": row.repository_path,
        "blob_id": row.blob_id,
        "source_revision": row.source_revision,
        "content_hash": row.content_hash,
        "acl_hash": row.acl_hash,
        "parser_version": row.parser_version,
        "chunk_strategy_version": row.chunk_strategy_version,
        "chunk_config_fingerprint": row.chunk_config_fingerprint,
        "document_type": row.document_type,
        "acl_json": row.acl_json,
    }


def _change(
    change_type: str,
    doc_id: str,
    path: str,
    acl: dict[str, Any],
) -> dict[str, Any]:
    return {
        "change_type": change_type,
        "doc_id": doc_id,
        "source_path": path,
        "title": PurePosixPath(path).name,
        **acl,
    }


def _physical_id(logical_id: str, version: int) -> str:
    return hashlib.sha256(f"{logical_id}{version}".encode("utf-8")).hexdigest()


def _git_blob_id(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _document_content_hash(
    *,
    file_path: Path,
    raw: bytes,
    document_type: str,
) -> str:
    digest = hashlib.sha256(raw)
    if document_type == "spreadsheet":
        profile_path = Path(f"{file_path}{PROFILE_SUFFIX}")
        if not profile_path.is_file():
            raise ValueError(
                f"XLSX 缺少仓库版本化 Profile: {file_path.name}{PROFILE_SUFFIX}"
            )
        digest.update(b"\0profile\0")
        digest.update(profile_path.read_bytes())
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_repository_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/").strip("/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("GitLab Compare 返回非法路径")
    return path.as_posix()


def _is_supported(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SUPPORTED_DOCUMENT_TYPES


def _is_policy_path(path: str) -> bool:
    return (
        PurePosixPath(path).name == ".permission-rules.json"
        or path.endswith(PERMISSION_SUFFIX)
        or path.endswith(PROFILE_SUFFIX)
    )


def _escape_milvus(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


__all__ = [
    "GitDocumentSyncService",
    "PreparedSync",
    "safe_extract_archive",
    "version_artifacts",
]
