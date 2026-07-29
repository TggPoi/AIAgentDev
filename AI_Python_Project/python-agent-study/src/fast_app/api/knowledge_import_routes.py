from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings, get_settings
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.db.ingestion_tables import (
    KnowledgeExcelImportProfileTable,
    KnowledgeIngestionJobTable,
)
from fast_app.dependencies.rag_dependencies import get_db_session, get_permission_service
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.ingestion.import_jobs import (
    ImportFileTooLargeError,
    ImportJobConflictError,
    ImportJobNotFoundError,
    ImportJobValidationError,
    KnowledgeDocumentVersionConflictError,
    KnowledgeImportJobRepository,
    STAGING_DIR,
    new_import_job_id,
    normalize_upload_filename,
    validate_department_code,
)
from fast_app.ingestion.processing.metadata_models import build_doc_id
from fast_app.ingestion.validation.ooxml_validation import OOXMLValidationError, validate_ooxml_package
from fast_app.services.exceptions import AuthenticationError, ToolPermissionDeniedError
from fast_app.services.auth.permission_service import PermissionService


router = APIRouter(tags=["knowledge-imports"])


class KnowledgeImportJobResponse(BaseModel):
    """前端轮询任务状态、配置要求和增量结果所需的稳定结构。"""

    job_id: str = Field(description="导入任务唯一 ID。")
    operation: str = Field(description="任务操作类型：create 或 update。")
    doc_id: str | None = Field(description="稳定文档 ID；尚未注册时可能为空。")
    status: str = Field(description="任务当前状态，例如 pending、running 或 succeeded。")
    phase: str = Field(description="Worker 当前执行阶段。")
    original_filename: str = Field(description="用户上传时的原始文件名。")
    target_path: str = Field(description="服务端生成的知识库目标路径。")
    department_code: str = Field(description="目标文档所属部门编码。")
    document_type: str = Field(description="文档类型，例如 pptx 或 xlsx。")
    file_size: int = Field(description="上传文件实际字节数。")
    base_sha256: str | None = Field(
        default=None,
        description="更新任务开始时的旧文件 SHA-256；创建任务为空。",
    )
    new_sha256: str | None = Field(
        default=None,
        description="本次上传文件的 SHA-256。",
    )
    attempt_count: int = Field(description="任务已被 Worker 尝试执行的次数。")
    max_attempts: int = Field(description="任务允许的最大尝试次数。")
    document_count: int = Field(description="本次解析产生的 LoadedDocument 数量。")
    chunk_count: int = Field(description="本次目标版本的唯一 Chunk 数量。")
    requires_configuration: bool = Field(
        description="是否需要用户确认或重新配置 Excel Profile。"
    )
    excel_preview: dict[str, Any] | None = Field(
        default=None,
        description="Excel 待确认的 Sheet、表头和候选主键预览。",
    )
    excel_profile_id: str | None = Field(
        default=None,
        description="本任务使用或等待激活的 Excel Profile ID。",
    )
    diff_counts: dict[str, int] = Field(
        default_factory=dict,
        description="增量对比计数，例如 added、changed、removed 和 embedded。",
    )
    warnings: list[dict[str, Any]] = Field(
        default_factory=list,
        description="解析、Profile 或索引过程中产生的结构化警告。",
    )
    error_code: str | None = Field(default=None, description="稳定机器可读错误码。")
    error_message: str | None = Field(default=None, description="供用户或管理员查看的错误摘要。")
    created_at: datetime = Field(description="任务创建时间。")
    updated_at: datetime = Field(description="任务最近更新时间。")
    started_at: datetime | None = Field(default=None, description="Worker 首次开始执行时间。")
    finished_at: datetime | None = Field(default=None, description="任务进入终态的时间。")
    status_url: str = Field(description="前端轮询该任务状态的 API 路径。")
    request_id: str | None = Field(default=None, description="创建或查询请求 ID。")
    trace_id: str | None = Field(default=None, description="跨组件追踪 ID。")


class KnowledgeImportJobListResponse(BaseModel):
    """导入任务列表响应。"""

    items: list[KnowledgeImportJobResponse] = Field(description="按查询条件返回的导入任务。")


