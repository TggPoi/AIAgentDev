from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shutil
import socket
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from elasticsearch import AsyncElasticsearch
from pymilvus import AsyncMilvusClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings, get_settings
from fast_app.core.langsmith import (
    build_langsmith_metadata,
    build_langsmith_tags,
    configure_langsmith,
    langsmith_trace,
)
from fast_app.core.logging import format_log_fields, get_logger, setup_logging
from fast_app.core.request_context import reset_request_context, set_request_context
from fast_app.db.ingestion_tables import KnowledgeIngestionJobTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.ingestion.processing.chunk_builders import ChunkBuildOptions
from fast_app.ingestion.cli import (
    apply_arg_overrides,
    build_elasticsearch_client,
    build_embedding_client,
    build_milvus_client,
)
from fast_app.ingestion.processing.document_loaders import (
    ExcelDocumentLoader,
    PowerPointDocumentLoader,
)
from fast_app.ingestion.import_jobs import (
    HEARTBEAT_SECONDS,
    ClaimedImportJob,
    KnowledgeImportJobRepository,
)
from fast_app.ingestion.stores.incremental_store import (
    apply_chunk_diff,
    build_chunk_diff,
    load_es_chunk_states,
    load_milvus_chunk_states,
    verify_chunk_convergence,
)
from fast_app.ingestion.validation.ingestion_validation import validate_ingestion_result
from fast_app.ingestion.validation.document_validation import (
    DocumentPackageValidationError,
    KnowledgeDocumentValidationLimits,
    validate_knowledge_document_package,
)
from fast_app.ingestion.processing.office_chunk_builders import (
    ExcelChunkBuilder,
    ExcelConfigurationRequired,
    PowerPointChunkBuilder,
    build_embedding_fingerprint,
    build_excel_preview,
)
from fast_app.ingestion.processing.structured_document_processor import (
    DocumentProcessingError,
    StructuredDocumentProcessor,
)
from fast_app.ingestion.stores.rag_store_writer import (
    delete_es_docs_by_doc_ids,
    delete_milvus_docs_by_doc_ids,
    replace_docs_rag_stores,
)
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock


logger = get_logger(__name__)
RETRY_DELAYS_SECONDS = (5, 30)


class PermanentImportError(RuntimeError):
    """输入或目标状态导致的永久失败，不应通过自动重试解决。"""

    def __init__(self, code: str, message: str) -> None:
        """保存写入任务 error_code 的稳定错误码。"""

        super().__init__(message)
        self.code = code


class ImportLeaseLostError(RuntimeError):
    """Worker 已不再拥有任务，必须立即停止发布和索引写入。"""

    pass


class ImportAwaitingConfiguration(RuntimeError):
    """Excel 已安全暂停并释放租约，等待用户确认 Profile。"""

    pass


