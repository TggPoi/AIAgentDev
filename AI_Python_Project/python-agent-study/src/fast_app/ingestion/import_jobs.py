from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.db.ingestion_tables import (
    KnowledgeDocumentTable,
    KnowledgeExcelImportProfileTable,
    KnowledgeIngestionJobTable,
)
from fast_app.services.exceptions import AppServiceError


ACTIVE_JOB_STATUSES = {"pending", "running", "awaiting_configuration"}
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 60
MAX_ATTEMPTS = 3
STAGING_DIR = Path("runtime/knowledge-imports")


class ImportJobConflictError(AppServiceError):
    """目标文件已存在或同一路径已有活动导入任务。"""

    error_code = "KNOWLEDGE_IMPORT_CONFLICT"
    status_code = 409


class ImportJobNotFoundError(AppServiceError):
    """任务不存在，或当前用户无权感知该任务。"""

    error_code = "KNOWLEDGE_IMPORT_JOB_NOT_FOUND"
    status_code = 404


class ImportJobValidationError(AppServiceError):
    """上传文件名、部门或 OOXML 内容不符合导入约束。"""

    error_code = "KNOWLEDGE_IMPORT_INVALID_FILE"
    status_code = 422

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        """允许底层 OOXML 校验错误码透传到统一 API 错误响应。"""

        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class ImportFileTooLargeError(AppServiceError):
    """分块读取发现文件实际大小超过上传文件上限。"""

    error_code = "KNOWLEDGE_IMPORT_FILE_TOO_LARGE"
    status_code = 413


class KnowledgeDocumentVersionConflictError(AppServiceError):
    """客户端基于的文档版本已经不是数据库中的活动版本。"""

    error_code = "KNOWLEDGE_DOCUMENT_VERSION_CONFLICT"
    status_code = 409


class ExcelPreviewChangedError(AppServiceError):
    """用户确认的预览并非当前任务最近一次生成的预览。"""

    error_code = "EXCEL_PREVIEW_CHANGED"
    status_code = 409


@dataclass(frozen=True)
class ClaimedImportJob:
    """一次任务领取结果，以及是否因崩溃恢复耗尽重试次数。"""

    row: KnowledgeIngestionJobTable
    recovery_exhausted: bool = False


