from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.gitlab_tables import (
    GitLabChangeRequestTable,
    GitLabDocumentTable,
    GitLabSourceTable,
    GitLabSyncJobTable,
    GitLabWebhookDeliveryTable,
    KnowledgeChangeEventTable,
    KnowledgePublicationStateTable,
    KnowledgePublicationTable,
)


ACTIVE_JOB_STATUSES = {"pending", "running", "publishing", "retry_wait"}


@dataclass(frozen=True)
class DeliveryResult:
    duplicate: bool
    job: GitLabSyncJobTable | None


class GitLabRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_source(self, source_id: str) -> GitLabSourceTable | None:
        return await self.session.get(GitLabSourceTable, source_id)

    async def list_sources(self) -> list[GitLabSourceTable]:
        rows = await self.session.scalars(
            select(GitLabSourceTable).order_by(GitLabSourceTable.id)
        )
        return list(rows.all())

    async def save_source(
        self,
        source: GitLabSourceTable,
    ) -> GitLabSourceTable:
        self.session.add(source)
        await self.session.commit()
        await self.session.refresh(source)
        return source

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[GitLabSyncJobTable]:
        stmt = select(GitLabSyncJobTable)
        if status:
            stmt = stmt.where(GitLabSyncJobTable.status == status)
        rows = await self.session.scalars(
            stmt.order_by(GitLabSyncJobTable.created_at.desc()).limit(limit)
        )
        return list(rows.all())

    async def get_job(self, job_id: str) -> GitLabSyncJobTable | None:
        return await self.session.get(GitLabSyncJobTable, job_id)

    async def enqueue(
        self,
        *,
        source_id: str,
        mode: str,
        target_sha: str,
        base_sha: str | None,
    ) -> GitLabSyncJobTable:
        source = await self.session.scalar(
            select(GitLabSourceTable)
            .where(GitLabSourceTable.id == source_id)
            .with_for_update()
        )
        if source is None:
            raise LookupError("GitLab Source 不存在")
        # desired_sha 表示“最终必须追赶到哪里”。即使已有任务正在运行，新提交也不会丢失。
        source.desired_sha = target_sha
        active = await self.session.scalar(
            select(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.source_id == source_id,
                GitLabSyncJobTable.status.in_(ACTIVE_JOB_STATUSES),
            )
            .with_for_update()
        )
        if active is not None:
            # 每个 Source 只保留一个活动任务。尚未开始的任务直接推进 target_sha，
            # 正在运行的任务保持冻结 SHA，完成后由 Worker 再追赶最新 desired_sha。
            if active.status in {"pending", "retry_wait"}:
                active.target_sha = target_sha
                if mode in {"full", "reconcile", "bootstrap"}:
                    active.mode = mode
            active.updated_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(active)
            return active
        job = GitLabSyncJobTable(
            id=f"gitlab_job_{uuid4().hex}",
            source_id=source_id,
            mode=mode,
            base_sha=base_sha,
            target_sha=target_sha,
            status="pending",
            phase="queued",
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def register_delivery_and_enqueue(
        self,
        *,
        source: GitLabSourceTable,
        delivery_key: str,
        event_uuid: str | None,
        event_type: str,
        before_sha: str,
        after_sha: str,
        payload_hash: str,
    ) -> DeliveryResult:
        existing = await self.session.get(
            GitLabWebhookDeliveryTable, delivery_key
        )
        if existing is not None:
            return DeliveryResult(duplicate=True, job=None)
        # Delivery 审计记录与任务入队使用同一个数据库事务；这样不会出现
        # “已经记为接收，但任务没有创建”的半完成状态。
        self.session.add(
            GitLabWebhookDeliveryTable(
                delivery_key=delivery_key,
                source_id=source.id,
                event_uuid=event_uuid,
                event_type=event_type,
                before_sha=before_sha,
                after_sha=after_sha,
                payload_hash=payload_hash,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return DeliveryResult(duplicate=True, job=None)

        source.desired_sha = after_sha
        active = await self.session.scalar(
            select(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.source_id == source.id,
                GitLabSyncJobTable.status.in_(ACTIVE_JOB_STATUSES),
            )
            .with_for_update()
        )
        if active is not None:
            if active.status in {"pending", "retry_wait"}:
                active.target_sha = after_sha
                if (
                    source.last_synced_sha
                    and before_sha
                    and before_sha != source.last_synced_sha
                ):
                    # before_sha 与上次正式发布 SHA 不连续，说明可能漏事件或发生强推；
                    # 此时不再相信增量 Compare，升级为 Archive 全量对账。
                    active.mode = "full"
            active.updated_at = datetime.now(UTC)
            job = active
        else:
            mode = (
                "full"
                if not source.last_synced_sha
                or (
                    before_sha
                    and before_sha != source.last_synced_sha
                )
                else "incremental"
            )
            job = GitLabSyncJobTable(
                id=f"gitlab_job_{uuid4().hex}",
                source_id=source.id,
                mode=mode,
                base_sha=source.last_synced_sha,
                target_sha=after_sha,
                status="pending",
                phase="queued",
            )
            self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return DeliveryResult(duplicate=False, job=job)

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GitLabSyncJobTable | None:
        now = datetime.now(UTC)
        job = await self.session.scalar(
            select(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.attempt_count < GitLabSyncJobTable.max_attempts,
                or_(
                    GitLabSyncJobTable.status.in_(["pending", "retry_wait"]),
                    and_(
                        GitLabSyncJobTable.status.in_(["running", "publishing"]),
                        GitLabSyncJobTable.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(GitLabSyncJobTable.created_at)
            # 多个 Worker 同时查询时，数据库锁住当前行并跳过其他 Worker 已锁行，
            # 从而保证同一任务不会被两个 Worker 同时领取。
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            await self.session.rollback()
            return None
        job.status = "running"
        job.phase = "claiming"
        job.worker_id = worker_id
        # 租约让“Worker 进程崩溃”可恢复：心跳停止后，过期任务能被其他实例重新领取。
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.error_code = None
        job.error_message = None
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        result = await self.session.execute(
            update(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.id == job_id,
                GitLabSyncJobTable.worker_id == worker_id,
                GitLabSyncJobTable.status.in_(["running", "publishing"]),
            )
            .values(
                lease_expires_at=datetime.now(UTC)
                + timedelta(seconds=lease_seconds),
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        return bool(result.rowcount)

    async def update_job_phase(
        self,
        *,
        job_id: str,
        worker_id: str,
        phase: str,
        publishing: bool = False,
    ) -> None:
        await self.session.execute(
            update(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.id == job_id,
                GitLabSyncJobTable.worker_id == worker_id,
            )
            .values(
                phase=phase,
                status="publishing" if publishing else "running",
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.commit()

    async def assert_job_owned(self, job_id: str, worker_id: str) -> None:
        owned = await self.session.scalar(
            select(func.count())
            .select_from(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.id == job_id,
                GitLabSyncJobTable.worker_id == worker_id,
                GitLabSyncJobTable.status.in_(["running", "publishing"]),
                GitLabSyncJobTable.lease_expires_at > datetime.now(UTC),
            )
        )
        if not owned:
            raise RuntimeError("GitLab 同步任务租约已丢失")

    async def mark_job_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool = True,
    ) -> None:
        job = await self.session.scalar(
            select(GitLabSyncJobTable)
            .where(
                GitLabSyncJobTable.id == job_id,
                GitLabSyncJobTable.worker_id == worker_id,
            )
            .with_for_update()
        )
        if job is None:
            await self.session.rollback()
            return
        exhausted = not retryable or job.attempt_count >= job.max_attempts
        job.status = "failed" if exhausted else "retry_wait"
        job.phase = "failed"
        job.error_code = error_code
        job.error_message = error_message[:2000]
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC) if exhausted else None
        if job.candidate_version is not None:
            publication = await self.session.get(
                KnowledgePublicationTable, job.candidate_version
            )
            if publication is not None and publication.sync_job_id == job.id:
                publication.status = "failed"
        await self.session.commit()

    async def complete_noop(
        self,
        *,
        job_id: str,
        source_id: str,
        worker_id: str,
        target_sha: str,
    ) -> None:
        job = await self.session.get(GitLabSyncJobTable, job_id)
        source = await self.session.get(GitLabSourceTable, source_id)
        if (
            job is None
            or source is None
            or job.worker_id != worker_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= datetime.now(UTC)
        ):
            raise RuntimeError("GitLab 空变更任务租约已丢失")
        source.last_synced_sha = target_sha
        job.status = "succeeded"
        job.phase = "no_changes"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)
        await self.session.commit()

    async def list_documents(
        self,
        source_id: str,
    ) -> list[GitLabDocumentTable]:
        rows = await self.session.scalars(
            select(GitLabDocumentTable).where(
                GitLabDocumentTable.source_id == source_id,
                GitLabDocumentTable.status == "active",
            )
        )
        return list(rows.all())

    async def get_document(self, doc_id: str) -> GitLabDocumentTable | None:
        return await self.session.get(GitLabDocumentTable, doc_id)

    async def find_document_by_path(
        self,
        repository_path: str,
    ) -> GitLabDocumentTable | None:
        return await self.session.scalar(
            select(GitLabDocumentTable).where(
                GitLabDocumentTable.repository_path == repository_path,
                GitLabDocumentTable.status == "active",
            )
        )

    async def find_source_by_department(
        self,
        department_code: str,
    ) -> GitLabSourceTable | None:
        return await self.session.scalar(
            select(GitLabSourceTable).where(
                GitLabSourceTable.department_code == department_code,
                GitLabSourceTable.status == "active",
            )
        )

    async def reserve_publication(
        self,
        *,
        source_id: str,
        job_id: str,
        target_sha: str,
    ) -> KnowledgePublicationTable:
        state = await self.session.scalar(
            select(KnowledgePublicationStateTable)
            .where(KnowledgePublicationStateTable.id == 1)
            .with_for_update()
        )
        if state is None:
            state = KnowledgePublicationStateTable(id=1, active_version=0)
            self.session.add(state)
            await self.session.flush()
        version = state.active_version + 1
        # active_version 行是全局发布锁。不同 Source 可以并行准备数据，
        # 但候选版本号和最终指针切换必须串行，避免两个发布抢同一个版本。
        publication = await self.session.get(KnowledgePublicationTable, version)
        if publication is None:
            publication = KnowledgePublicationTable(
                version=version,
                previous_version=state.active_version,
                source_id=source_id,
                sync_job_id=job_id,
                target_sha=target_sha,
                status="building",
            )
            self.session.add(publication)
        else:
            if publication.sync_job_id != job_id:
                await self.session.rollback()
                raise RuntimeError(
                    "上一候选知识版本尚未由原任务完成，不能复用其版本号"
                )
            publication.source_id = source_id
            publication.sync_job_id = job_id
            publication.target_sha = target_sha
            publication.status = "building"
            publication.validation_json = {}
        job = await self.session.get(GitLabSyncJobTable, job_id)
        if job is not None:
            job.candidate_version = version
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def retry_job(self, job_id: str) -> GitLabSyncJobTable:
        job = await self.session.scalar(
            select(GitLabSyncJobTable)
            .where(GitLabSyncJobTable.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError("GitLab 同步任务不存在")
        if job.status not in {"failed", "retry_wait"}:
            raise ValueError("只有失败或等待重试的任务可以重试")
        source = await self.session.get(GitLabSourceTable, job.source_id)
        if source is None:
            raise LookupError("GitLab Source 不存在")
        job.status = "pending"
        job.phase = "queued"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = None
        job.attempt_count = 0
        job.error_code = None
        job.error_message = None
        job.base_sha = source.last_synced_sha
        job.target_sha = source.desired_sha or job.target_sha
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def publish(
        self,
        *,
        job_id: str,
        source_id: str,
        version: int,
        target_sha: str,
        manifests: list[dict],
        changes: list[dict],
        parent_count: int,
        child_count: int,
        validation: dict,
        worker_id: str,
    ) -> None:
        state = await self.session.scalar(
            select(KnowledgePublicationStateTable)
            .where(KnowledgePublicationStateTable.id == 1)
            .with_for_update()
        )
        publication = await self.session.get(KnowledgePublicationTable, version)
        job = await self.session.get(GitLabSyncJobTable, job_id)
        source = await self.session.get(GitLabSourceTable, source_id)
        if (
            state is None
            or publication is None
            or job is None
            or source is None
            or state.active_version != publication.previous_version
            or job.worker_id != worker_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= datetime.now(UTC)
        ):
            raise RuntimeError("知识版本发布前置状态已变化")

        # Manifest、Source SHA、任务状态、通知事件和正式版本指针在同一个
        # PostgreSQL 事务中提交。ES/Milvus 候选数据已在此之前完成并通过验证。
        await self._apply_manifests(source_id, manifests)

        now = datetime.now(UTC)
        publication.status = "published"
        publication.validation_json = validation
        publication.published_at = now
        state.active_version = version
        source.last_synced_sha = target_sha
        if not source.desired_sha:
            source.desired_sha = target_sha
        job.status = "succeeded"
        job.phase = "published"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = now
        job.document_count = len(manifests)
        job.parent_count = parent_count
        job.child_count = child_count
        job.change_counts_json = _count_changes(changes)
        self.session.add(
            KnowledgeChangeEventTable(
                publication_version=version,
                source_id=source_id,
                event_type="knowledge_published",
                affected_documents_json=changes,
            )
        )
        await self.session.commit()

    async def publish_bootstrap(
        self,
        *,
        job_id: str,
        worker_id: str,
        version: int,
        entries: list[dict],
        parent_count: int,
        child_count: int,
    ) -> None:
        state = await self.session.scalar(
            select(KnowledgePublicationStateTable)
            .where(KnowledgePublicationStateTable.id == 1)
            .with_for_update()
        )
        publication = await self.session.get(KnowledgePublicationTable, version)
        job = await self.session.get(GitLabSyncJobTable, job_id)
        now = datetime.now(UTC)
        if (
            state is None
            or publication is None
            or job is None
            or state.active_version != 0
            or publication.previous_version != 0
            or job.worker_id != worker_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise RuntimeError("联合 Bootstrap 发布前置状态已变化")

        source_ids: list[str] = []
        for entry in entries:
            source = entry["source"]
            source_ids.append(source.id)
            await self._apply_manifests(source.id, entry["manifests"])
            source.last_synced_sha = entry["target_sha"]
            if not source.desired_sha:
                source.desired_sha = entry["target_sha"]
            self.session.add(
                KnowledgeChangeEventTable(
                    publication_version=version,
                    source_id=source.id,
                    event_type="knowledge_published",
                    affected_documents_json=entry["changes"],
                )
            )

        publication.status = "published"
        publication.validation_json = {
            "source_ids": source_ids,
            "source_count": len(source_ids),
            "es_record_count": parent_count + child_count,
            "milvus_child_count": child_count,
        }
        publication.published_at = now
        state.active_version = version
        job.status = "succeeded"
        job.phase = "published"
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = now
        job.document_count = sum(len(entry["manifests"]) for entry in entries)
        job.parent_count = parent_count
        job.child_count = child_count
        combined_changes = [
            change for entry in entries for change in entry["changes"]
        ]
        job.change_counts_json = _count_changes(combined_changes)
        await self.session.commit()

    async def _apply_manifests(
        self,
        source_id: str,
        manifests: list[dict],
    ) -> None:
        existing = {
            row.doc_id: row
            for row in await self.list_documents(source_id)
        }
        incoming_ids = {str(item["doc_id"]) for item in manifests}
        for doc_id, row in existing.items():
            if doc_id not in incoming_ids:
                row.status = "deleted"
        manifest_fields = {
            "source_id",
            "repository_path",
            "blob_id",
            "source_revision",
            "content_hash",
            "acl_hash",
            "parser_version",
            "chunk_strategy_version",
            "chunk_config_fingerprint",
            "document_type",
            "acl_json",
        }
        for item in manifests:
            row = await self.session.get(GitLabDocumentTable, item["doc_id"])
            values = {
                key: value for key, value in item.items() if key in manifest_fields
            }
            if row is None:
                self.session.add(
                    GitLabDocumentTable(doc_id=item["doc_id"], **values)
                )
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.status = "active"

    async def get_active_version(self) -> int:
        version = await self.session.scalar(
            select(KnowledgePublicationStateTable.active_version).where(
                KnowledgePublicationStateTable.id == 1
            )
        )
        return int(version or 0)

    async def get_publication_status(self) -> tuple[int, bool, int | None]:
        active = await self.get_active_version()
        syncing = bool(
            await self.session.scalar(
                select(func.count())
                .select_from(GitLabSyncJobTable)
                .where(GitLabSyncJobTable.status.in_(["running", "publishing"]))
            )
        )
        latest = await self.session.scalar(
            select(func.max(KnowledgePublicationTable.version))
        )
        return active, syncing, int(latest) if latest is not None else None

    async def list_change_events(
        self,
        *,
        after_id: int,
        limit: int,
    ) -> list[KnowledgeChangeEventTable]:
        rows = await self.session.scalars(
            select(KnowledgeChangeEventTable)
            .where(KnowledgeChangeEventTable.id > after_id)
            .order_by(KnowledgeChangeEventTable.id)
            .limit(limit)
        )
        return list(rows.all())

    async def changed_doc_ids_after_version(self, version: int) -> set[str]:
        rows = await self.session.scalars(
            select(KnowledgeChangeEventTable).where(
                KnowledgeChangeEventTable.publication_version > version
            )
        )
        return {
            str(item["doc_id"])
            for row in rows.all()
            for item in row.affected_documents_json
            if item.get("doc_id")
        }

    async def get_change_request(
        self,
        task_plan_id: str,
        source_id: str,
    ) -> GitLabChangeRequestTable | None:
        return await self.session.scalar(
            select(GitLabChangeRequestTable).where(
                GitLabChangeRequestTable.task_plan_id == task_plan_id,
                GitLabChangeRequestTable.source_id == source_id,
            )
        )

    async def list_change_requests(
        self,
        *,
        source_id: str,
        status: str | None = None,
    ) -> list[GitLabChangeRequestTable]:
        stmt = select(GitLabChangeRequestTable).where(
            GitLabChangeRequestTable.source_id == source_id
        )
        if status:
            stmt = stmt.where(GitLabChangeRequestTable.status == status)
        rows = await self.session.scalars(
            stmt.order_by(GitLabChangeRequestTable.created_at)
        )
        return list(rows.all())

    async def save_change_request(
        self,
        row: GitLabChangeRequestTable,
    ) -> GitLabChangeRequestTable:
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row


def _count_changes(changes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for change in changes:
        key = str(change.get("change_type") or "modified")
        counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = ["DeliveryResult", "GitLabRepository"]