class ExcelFieldProfile(BaseModel):
    """一个稳定业务字段及其当前可接受表头名称。"""

    field_id: str = Field(
        min_length=1,
        max_length=128,
        description="跨版本稳定的业务字段 ID，不使用物理列坐标。",
    )
    display_name: str = Field(
        min_length=1,
        max_length=128,
        description="Profile 和前端展示的字段名称。",
    )
    header_aliases: list[str] = Field(
        default_factory=list,
        description="允许匹配该字段的历史或替代表头文本。",
    )
    required: bool = Field(default=False, description="更新文件中是否必须匹配到该字段。")
    indexed: bool = Field(default=True, description="该字段内容是否进入检索 Chunk。")
    field_group: str | None = Field(
        default=None,
        max_length=128,
        description="宽表分组标识；为空时该记录使用默认分组。",
    )


class ExcelSheetProfile(BaseModel):
    """一个工作表的稳定身份、表头位置、主键和字段映射。"""

    sheet_key: str = Field(
        min_length=1,
        max_length=128,
        description="跨版本稳定的 Sheet 身份，不依赖当前工作表名称。",
    )
    # mixed Profile 必须逐 Sheet 声明模式；旧 Profile 省略时继承 Workbook mode。
    mode: Literal["record", "section"] | None = Field(
        default=None,
        description="该 Sheet 的处理模式；非 mixed Profile 可省略并继承顶层 mode。",
    )
    sheet_name_aliases: list[str] = Field(
        default_factory=list,
        description="用于跨版本匹配该 Sheet 的当前名称和历史别名。",
    )
    header_row: int = Field(
        default=1,
        ge=1,
        le=100_000,
        description="Record 模式业务表头所在的原始 Excel 行号。",
    )
    identity_field_ids: list[str] = Field(
        default_factory=list,
        description="Record 模式组合主键使用的稳定 field_id 列表。",
    )
    fields: list[ExcelFieldProfile] = Field(
        default_factory=list,
        description="Record 模式的稳定字段映射；Section 模式可为空。",
    )


class ExcelProfileConfirmRequest(BaseModel):
    """React 在预览后提交的 Profile 确认请求。"""

    preview_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        description="用户当前看到的 Excel 预览指纹，用于防止确认过期预览。",
    )
    mode: Literal["record", "section", "mixed"] = Field(
        description="Workbook 顶层模式；mixed 要求每个可见非空 Sheet 声明 mode。"
    )
    profile_name: str = Field(
        min_length=1,
        max_length=128,
        description="供用户识别该版本 Profile 的名称。",
    )
    sheets: list[ExcelSheetProfile] = Field(
        default_factory=list,
        description="可见非空 Sheet 的身份和处理配置。",
    )


class ExcelProfileResponse(BaseModel):
    """当前任务或文档所使用的 Excel Profile。"""

    id: str = Field(description="Excel Profile 唯一 ID。")
    doc_id: str = Field(description="该 Profile 所属的稳定文档 ID。")
    version: int = Field(description="Profile 版本号。")
    status: str = Field(description="Profile 状态：draft、active 或 superseded。")
    mode: str = Field(description="Workbook 顶层处理模式。")
    profile_name: str = Field(description="Profile 展示名称。")
    sheets: list[dict[str, Any]] = Field(description="已保存的逐 Sheet 配置快照。")
    preview_fingerprint: str = Field(description="创建该 Profile 时确认的预览指纹。")


def get_import_job_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeImportJobRepository:
    """为当前请求创建共享同一数据库会话的任务仓储。"""

    return KnowledgeImportJobRepository(session)