class KnowledgeImportWorker:
    """领取并执行持久化 Office 导入任务，同时维护任务租约。"""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_client: BaseEmbeddingClient,
        elasticsearch_client: AsyncElasticsearch,
        milvus_client: AsyncMilvusClient,
        worker_id: str,
        store_mutation_lock: StoreMutationLock | None = None,
    ) -> None:
        """注入数据库、Embedding 和两个检索存储客户端。"""

        self.settings = settings
        self.session_factory = session_factory
        self.embedding_client = embedding_client
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client
        self.worker_id = worker_id
        self.store_mutation_lock = store_mutation_lock
        self.document_processor = StructuredDocumentProcessor(settings=settings)

    async def run_once(self) -> bool:
        """至多领取并处理一个任务；返回值表示本轮是否领到任务。"""

        async with self.session_factory() as session:
            claimed = await KnowledgeImportJobRepository(session).claim_next(self.worker_id)
        if claimed is None:
            return False
        await self._run_claimed(claimed)
        return True

    async def _run_claimed(self, claimed: ClaimedImportJob) -> None:
        """在请求追踪上下文和独立心跳保护下执行已领取任务。"""

        job = claimed.row
        request_tokens = set_request_context(job.request_id or job.id, job.trace_id)
        lease_lost = asyncio.Event()
        # 心跳独立于阶段切换运行，Embedding/索引等长阶段也能每 60 秒续租。
        heartbeat = asyncio.create_task(self._heartbeat(job.id, lease_lost))
        try:
            if claimed.recovery_exhausted:
                await self._assert_lease(job.id, lease_lost)
                outcome = await self._recover_outputs(job, lease_lost)
                if outcome == "forward_completed":
                    return
                await self._mark_failed(
                    job,
                    (
                        "KNOWLEDGE_IMPORT_ROLLBACK_FAILED"
                        if outcome == "rollback_failed"
                        else "KNOWLEDGE_IMPORT_RETRIES_EXHAUSTED"
                    ),
                    (
                        "旧文件仍保留，但检索存储回滚失败"
                        if outcome == "rollback_failed"
                        else "导入任务崩溃恢复时已达到最大尝试次数"
                    ),
                    preserve_staging=outcome == "rollback_failed",
                )
                return

            async with langsmith_trace(
                settings=self.settings,
                name="knowledge_import.worker",
                run_type="chain",
                inputs={
                    "job_id": job.id,
                    "document_type": job.document_type,
                    "file_size": job.file_size,
                },
                metadata=build_langsmith_metadata(
                    self.settings,
                    sensitive_metadata={"user_id": job.user_id},
                    operation="knowledge_import",
                    job_id=job.id,
                    department_code=job.department_code,
                ),
                tags=build_langsmith_tags(
                    self.settings,
                    "knowledge-import",
                    f"document-type:{job.document_type}",
                ),
            ) as trace_run:
                document_count, chunk_count, warnings = await self._process(job, lease_lost)
                if trace_run is not None:
                    trace_run.add_outputs(
                        {
                            "status": "succeeded",
                            "document_count": document_count,
                            "chunk_count": chunk_count,
                            "warning_count": len(warnings),
                        }
                    )
        except ImportAwaitingConfiguration:
            logger.info(
                "knowledge_import %s",
                format_log_fields(
                    event="knowledge_import.awaiting_configuration", job_id=job.id
                ),
            )
        except ImportLeaseLostError:
            # 所有权丢失后不改任务状态；新所有者负责继续或收尾。
            logger.warning(
                "knowledge_import %s",
                format_log_fields(event="knowledge_import.lease_lost", job_id=job.id),
            )
        except PermanentImportError as exc:
            logger.warning(
                "knowledge_import %s",
                format_log_fields(
                    event="knowledge_import.failed",
                    job_id=job.id,
                    error_code=exc.code,
                ),
            )
            # 只有仍持有租约的 Worker 才能清理共享产物并写入 failed。
            if await self._still_owns_lease(job.id, lease_lost):
                outcome = await self._recover_outputs(job, lease_lost)
                if outcome != "forward_completed":
                    await self._mark_failed(
                        job,
                        (
                            "KNOWLEDGE_IMPORT_ROLLBACK_FAILED"
                            if outcome == "rollback_failed"
                            else exc.code
                        ),
                        (
                            "旧文件仍保留，但检索存储回滚失败"
                            if outcome == "rollback_failed"
                            else str(exc)
                        ),
                        preserve_staging=outcome == "rollback_failed",
                    )
        except Exception:
            logger.exception(
                "knowledge_import %s",
                format_log_fields(
                    event="knowledge_import.external_failure",
                    job_id=job.id,
                    attempt_count=job.attempt_count,
                ),
            )
            if job.attempt_count < job.max_attempts:
                # 短暂外部故障使用有限退避；等待期间心跳任务仍持续续租。
                delay = RETRY_DELAYS_SECONDS[min(job.attempt_count - 1, 1)]
                await asyncio.sleep(delay)
                if await self._still_owns_lease(job.id, lease_lost):
                    await self._mark_retry(job)
            else:
                if await self._still_owns_lease(job.id, lease_lost):
                    outcome = await self._recover_outputs(job, lease_lost)
                    if outcome != "forward_completed":
                        await self._mark_failed(
                            job,
                            (
                                "KNOWLEDGE_IMPORT_ROLLBACK_FAILED"
                                if outcome == "rollback_failed"
                                else "KNOWLEDGE_IMPORT_EXTERNAL_FAILURE"
                            ),
                            (
                                "旧文件仍保留，但检索存储回滚失败"
                                if outcome == "rollback_failed"
                                else "外部服务处理失败，已达到最大尝试次数"
                            ),
                            preserve_staging=outcome == "rollback_failed",
                        )
        finally:
            # 无论成功、失败还是失租，都要停止后台心跳并还原请求上下文。
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            reset_request_context(*request_tokens)

    async def _process(
        self,
        job: KnowledgeIngestionJobTable,
        lease_lost: asyncio.Event,
    ) -> tuple[int, int, list[dict[str, str]]]:
        """执行结构化解析、Chunk 差异同步、验证和最后文件发布。"""

        await self._phase(job.id, "validating", lease_lost)
        staged_path = Path(job.staged_path)
        if (
            not staged_path.is_file()
            or await asyncio.to_thread(_sha256_file, staged_path) != job.sha256
        ):
            raise PermanentImportError(
                "KNOWLEDGE_IMPORT_STAGING_MISSING",
                "导入暂存文件不存在或哈希不一致",
            )
        await self._assert_document_version(job)
        try:
            await asyncio.to_thread(
                validate_knowledge_document_package,
                staged_path,
                document_type=job.document_type,
                limits=KnowledgeDocumentValidationLimits(
                    max_file_bytes=self.settings.max_upload_file_bytes,
                    max_pdf_pages=self.settings.pdf_max_pages,
                ),
            )
        except DocumentPackageValidationError as exc:
            raise PermanentImportError(exc.code, str(exc)) from exc

        await self._phase(job.id, "extracting", lease_lost)
        options = ChunkBuildOptions(
            source=self.settings.ingestion_source_name,
            max_chars=self.settings.markdown_chunk_max_chars,
            overlap_chars=self.settings.markdown_chunk_overlap_chars,
            max_tokens=self.settings.markdown_chunk_max_tokens,
            min_chars=self.settings.markdown_chunk_min_chars,
        )
        fingerprint = build_embedding_fingerprint(self.settings)
        processing_warnings: list[dict[str, str]] = []
        try:
            if job.document_type == "spreadsheet":
                document = await asyncio.to_thread(self._load_document, job)
                profile = job.excel_profile_snapshot_json
                if profile is None:
                    preview = await asyncio.to_thread(build_excel_preview, document)
                    await self._pause_for_excel_configuration(job, preview)
                    raise ImportAwaitingConfiguration()
                chunks = ExcelChunkBuilder().build(
                    document,
                    options,
                    profile=profile,
                    embedding_fingerprint=fingerprint,
                )
            else:
                processed = await self.document_processor.process_file(
                    staged_path,
                    document_type=job.document_type,
                    source_path=job.target_path,
                    options=options,
                    document_metadata={
                        "visibility": "department",
                        "allowed_departments": [job.department_code],
                        "allowed_users": [],
                        "permission_source": "import_job_department",
                    },
                    before_external_call=lambda: self._assert_lease(
                        job.id, lease_lost
                    ),
                )
                chunks = processed.chunks
                processing_warnings = [
                    {"code": warning.code, "message": warning.message}
                    for warning in processed.warnings
                ]
                document = LoadedDocument(
                    source_path=job.target_path,
                    content="\n".join(chunk.content for chunk in chunks),
                    document_type=job.document_type,
                    metadata=(dict(chunks[0].metadata) if chunks else {}),
                )
        except ExcelConfigurationRequired as exc:
            await self._pause_for_excel_configuration(job, exc.preview)
            raise ImportAwaitingConfiguration() from exc
        except DocumentProcessingError as exc:
            raise PermanentImportError(exc.code, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise PermanentImportError(
                "KNOWLEDGE_IMPORT_PARSE_FAILED",
                "Office 文档解析失败",
            ) from exc

        await self._phase(job.id, "chunking", lease_lost)

        compatibility_document = LoadedDocument(
            source_path=document.source_path,
            content="\n".join(chunk.content for chunk in chunks),
            document_type=job.document_type,
            metadata=document.metadata,
        )
        report = validate_ingestion_result([compatibility_document], chunks)
        if not report.passed:
            raise PermanentImportError(
                "KNOWLEDGE_IMPORT_CHUNK_VALIDATION_FAILED",
                "文档分块校验失败",
            )
        warnings = [
            {"code": issue.code, "message": issue.message}
            for issue in report.issues
            if issue.level == "warning"
        ]
        warnings.extend(
            {"code": code, "message": code}
            for code in document.metadata.get("extraction_warnings", [])
        )
        warnings.extend(processing_warnings)

        doc_id = str(job.doc_id)
        await self._phase(job.id, "loading_existing_chunks", lease_lost)
        es_states, milvus_states = await asyncio.gather(
            load_es_chunk_states(self.elasticsearch_client, self.settings, doc_id),
            load_milvus_chunk_states(
                self.milvus_client,
                self.settings,
                doc_id,
            ),
        )
        await self._phase(job.id, "diffing", lease_lost)
        diff = build_chunk_diff(
            chunks,
            es_states,
            milvus_states,
            embedding_dim=self.settings.embedding_dim,
        )

        await self._phase(job.id, "embedding", lease_lost)
        vectors = (
            await self.embedding_client.embed_documents(
                [chunk.content for chunk in diff.embed]
            )
            if diff.embed
            else []
        )
        if len(vectors) != len(diff.embed) or any(
            len(vector) != self.settings.embedding_dim for vector in vectors
        ):
            raise RuntimeError("embedding 数量或维度不匹配")

        async with self._store_mutation_guard():
            # 等待全局锁可能跨越多个 heartbeat 周期，进入共享 mutation 前必须
            # 重新证明当前 Worker 仍然拥有任务。
            await self._phase(job.id, "indexing", lease_lost)
            await self._assert_lease(job.id, lease_lost)
            await apply_chunk_diff(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                diff=diff,
                embedded_vectors=vectors,
            )
            await self._phase(job.id, "verifying", lease_lost)
            await verify_chunk_convergence(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                chunks=chunks,
            )

            # 检索存储、文件和任务事实处于同一全局 mutation 临界区。
            await self._phase(job.id, "publishing", lease_lost)
            await self._assert_document_version(job)
            await self._assert_lease(job.id, lease_lost)
            await asyncio.to_thread(_publish_file, job, self.settings.knowledge_base_dir)

            async with self.session_factory() as session:
                succeeded = await KnowledgeImportJobRepository(session).mark_succeeded(
                    job.id,
                    self.worker_id,
                    document_count=1,
                    chunk_count=len(chunks),
                    warnings=warnings,
                    diff_counts=diff.counts,
                )
            if not succeeded:
                raise ImportLeaseLostError("完成任务前租约已丢失")
        staged_path.unlink(missing_ok=True)
        return 1, len(chunks), warnings

    def _load_document(self, job: KnowledgeIngestionJobTable):
        """返回 Office 专属结构化文档，并覆盖为服务端可信 ACL。"""

        return self._load_document_path(job, Path(job.staged_path))

    def _load_document_path(
        self, job: KnowledgeIngestionJobTable, input_path: Path
    ):
        """从指定物理文件解析内容，但始终使用注册表 source_path 生成身份。"""

        loader = (
            PowerPointDocumentLoader()
            if job.document_type == "powerpoint"
            else ExcelDocumentLoader()
        )
        document = loader.load_structured_file(
            input_path,
            source_path=job.target_path,
            knowledge_base_dir=self.settings.knowledge_base_dir,
        )
        # 文件内元数据不能决定权限；导入任务记录的部门是唯一可信来源。
        document.metadata.update(
            visibility="department",
            allowed_departments=[job.department_code],
            allowed_users=[],
            permission_source="import_job_department",
        )
        return document

    async def _pause_for_excel_configuration(
        self,
        job: KnowledgeIngestionJobTable,
        preview: dict,
    ) -> None:
        """持久化最新预览；条件更新失败说明当前 Worker 已失去所有权。"""

        async with self.session_factory() as session:
            paused = await KnowledgeImportJobRepository(
                session
            ).mark_awaiting_configuration(
                job.id,
                self.worker_id,
                preview=preview,
            )
        if not paused:
            raise ImportLeaseLostError("保存 Excel 预览前租约已丢失")

    async def _assert_document_version(self, job: KnowledgeIngestionJobTable) -> None:
        """在索引与文件提交边界重新检查注册表中的乐观锁版本。"""

        async with self.session_factory() as session:
            document = await KnowledgeImportJobRepository(session).get_document(
                str(job.doc_id)
            )
        if document is None:
            raise PermanentImportError(
                "KNOWLEDGE_DOCUMENT_NOT_REGISTERED", "知识文档注册记录不存在"
            )
        if job.operation == "update" and document.current_sha256 != job.base_sha256:
            raise PermanentImportError(
                "KNOWLEDGE_DOCUMENT_VERSION_CONFLICT", "知识文档版本已经变化"
            )

    async def _phase(self, job_id: str, phase: str, lease_lost: asyncio.Event) -> None:
        """切换处理阶段；条件更新失败时立即传播失租信号。"""

        await self._assert_lease(job_id, lease_lost)
        async with self.session_factory() as session:
            updated = await KnowledgeImportJobRepository(session).set_phase(
                job_id,
                self.worker_id,
                phase,
            )
        if not updated:
            lease_lost.set()
            raise ImportLeaseLostError(f"切换到 {phase} 前租约已丢失")
        logger.info(
            "knowledge_import %s",
            format_log_fields(event="knowledge_import.phase", job_id=job_id, phase=phase),
        )

    async def _assert_lease(self, job_id: str, lease_lost: asyncio.Event) -> None:
        """确认并续租当前任务，失败时阻断后续共享状态写入。"""

        if lease_lost.is_set():
            raise ImportLeaseLostError("任务租约已丢失")
        async with self.session_factory() as session:
            renewed = await KnowledgeImportJobRepository(session).renew_lease(
                job_id,
                self.worker_id,
            )
        if not renewed:
            lease_lost.set()
            raise ImportLeaseLostError("任务租约已丢失")

    async def _still_owns_lease(
        self,
        job_id: str,
        lease_lost: asyncio.Event,
    ) -> bool:
        """在异常处理路径中尝试确认所有权，不把失租再次抛出。"""

        try:
            await self._assert_lease(job_id, lease_lost)
        except ImportLeaseLostError:
            return False
        return True

    async def _heartbeat(self, job_id: str, lease_lost: asyncio.Event) -> None:
        """每隔固定时间独立续租，数据库拒绝续租时设置共享失租事件。"""

        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                async with self.session_factory() as session:
                    renewed = await KnowledgeImportJobRepository(session).renew_lease(
                        job_id,
                        self.worker_id,
                    )
                if not renewed:
                    lease_lost.set()
                    return
            except Exception:
                # 临时数据库异常只记录日志；租约到期后的新 Worker 会通过条件更新接管。
                logger.exception(
                    "knowledge_import %s",
                    format_log_fields(event="knowledge_import.heartbeat_failed", job_id=job_id),
                )

    async def _mark_retry(self, job: KnowledgeIngestionJobTable) -> None:
        """记录外部故障并把仍由当前 Worker 持有的任务放回队列。"""

        async with self.session_factory() as session:
            await KnowledgeImportJobRepository(session).mark_retry(
                job.id,
                self.worker_id,
                error_code="KNOWLEDGE_IMPORT_EXTERNAL_FAILURE",
                error_message="外部服务处理失败，任务将自动重试",
            )

    async def _mark_failed(
        self,
        job: KnowledgeIngestionJobTable,
        code: str,
        message: str,
        *,
        preserve_staging: bool = False,
    ) -> None:
        """记录最终失败；只有条件更新成功后才删除 staging 文件。"""

        async with self.session_factory() as session:
            failed = await KnowledgeImportJobRepository(session).mark_failed(
                job.id,
                self.worker_id,
                error_code=code,
                error_message=message,
            )
        if failed and not preserve_staging:
            Path(job.staged_path).unlink(missing_ok=True)

    async def _recover_outputs(
        self,
        job: KnowledgeIngestionJobTable,
        lease_lost: asyncio.Event,
    ) -> str:
        """Create 清理；Update 按文件提交点选择回滚旧版或向前完成。"""

        if job.operation == "create":
            await self._cleanup_created_outputs(job, lease_lost)
            return "restored"
        try:
            await self._phase(job.id, "repairing", lease_lost)
            target = _physical_target(job.target_path, self.settings.knowledge_base_dir)
            if not target.is_file():
                return "rollback_failed"
            target_sha = await asyncio.to_thread(_sha256_file, target)
            if target_sha == job.new_sha256:
                # 文件替换是提交点；此后绝不回滚，只重建新索引并补数据库提交。
                chunks, warnings = await self._repair_stores_from_file(
                    job,
                    target,
                    profile=job.excel_profile_snapshot_json,
                    lease_lost=lease_lost,
                )
                async with self.session_factory() as session:
                    succeeded = await KnowledgeImportJobRepository(
                        session
                    ).mark_succeeded(
                        job.id,
                        self.worker_id,
                        document_count=1,
                        chunk_count=len(chunks),
                        warnings=warnings,
                        diff_counts={
                            "unchanged": 0,
                            "metadata_only": 0,
                            "added": 0,
                            "changed": len(chunks),
                            "removed": 0,
                            "repaired": len(chunks),
                            "embedded": len(chunks),
                        },
                    )
                if not succeeded:
                    raise ImportLeaseLostError("向前修复提交前租约已丢失")
                Path(job.staged_path).unlink(missing_ok=True)
                return "forward_completed"
            if target_sha != job.base_sha256:
                return "rollback_failed"

            profile = None
            if job.document_type == "spreadsheet":
                async with self.session_factory() as session:
                    active = await KnowledgeImportJobRepository(
                        session
                    ).get_active_excel_profile(str(job.doc_id))
                profile = (
                    {
                        "mode": active.mode,
                        "profile_name": active.profile_name,
                        "sheets": list(active.sheet_configs_json),
                    }
                    if active is not None
                    else {"mode": "section", "sheets": []}
                )
            await self._repair_stores_from_file(
                job,
                target,
                profile=profile,
                lease_lost=lease_lost,
            )
            return "restored"
        except ImportLeaseLostError:
            raise
        except Exception:
            logger.exception(
                "knowledge_import %s",
                format_log_fields(
                    event="knowledge_import.rollback_failed", job_id=job.id
                ),
            )
            # 保留旧目标文件和 staging，供管理员或后续恢复任务检查。
            return "rollback_failed"

    async def _repair_stores_from_file(
        self,
        job: KnowledgeIngestionJobTable,
        path: Path,
        *,
        profile: dict | None,
        lease_lost: asyncio.Event,
    ) -> tuple[list, list[dict[str, str]]]:
        """解析指定版本并全量替换双存储，供终态回滚和提交后向前修复。"""

        options = ChunkBuildOptions(
            source=self.settings.ingestion_source_name,
            max_chars=self.settings.markdown_chunk_max_chars,
            overlap_chars=self.settings.markdown_chunk_overlap_chars,
            max_tokens=self.settings.markdown_chunk_max_tokens,
            min_chars=self.settings.markdown_chunk_min_chars,
        )
        fingerprint = build_embedding_fingerprint(self.settings)
        processing_warnings: list[dict[str, str]] = []
        if job.document_type == "spreadsheet":
            document = await asyncio.to_thread(self._load_document_path, job, path)
            if profile is None:
                raise RuntimeError("Excel 修复缺少 Profile")
            chunks = ExcelChunkBuilder().build(
                document,
                options,
                profile=profile,
                embedding_fingerprint=fingerprint,
            )
        else:
            processed = await self.document_processor.process_file(
                path,
                document_type=job.document_type,
                source_path=job.target_path,
                options=options,
                document_metadata={
                    "visibility": "department",
                    "allowed_departments": [job.department_code],
                    "allowed_users": [],
                    "permission_source": "import_job_department",
                },
                before_external_call=lambda: self._assert_lease(job.id, lease_lost),
            )
            chunks = processed.chunks
            processing_warnings = [
                {"code": warning.code, "message": warning.message}
                for warning in processed.warnings
            ]
        vectors = await self.embedding_client.embed_documents(
            [chunk.content for chunk in chunks]
        )
        if len(vectors) != len(chunks) or any(
            len(vector) != self.settings.embedding_dim for vector in vectors
        ):
            raise RuntimeError("修复 Embedding 数量或维度不匹配")
        async with self._store_mutation_guard():
            await self._assert_lease(job.id, lease_lost)
            await replace_docs_rag_stores(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                chunks=chunks,
                vectors=vectors,
            )
            await verify_chunk_convergence(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                chunks=chunks,
            )
        warnings = [
            {"code": code, "message": code}
            for code in (
                document.metadata.get("extraction_warnings", [])
                if job.document_type == "spreadsheet"
                else []
            )
        ]
        warnings.extend(processing_warnings)
        return chunks, warnings

    async def _cleanup_created_outputs(
        self,
        job: KnowledgeIngestionJobTable,
        lease_lost: asyncio.Event,
    ) -> None:
        """仅 Create 失败允许删除新文件和该 doc_id 的全部 Chunk。"""

        async with self._store_mutation_guard():
            await self._assert_lease(job.id, lease_lost)
            target = _physical_target(job.target_path, self.settings.knowledge_base_dir)
            if (
                target.is_file()
                and await asyncio.to_thread(_sha256_file, target) == job.sha256
            ):
                target.unlink(missing_ok=True)
            await delete_es_docs_by_doc_ids(
                self.elasticsearch_client, self.settings, [str(job.doc_id)]
            )
            await delete_milvus_docs_by_doc_ids(
                self.milvus_client, self.settings, [str(job.doc_id)]
            )

    @asynccontextmanager
    async def _store_mutation_guard(self):
        if self.store_mutation_lock is None:
            yield
            return
        async with self.store_mutation_lock.hold():
            yield


def _publish_file(job: KnowledgeIngestionJobTable, knowledge_base_dir: str) -> None:
    """Create 独占发布；Update 经同盘临时文件执行原子替换。"""

    source = Path(job.staged_path)
    target = _physical_target(job.target_path, knowledge_base_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if job.operation == "update":
        if not target.is_file():
            raise PermanentImportError(
                "KNOWLEDGE_IMPORT_TARGET_MISSING", "待更新目标文件不存在"
            )
        current_sha = _sha256_file(target)
        if current_sha == job.new_sha256:
            return
        if current_sha != job.base_sha256:
            raise PermanentImportError(
                "KNOWLEDGE_DOCUMENT_VERSION_CONFLICT", "目标文件版本已经变化"
            )
        temporary = target.with_name(f".{target.name}.{job.id}.tmp")
        try:
            if temporary.exists() and _sha256_file(temporary) != job.new_sha256:
                temporary.unlink()
            if not temporary.exists():
                with source.open("rb") as input_file, temporary.open("xb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
            if _sha256_file(temporary) != job.new_sha256:
                raise RuntimeError("发布临时文件哈希不一致")
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return

    if target.exists():
        # 崩溃重跑可能已完成文件发布，相同内容无需再次复制。
        if _sha256_file(target) == job.sha256:
            return
        raise PermanentImportError(
            "KNOWLEDGE_IMPORT_TARGET_CONFLICT",
            "目标文档已存在且内容不同",
        )
    try:
        # "xb" 保证并发任务不能静默覆盖已经存在的知识文件。
        with source.open("rb") as input_file, target.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file)
    except FileExistsError:
        if _sha256_file(target) != job.sha256:
            raise PermanentImportError(
                "KNOWLEDGE_IMPORT_TARGET_CONFLICT",
                "目标文档已存在且内容不同",
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _physical_target(target_path: str, knowledge_base_dir: str) -> Path:
    """解析并验证目标文件必须位于知识库根目录内。"""

    root = Path(knowledge_base_dir).resolve()
    target = Path(target_path).resolve()
    if not target.is_relative_to(root):
        raise PermanentImportError(
            "KNOWLEDGE_IMPORT_TARGET_OUTSIDE_ROOT",
            "目标文档路径超出知识库目录",
        )
    return target


def _sha256_file(path: Path) -> str:
    """以固定大小分块计算文件 SHA-256，避免把 Office 文件整体读入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


async def run_worker(*, once: bool, use_mock_embeddings: bool) -> int:
    """组装 Worker 依赖并以单次或常驻轮询模式运行。"""

    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    elasticsearch_client = build_elasticsearch_client(settings)
    milvus_client = build_milvus_client(settings)
    worker = KnowledgeImportWorker(
        settings=settings,
        session_factory=session_factory,
        embedding_client=build_embedding_client(settings, use_mock_embeddings),
        elasticsearch_client=elasticsearch_client,
        milvus_client=milvus_client,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        store_mutation_lock=StoreMutationLock(engine),
    )
    try:
        if once:
            await worker.run_once()
            return 0
        while True:
            # 队列为空时短暂让出执行权，避免空轮询占满 CPU 和数据库连接。
            if not await worker.run_once():
                await asyncio.sleep(2)
    finally:
        await elasticsearch_client.close()
        await milvus_client.close()
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    """构建知识导入 Worker 的命令行参数。"""

    parser = argparse.ArgumentParser(description="处理持久化知识文档导入任务")
    parser.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="本地测试使用固定维度 Mock Embedding",
    )
    parser.add_argument(
        "--no-es-auth",
        action="store_true",
        help="本地 Elasticsearch 未启用认证时忽略 .env 中的认证字段",
    )
    return parser


def main() -> int:
    """解析命令行配置并启动异步 Worker。"""

    args = build_parser().parse_args()
    apply_arg_overrides(args)
    return asyncio.run(
        run_worker(once=args.once, use_mock_embeddings=args.mock_embeddings)
    )


if __name__ == "__main__":
    raise SystemExit(main())