class KnowledgeImportJobRepository:
    """封装导入任务的持久化、并发领取和租约条件更新。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定一个由调用方管理事务生命周期的异步数据库会话。"""

        self._session = session

    async def create(
        self,
        *,
        job_id: str,
        user_id: str,
        department_code: str,
        original_filename: str,
        target_path: str,
        staged_path: str,
        sha256: str,
        document_type: str,
        file_size: int,
        request_id: str | None,
        trace_id: str | None,
        doc_id: str,
        operation: str = "create",
        base_sha256: str | None = None,
        excel_profile_id: str | None = None,
        excel_profile_snapshot: dict | None = None,
    ) -> KnowledgeIngestionJobTable:
        """创建任务，并在 create 场景同时登记尚未激活的文档。"""

        row = KnowledgeIngestionJobTable(
            id=job_id,
            operation=operation,
            doc_id=doc_id,
            user_id=user_id,
            department_code=department_code,
            original_filename=original_filename,
            target_path=target_path,
            staged_path=staged_path,
            sha256=sha256,
            base_sha256=base_sha256,
            new_sha256=sha256,
            document_type=document_type,
            file_size=file_size,
            status="pending",
            phase="queued",
            max_attempts=MAX_ATTEMPTS,
            request_id=request_id,
            trace_id=trace_id,
            excel_profile_id=excel_profile_id,
            excel_profile_snapshot_json=excel_profile_snapshot,
        )
        if operation == "create":
            self._session.add(
                KnowledgeDocumentTable(
                    doc_id=doc_id,
                    source_path=target_path,
                    department_code=department_code,
                    document_type=document_type,
                    status="pending",
                    version=0,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ImportJobConflictError("同名文档已有活动导入任务") from exc
        await self._session.refresh(row)
        return row

    async def get(self, job_id: str) -> KnowledgeIngestionJobTable | None:
        """按任务主键读取任务，不在仓储层处理用户可见性。"""

        return await self._session.get(KnowledgeIngestionJobTable, job_id)

    async def get_document(self, doc_id: str) -> KnowledgeDocumentTable | None:
        """读取服务端文档注册记录。"""

        return await self._session.get(KnowledgeDocumentTable, doc_id)

    async def get_active_excel_profile(
        self, doc_id: str
    ) -> KnowledgeExcelImportProfileTable | None:
        """通过文档记录上的指针读取当前生效 Excel Profile。"""

        document = await self.get_document(doc_id)
        if document is None or document.active_excel_profile_id is None:
            return None
        return await self._session.get(
            KnowledgeExcelImportProfileTable, document.active_excel_profile_id
        )

    async def find_active_target(self, target_path: str) -> KnowledgeIngestionJobTable | None:
        """查询同一目标路径上尚未结束的任务，用于提前返回可读冲突。"""

        stmt = select(KnowledgeIngestionJobTable).where(
            KnowledgeIngestionJobTable.target_path == target_path,
            KnowledgeIngestionJobTable.status.in_(ACTIVE_JOB_STATUSES),
        )
        return await self._session.scalar(stmt)

    async def list_for_user(
        self,
        *,
        user_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[KnowledgeIngestionJobTable]:
        """按用户和状态筛选任务，并按创建时间倒序返回有限结果。"""

        stmt: Select[tuple[KnowledgeIngestionJobTable]] = select(
            KnowledgeIngestionJobTable
        )
        if user_id is not None:
            stmt = stmt.where(KnowledgeIngestionJobTable.user_id == user_id)
        if status is not None:
            stmt = stmt.where(KnowledgeIngestionJobTable.status == status)
        stmt = stmt.order_by(KnowledgeIngestionJobTable.created_at.desc()).limit(limit)
        return list((await self._session.scalars(stmt)).all())

    async def mark_awaiting_configuration(
        self,
        job_id: str,
        worker_id: str,
        *,
        preview: dict,
    ) -> bool:
        """保存 Excel 预览并释放租约，等待显式 Profile 确认。"""

        now = datetime.now(UTC)
        result = await self._session.execute(
            update(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .values(
                status="awaiting_configuration",
                phase="profiling",
                preview_json=preview,
                # 等待用户配置不是执行失败，不占用自动重试额度。
                attempt_count=KnowledgeIngestionJobTable.attempt_count - 1,
                worker_id=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def confirm_excel_profile(
        self,
        job_id: str,
        *,
        user_id: str,
        preview_fingerprint: str,
        mode: str,
        profile_name: str,
        sheets: list[dict],
    ) -> KnowledgeExcelImportProfileTable:
        """创建 draft Profile，把等待配置的任务重新放回 pending 队列。"""

        job = await self._session.scalar(
            select(KnowledgeIngestionJobTable)
            .where(KnowledgeIngestionJobTable.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "awaiting_configuration":
            raise ImportJobConflictError("任务当前不等待 Excel 配置")
        current_fingerprint = (job.preview_json or {}).get("preview_fingerprint")
        if current_fingerprint != preview_fingerprint:
            raise ExcelPreviewChangedError("Excel 预览已经变化，请刷新后重新确认")

        latest_version = await self._session.scalar(
            select(func.max(KnowledgeExcelImportProfileTable.version)).where(
                KnowledgeExcelImportProfileTable.doc_id == job.doc_id
            )
        )
        profile = KnowledgeExcelImportProfileTable(
            id=f"excel_profile_{uuid4().hex}",
            doc_id=str(job.doc_id),
            version=int(latest_version or 0) + 1,
            status="draft",
            mode=mode,
            profile_name=profile_name,
            sheet_configs_json=sheets,
            preview_fingerprint=preview_fingerprint,
            created_by=user_id,
        )
        snapshot = {"mode": mode, "profile_name": profile_name, "sheets": sheets}
        self._session.add(profile)
        job.excel_profile_id = profile.id
        job.excel_profile_snapshot_json = snapshot
        job.status = "pending"
        job.phase = "queued"
        job.error_code = None
        job.error_message = None
        job.updated_at = datetime.now(UTC)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ImportJobConflictError("Excel Profile 版本发生并发冲突") from exc
        await self._session.refresh(profile)
        return profile

    async def claim_next(self, worker_id: str) -> ClaimedImportJob | None:
        """原子领取最早的待执行任务，或回收租约已过期的运行中任务。"""

        now = datetime.now(UTC)
        # SKIP LOCKED 让多个 Worker 各自领取不同任务，不互相等待同一行锁。
        stmt = (
            select(KnowledgeIngestionJobTable)
            .where(
                or_(
                    and_(
                        KnowledgeIngestionJobTable.status == "pending",
                        KnowledgeIngestionJobTable.attempt_count
                        < KnowledgeIngestionJobTable.max_attempts,
                    ),
                    and_(
                        KnowledgeIngestionJobTable.status == "running",
                        KnowledgeIngestionJobTable.lease_expires_at < now,
                    ),
                )
            )
            .order_by(KnowledgeIngestionJobTable.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        row = await self._session.scalar(stmt)
        if row is None:
            return None

        recovery_exhausted = (
            row.status == "running" and row.attempt_count >= row.max_attempts
        )
        # 已耗尽次数的崩溃任务仍需被领取一次，以便清理产物并落为 failed；
        # 这次清理领取不再增加 attempt_count。
        if not recovery_exhausted:
            row.attempt_count += 1
        row.status = "running"
        row.worker_id = worker_id
        row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        row.started_at = row.started_at or now
        row.updated_at = now
        await self._session.commit()
        return ClaimedImportJob(row=row, recovery_exhausted=recovery_exhausted)

    async def renew_lease(self, job_id: str, worker_id: str) -> bool:
        """仅由当前所有者续租；返回 False 表示任务已被回收或终止。"""

        now = datetime.now(UTC)
        result = await self._session.execute(
            update(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .values(
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                updated_at=now,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def set_phase(self, job_id: str, worker_id: str, phase: str) -> bool:
        """在仍持有任务时更新阶段，并顺带把租约向后延长五分钟。"""

        now = datetime.now(UTC)
        result = await self._session.execute(
            update(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .values(
                phase=phase,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                updated_at=now,
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_succeeded(
        self,
        job_id: str,
        worker_id: str,
        *,
        document_count: int,
        chunk_count: int,
        warnings: list[dict[str, str]],
        diff_counts: dict[str, int] | None = None,
    ) -> bool:
        """在同一事务中提交任务、文档版本以及 draft Profile。"""

        now = datetime.now(UTC)
        job = await self._session.scalar(
            select(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .with_for_update()
        )
        if job is None:
            await self._session.rollback()
            return False
        document = await self._session.scalar(
            select(KnowledgeDocumentTable)
            .where(KnowledgeDocumentTable.doc_id == job.doc_id)
            .with_for_update()
        )
        if document is None:
            await self._session.rollback()
            return False
        if job.operation == "update" and document.current_sha256 != job.base_sha256:
            # 文件发布前虽已检查过一次，这个行锁内检查关闭最终提交竞态窗口。
            await self._session.rollback()
            return False

        job.status = "succeeded"
        job.phase = "completed"
        job.document_count = document_count
        job.chunk_count = chunk_count
        job.warnings_json = warnings
        job.diff_counts_json = diff_counts or {}
        job.error_code = None
        job.error_message = None
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = now
        job.updated_at = now

        document.current_sha256 = job.new_sha256 or job.sha256
        document.version += 1
        document.status = "active"
        document.updated_by = job.user_id
        document.updated_at = now
        if job.excel_profile_id is not None:
            await self._session.execute(
                update(KnowledgeExcelImportProfileTable)
                .where(
                    KnowledgeExcelImportProfileTable.doc_id == job.doc_id,
                    KnowledgeExcelImportProfileTable.status == "active",
                )
                .values(status="superseded")
            )
            profile = await self._session.get(
                KnowledgeExcelImportProfileTable, job.excel_profile_id
            )
            if profile is not None:
                profile.status = "active"
                profile.activated_at = now
                document.active_excel_profile_id = profile.id
        await self._session.commit()
        return True

    async def mark_retry(
        self,
        job_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> bool:
        """把可重试的外部故障任务放回 pending 队列。"""

        result = await self._session.execute(
            update(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .values(
                status="pending",
                phase="queued",
                error_code=error_code,
                error_message=error_message,
                worker_id=None,
                lease_expires_at=None,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.commit()
        return bool(result.rowcount)

    async def mark_failed(
        self,
        job_id: str,
        worker_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> bool:
        """把不可恢复或耗尽重试次数的任务标记为 failed。"""

        now = datetime.now(UTC)
        job = await self._session.scalar(
            select(KnowledgeIngestionJobTable)
            .where(
                KnowledgeIngestionJobTable.id == job_id,
                KnowledgeIngestionJobTable.worker_id == worker_id,
                KnowledgeIngestionJobTable.status == "running",
            )
            .with_for_update()
        )
        if job is None:
            await self._session.rollback()
            return False
        job.status = "failed"
        job.error_code = error_code
        job.error_message = error_message
        job.worker_id = None
        job.lease_expires_at = None
        job.finished_at = now
        job.updated_at = now
        if job.excel_profile_id is not None:
            profile = await self._session.get(
                KnowledgeExcelImportProfileTable, job.excel_profile_id
            )
            if profile is not None and profile.status == "draft":
                await self._session.delete(profile)
        if job.operation == "create":
            document = await self._session.get(KnowledgeDocumentTable, job.doc_id)
            if document is not None and document.status == "pending":
                await self._session.delete(document)
        await self._session.commit()
        return True


def new_import_job_id() -> str:
    """生成适合作为数据库主键和 staging 文件名前缀的任务 ID。"""

    return f"import_{uuid4().hex}"


def normalize_upload_filename(filename: str | None) -> tuple[str, str]:
    """规范化上传文件名，并返回受支持扩展名对应的文档类型。"""

    if filename is None:
        raise ImportJobValidationError("上传文件缺少文件名")
    normalized = unicodedata.normalize("NFC", filename.strip())
    if not normalized or len(normalized) > 128:
        raise ImportJobValidationError("文件名不能为空且不能超过 128 个字符")
    if normalized.startswith(".") or Path(normalized).name != normalized:
        raise ImportJobValidationError("文件名不能包含路径或以点开头")
    if any(ord(char) < 32 for char in normalized) or any(
        char in normalized for char in '<>:"/\\|?*'
    ):
        raise ImportJobValidationError("文件名包含不允许的字符")

    # Windows 保留设备名即使带扩展名也不能安全地作为目标文件名。
    stem = Path(normalized).stem.rstrip(". ").upper()
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{index}"
        for prefix in ("COM", "LPT")
        for index in range(1, 10)
    }
    if stem in reserved:
        raise ImportJobValidationError("文件名使用了 Windows 保留名称")

    extension = Path(normalized).suffix.lower()
    document_types = {".pptx": "powerpoint", ".xlsx": "spreadsheet"}
    document_type = document_types.get(extension)
    if document_type is None:
        raise ImportJobValidationError("只允许上传 .pptx 或 .xlsx 文件")
    return normalized, document_type


def validate_department_code(department_code: str) -> str:
    """限制部门编码字符集，确保服务端拼接出的目录名可预测且安全。"""

    normalized = department_code.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", normalized):
        raise ImportJobValidationError("部门编码格式不合法")
    return normalized


__all__ = [
    "ClaimedImportJob",
    "HEARTBEAT_SECONDS",
    "ImportFileTooLargeError",
    "ImportJobConflictError",
    "ImportJobNotFoundError",
    "ImportJobValidationError",
    "ExcelPreviewChangedError",
    "KnowledgeDocumentVersionConflictError",
    "KnowledgeImportJobRepository",
    "STAGING_DIR",
    "new_import_job_id",
    "normalize_upload_filename",
    "validate_department_code",
]