@router.post(
    "/knowledge-documents/import-jobs",
    response_model=KnowledgeImportJobResponse,
    status_code=202,
)
async def create_knowledge_import_job(
    file: UploadFile = File(...),
    department_code: str = Form(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
    settings: Settings = Depends(get_settings),
) -> KnowledgeImportJobResponse:
    """创建 Office 文档；路径、文档身份和 ACL 全部由服务端生成。"""

    if not user.is_authenticated:
        raise AuthenticationError("上传知识文档需要已认证用户")
    safe_filename, document_type = normalize_upload_filename(file.filename)
    department = validate_department_code(department_code)
    await _require_permission(
        user, department, PermissionCode.KNOWLEDGE_DOCUMENT_CREATE, permission_service
    )
    target_path = _safe_create_target(settings, department, safe_filename)
    if target_path.resolve().exists():
        raise ImportJobConflictError("目标文档已存在，不允许覆盖")
    target_source_path = target_path.as_posix()
    if await repository.find_active_target(target_source_path) is not None:
        raise ImportJobConflictError("同名文档已有活动导入任务")

    return await _stage_and_create_job(
        file=file,
        original_filename=safe_filename,
        target_path=target_source_path,
        department_code=department,
        document_type=document_type,
        operation="create",
        doc_id=build_doc_id(target_source_path),
        base_sha256=None,
        excel_profile=None,
        user=user,
        repository=repository,
        settings=settings,
    )


@router.post(
    "/knowledge-documents/{doc_id}/import-jobs",
    response_model=KnowledgeImportJobResponse,
    status_code=202,
)
async def update_knowledge_import_job(
    doc_id: str,
    file: UploadFile = File(...),
    expected_sha256: str = Form(..., min_length=64, max_length=64),
    reconfigure_excel_profile: bool = Form(default=False),
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
    settings: Settings = Depends(get_settings),
) -> KnowledgeImportJobResponse:
    """基于注册表中的路径和版本创建受控更新任务。"""

    if not user.is_authenticated:
        raise AuthenticationError("更新知识文档需要已认证用户")
    document = await repository.get_document(doc_id)
    if document is None or document.status != "active":
        raise ImportJobNotFoundError("知识文档不存在")
    await _require_permission(
        user,
        document.department_code,
        PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE,
        permission_service,
    )
    if any(character not in "0123456789abcdefABCDEF" for character in expected_sha256):
        raise ImportJobValidationError("expected_sha256 必须是十六进制 SHA-256")
    if expected_sha256.casefold() != (document.current_sha256 or "").casefold():
        raise KnowledgeDocumentVersionConflictError("知识文档版本已变化")
    _, uploaded_type = normalize_upload_filename(file.filename)
    if uploaded_type != document.document_type:
        raise ImportJobValidationError("更新文件类型必须与现有文档一致")
    if reconfigure_excel_profile and document.document_type != "spreadsheet":
        raise ImportJobValidationError("只有 Excel 文档可以重新配置导入 Profile")
    if await repository.find_active_target(document.source_path) is not None:
        raise ImportJobConflictError("该文档已有活动导入任务")

    # 显式重配置时让 Worker 重新生成预览并暂停；否则继续复用当前 active Profile。
    active_profile = (
        None
        if reconfigure_excel_profile
        else await repository.get_active_excel_profile(doc_id)
    )
    return await _stage_and_create_job(
        file=file,
        original_filename=Path(document.source_path).name,
        target_path=document.source_path,
        department_code=document.department_code,
        document_type=document.document_type,
        operation="update",
        doc_id=document.doc_id,
        base_sha256=document.current_sha256,
        excel_profile=active_profile,
        user=user,
        repository=repository,
        settings=settings,
    )


@router.post(
    "/knowledge-documents/import-jobs/{job_id}/excel-profile/confirm",
    response_model=ExcelProfileResponse,
)
async def confirm_excel_profile(
    job_id: str,
    request: ExcelProfileConfirmRequest,
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
) -> ExcelProfileResponse:
    """确认预览对应的 Excel Profile，并将任务重新放回执行队列。"""

    if not user.is_authenticated:
        raise AuthenticationError("确认 Excel 配置需要已认证用户")
    job = await repository.get(job_id)
    is_admin = await _is_admin(user, permission_service)
    if job is None or (job.user_id != user.user_id and not is_admin):
        raise ImportJobNotFoundError("导入任务不存在")
    if job.document_type != "spreadsheet":
        raise ImportJobValidationError("只有 Excel 任务可以确认 Excel Profile")
    permission = (
        PermissionCode.KNOWLEDGE_DOCUMENT_CREATE
        if job.operation == "create"
        else PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE
    )
    await _require_permission(user, job.department_code, permission, permission_service)
    _validate_excel_profile_request(request)
    profile = await repository.confirm_excel_profile(
        job_id,
        user_id=user.user_id,
        preview_fingerprint=request.preview_fingerprint,
        mode=request.mode,
        profile_name=request.profile_name,
        sheets=[sheet.model_dump() for sheet in request.sheets],
    )
    return _profile_response(profile)


@router.get(
    "/knowledge-documents/{doc_id}/excel-profile",
    response_model=ExcelProfileResponse,
)
async def get_excel_profile(
    doc_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
) -> ExcelProfileResponse:
    """返回文档当前生效的 Excel Profile。"""

    if not user.is_authenticated:
        raise AuthenticationError("查询 Excel 配置需要已认证用户")
    document = await repository.get_document(doc_id)
    if document is None or document.status != "active":
        raise ImportJobNotFoundError("知识文档不存在")
    await _require_permission(
        user,
        document.department_code,
        PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE,
        permission_service,
    )
    profile = await repository.get_active_excel_profile(doc_id)
    if profile is None:
        raise ImportJobNotFoundError("Excel Profile 不存在")
    return _profile_response(profile)


@router.get(
    "/knowledge-documents/import-jobs/{job_id}",
    response_model=KnowledgeImportJobResponse,
)
async def get_knowledge_import_job(
    job_id: str,
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
) -> KnowledgeImportJobResponse:
    """读取单个任务；非管理员只能查看自己创建的任务。"""

    if not user.is_authenticated:
        raise AuthenticationError("查询知识文档导入任务需要已认证用户")
    row = await repository.get(job_id)
    is_admin = await _is_admin(user, permission_service)
    if row is None or (row.user_id != user.user_id and not is_admin):
        raise ImportJobNotFoundError("导入任务不存在")
    return _to_response(row)


@router.get(
    "/knowledge-documents/import-jobs",
    response_model=KnowledgeImportJobListResponse,
)
async def list_knowledge_import_jobs(
    status: Literal[
        "pending", "running", "awaiting_configuration", "succeeded", "failed"
    ]
    | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: CurrentUserContext = Depends(get_current_user_context),
    permission_service: PermissionService = Depends(get_permission_service),
    repository: KnowledgeImportJobRepository = Depends(get_import_job_repository),
) -> KnowledgeImportJobListResponse:
    """按状态列出任务；管理员可查看全局，普通用户仅查看自己。"""

    if not user.is_authenticated:
        raise AuthenticationError("查询知识文档导入任务需要已认证用户")
    is_admin = await _is_admin(user, permission_service)
    rows = await repository.list_for_user(
        user_id=None if is_admin else user.user_id,
        status=status,
        limit=limit,
    )
    return KnowledgeImportJobListResponse(items=[_to_response(row) for row in rows])


async def _stage_and_create_job(
    *,
    file: UploadFile,
    original_filename: str,
    target_path: str,
    department_code: str,
    document_type: str,
    operation: str,
    doc_id: str,
    base_sha256: str | None,
    excel_profile: KnowledgeExcelImportProfileTable | None,
    user: CurrentUserContext,
    repository: KnowledgeImportJobRepository,
    settings: Settings,
) -> KnowledgeImportJobResponse:
    """把创建/更新共用的安全暂存、OOXML 校验和任务落库集中在一处。"""

    job_id = new_import_job_id()
    staging_dir = STAGING_DIR.resolve()
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staging_dir / f"{job_id}{Path(original_filename).suffix.lower()}"
    created = False
    try:
        file_size, sha256 = await _copy_upload_to_staging(
            file, staged_path, max_bytes=settings.max_upload_file_bytes
        )
        try:
            await asyncio.to_thread(validate_ooxml_package, staged_path)
        except OOXMLValidationError as exc:
            raise ImportJobValidationError(str(exc), error_code=exc.code) from exc
        snapshot = None
        profile_id = None
        if excel_profile is not None:
            profile_id = excel_profile.id
            snapshot = {
                "mode": excel_profile.mode,
                "profile_name": excel_profile.profile_name,
                "sheets": list(excel_profile.sheet_configs_json),
            }
        row = await repository.create(
            job_id=job_id,
            user_id=user.user_id,
            department_code=department_code,
            original_filename=original_filename,
            target_path=target_path,
            staged_path=str(staged_path),
            sha256=sha256,
            document_type=document_type,
            file_size=file_size,
            request_id=get_request_id(),
            trace_id=get_trace_id(),
            doc_id=doc_id,
            operation=operation,
            base_sha256=base_sha256,
            excel_profile_id=profile_id,
            excel_profile_snapshot=snapshot,
        )
        created = True
        return _to_response(row)
    finally:
        await file.close()
        if not created:
            staged_path.unlink(missing_ok=True)


def _safe_create_target(settings: Settings, department: str, filename: str) -> Path:
    """构造并验证创建目标一定位于知识库根目录。"""

    root = Path(settings.knowledge_base_dir).resolve()
    target = Path(settings.knowledge_base_dir) / department / filename
    if not target.resolve().is_relative_to(root):
        raise ImportJobValidationError("目标文档路径超出知识库目录")
    return target


def _validate_excel_profile_request(request: ExcelProfileConfirmRequest) -> None:
    """在入库前拒绝重复机器身份和引用不存在字段的主键配置。"""

    if request.mode in {"record", "mixed"} and not request.sheets:
        raise ImportJobValidationError("Record 或 Mixed 模式必须配置工作表")
    sheet_keys = [sheet.sheet_key for sheet in request.sheets]
    if len(sheet_keys) != len(set(sheet_keys)):
        raise ImportJobValidationError("Excel Profile 的 sheet_key 不能重复")
    for sheet in request.sheets:
        if request.mode == "mixed" and sheet.mode is None:
            raise ImportJobValidationError(
                f"Mixed Profile 的工作表 {sheet.sheet_key} 必须声明 mode"
            )
        if request.mode != "mixed" and sheet.mode not in {None, request.mode}:
            raise ImportJobValidationError(
                f"工作表 {sheet.sheet_key} 的 mode 与 Workbook mode 不一致"
            )
        effective_mode = sheet.mode or request.mode
        if effective_mode == "section":
            continue
        field_ids = [field.field_id for field in sheet.fields]
        if not field_ids or len(field_ids) != len(set(field_ids)):
            raise ImportJobValidationError(
                f"工作表 {sheet.sheet_key} 的 field_id 不能为空或重复"
            )
        if not sheet.identity_field_ids or not set(
            sheet.identity_field_ids
        ).issubset(field_ids):
            raise ImportJobValidationError(
                f"工作表 {sheet.sheet_key} 的主键字段不存在"
            )


async def _require_permission(
    user: CurrentUserContext,
    department_code: str,
    permission: PermissionCode,
    permission_service: PermissionService,
) -> None:
    """要求用户在目标部门拥有指定文档权限。"""

    effective = await permission_service.get_effective_permissions(user.user_id)
    if effective.has_global_role(RoleCode.SYSTEM_ADMIN):
        return
    scope = effective.scope_for_department(department_code)
    if scope is None or permission not in scope.permission_codes:
        raise ToolPermissionDeniedError("当前用户没有目标部门的文档操作权限")


async def _is_admin(
    user: CurrentUserContext, permission_service: PermissionService
) -> bool:
    """同时兼容用户上下文角色和权限系统中的全局管理员角色。"""

    effective = await permission_service.get_effective_permissions(user.user_id)
    return effective.has_global_role(RoleCode.SYSTEM_ADMIN)


async def _copy_upload_to_staging(
    upload: UploadFile, target: Path, *, max_bytes: int
) -> tuple[int, str]:
    """分块复制上传文件并按实际字节执行上限和 SHA-256 计算。"""

    total = 0
    digest = hashlib.sha256()
    try:
        with target.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ImportFileTooLargeError(
                        f"上传文件超过 {max_bytes} 字节限制"
                    )
                output.write(chunk)
                digest.update(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


def _to_response(row: KnowledgeIngestionJobTable) -> KnowledgeImportJobResponse:
    """转换任务记录，不暴露 staging 路径、Worker 和租约。"""

    return KnowledgeImportJobResponse(
        job_id=row.id,
        operation=getattr(row, "operation", None) or "create",
        doc_id=getattr(row, "doc_id", None) or build_doc_id(row.target_path),
        status=row.status,
        phase=row.phase,
        original_filename=row.original_filename,
        target_path=row.target_path,
        department_code=row.department_code,
        document_type=row.document_type,
        file_size=row.file_size,
        base_sha256=getattr(row, "base_sha256", None),
        new_sha256=getattr(row, "new_sha256", None) or row.sha256,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        document_count=row.document_count,
        chunk_count=row.chunk_count,
        requires_configuration=row.status == "awaiting_configuration",
        excel_preview=getattr(row, "preview_json", None),
        excel_profile_id=getattr(row, "excel_profile_id", None),
        diff_counts=dict(getattr(row, "diff_counts_json", None) or {}),
        warnings=list(row.warnings_json or []),
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status_url=f"/knowledge-documents/import-jobs/{row.id}",
        request_id=row.request_id,
        trace_id=row.trace_id,
    )


def _profile_response(
    profile: KnowledgeExcelImportProfileTable,
) -> ExcelProfileResponse:
    """把 Profile ORM 行转换为前端稳定结构。"""

    return ExcelProfileResponse(
        id=profile.id,
        doc_id=profile.doc_id,
        version=profile.version,
        status=profile.status,
        mode=profile.mode,
        profile_name=profile.profile_name,
        sheets=list(profile.sheet_configs_json),
        preview_fingerprint=profile.preview_fingerprint,
    )


__all__ = ["router"]
