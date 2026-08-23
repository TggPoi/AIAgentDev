from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from fast_app.core.config import Settings
from fast_app.domain.knowledge_permissions import (
    DocumentAccessSource,
    RetrievalPermissionScope,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.ingestion.processing.document_loaders import (
    ExcelDocumentLoader,
    PowerPointDocumentLoader,
)
from fast_app.ingestion.processing.pdf_processing import PdfDocumentLoader
from fast_app.ingestion.processing.word_processing import WordDocumentLoader
from fast_app.ingestion.validation.document_validation import (
    KnowledgeDocumentValidationLimits,
    validate_knowledge_document_package,
)
from fast_app.integrations.gitlab.document_content_gateway import (
    GitLabDocumentContentGateway,
)
from fast_app.schemas.knowledge_document_schema import (
    KnowledgeDocumentContentResponse,
    KnowledgeDocumentDetail,
    KnowledgeDocumentItem,
    KnowledgeDocumentListResponse,
)
from fast_app.services.exceptions import (
    AuthenticationError,
    ExternalServiceError,
    KnowledgeDocumentContentTooLargeError,
    KnowledgeDocumentContentUnavailableError,
    KnowledgeDocumentCursorInvalidError,
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentPreviewFailedError,
    KnowledgeDocumentPreviewUnsupportedError,
    KnowledgeDocumentSourceUnavailableError,
)
from fast_app.services.knowledge.document_access_policy import DocumentAccessPolicy
from fast_app.services.knowledge.knowledge_document_read_repository import (
    KnowledgeDocumentReadRepository,
    KnowledgeDocumentRecord,
)


PREVIEW_MAX_CHARACTERS = 200_000
MEDIA_TYPES = {
    "markdown": "text/markdown",
    "text": "text/plain",
    "pdf": "application/pdf",
    "powerpoint": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class KnowledgeDocumentDownload:
    content: bytes
    file_name: str
    media_type: str
    source_revision: str


class KnowledgeDocumentReadService:
    """把 SQL ACL、单文档裁决、固定 revision 读取和安全预览封装成一个边界。"""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: KnowledgeDocumentReadRepository,
        access_policy: DocumentAccessPolicy,
        content_gateway: GitLabDocumentContentGateway,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._access_policy = access_policy
        self._content_gateway = content_gateway

    async def list_documents(
        self,
        user: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
        query: str | None,
        department_code: str | None,
        document_type: str | None,
    ) -> KnowledgeDocumentListResponse:
        self._require_authenticated(user)
        scope = await self._access_policy.build_retrieval_scope(user)
        cursor_updated_at, cursor_doc_id = _decode_cursor(cursor)
        rows, has_more = await self._repository.list_documents(
            scope=scope,
            limit=limit,
            query=_normalize_optional(query),
            department_code=_normalize_optional(department_code),
            document_type=document_type,
            cursor_updated_at=cursor_updated_at,
            cursor_doc_id=cursor_doc_id,
        )
        items = [self._to_item(row, scope) for row in rows]
        return KnowledgeDocumentListResponse(
            items=items,
            next_cursor=(
                _encode_cursor(
                    rows[-1].document.updated_at,
                    rows[-1].document.doc_id,
                )
                if has_more and rows
                else None
            ),
        )

    async def get_detail(
        self,
        user: CurrentUserContext,
        doc_id: str,
    ) -> KnowledgeDocumentDetail:
        record, access_source = await self._get_authorized_record(user, doc_id)
        item = _build_item(record, access_source)
        visibility, _ = _acl_values(record)
        return KnowledgeDocumentDetail(
            **item.model_dump(),
            source_id=record.source.id,
            source_project_path=record.source.project_path,
            visibility=visibility,
        )

    async def get_content(
        self,
        user: CurrentUserContext,
        doc_id: str,
    ) -> KnowledgeDocumentContentResponse:
        record, _ = await self._get_authorized_record(user, doc_id)
        raw = await self._load_source_bytes(record)
        try:
            render_mode, content, warnings = await asyncio.to_thread(
                _extract_text_preview,
                record,
                raw,
                self._settings,
            )
        except KnowledgeDocumentPreviewUnsupportedError:
            raise
        except (UnicodeDecodeError, OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeDocumentPreviewFailedError(
                "文档源文件无法解析为安全文本预览"
            ) from exc
        truncated = len(content) > PREVIEW_MAX_CHARACTERS
        if truncated:
            content = content[:PREVIEW_MAX_CHARACTERS]
            warnings = [*warnings, "preview_truncated"]
        return KnowledgeDocumentContentResponse(
            doc_id=record.document.doc_id,
            source_revision=record.document.source_revision,
            document_type=record.document.document_type,
            render_mode=render_mode,
            content=content,
            truncated=truncated,
            warnings=sorted(set(warnings)),
        )

    async def get_download(
        self,
        user: CurrentUserContext,
        doc_id: str,
    ) -> KnowledgeDocumentDownload:
        record, _ = await self._get_authorized_record(user, doc_id)
        return KnowledgeDocumentDownload(
            content=await self._load_source_bytes(record),
            file_name=_safe_file_name(record),
            media_type=MEDIA_TYPES.get(
                record.document.document_type,
                "application/octet-stream",
            ),
            source_revision=record.document.source_revision,
        )

    async def _get_authorized_record(
        self,
        user: CurrentUserContext,
        doc_id: str,
    ) -> tuple[KnowledgeDocumentRecord, DocumentAccessSource]:
        self._require_authenticated(user)
        record = await self._repository.get_document(doc_id)
        if record is None:
            raise KnowledgeDocumentNotFoundError("知识文档不存在")
        visibility, allowed_users = _acl_values(record)
        access_source = await self._access_policy.resolve_access_source(
            user,
            document_id=record.document.doc_id,
            document_department_code=record.source.department_code,
            visibility=visibility,
            allowed_user_ids=allowed_users,
        )
        if access_source is None:
            raise KnowledgeDocumentNotFoundError("知识文档不存在")
        return record, access_source

    async def _load_source_bytes(self, record: KnowledgeDocumentRecord) -> bytes:
        try:
            raw = await self._content_gateway.fetch(
                source=record.source,
                document=record.document,
            )
        except ExternalServiceError as exc:
            raise KnowledgeDocumentSourceUnavailableError(
                "GitLab 文档源当前不可用，请稍后重试"
            ) from exc
        if raw is None:
            raise KnowledgeDocumentContentUnavailableError(
                "固定 revision 中不存在 manifest 指向的文档"
            )
        if len(raw) > self._settings.gitlab_source_file_max_bytes:
            raise KnowledgeDocumentContentTooLargeError(
                "文档超过服务端允许的读取大小"
            )
        if record.document.blob_id and _git_blob_id(raw) != record.document.blob_id:
            raise KnowledgeDocumentContentUnavailableError(
                "GitLab 返回内容与 manifest blob 不一致"
            )
        return raw

    def _to_item(
        self,
        record: KnowledgeDocumentRecord,
        scope: RetrievalPermissionScope,
    ) -> KnowledgeDocumentItem:
        visibility, allowed_users = _acl_values(record)
        access_source = self._access_policy.resolve_access_source_from_scope(
            scope,
            document_id=record.document.doc_id,
            document_department_code=record.source.department_code,
            visibility=visibility,
            allowed_user_ids=allowed_users,
        )
        if access_source is None:
            raise RuntimeError("SQL ACL 返回了共享策略判定为不可见的文档")
        return _build_item(record, access_source)

    @staticmethod
    def _require_authenticated(user: CurrentUserContext) -> None:
        if not user.is_authenticated:
            raise AuthenticationError("知识文档读取只允许已认证用户")


def _build_item(
    record: KnowledgeDocumentRecord,
    access_source: DocumentAccessSource,
) -> KnowledgeDocumentItem:
    file_name = _safe_file_name(record)
    return KnowledgeDocumentItem(
        doc_id=record.document.doc_id,
        title=PurePosixPath(file_name).stem or file_name,
        file_name=file_name,
        repository_path=record.document.repository_path,
        department_code=record.source.department_code,
        document_type=record.document.document_type,
        source_revision=record.document.source_revision,
        updated_at=record.document.updated_at,
        access_source=access_source,
    )


def _acl_values(record: KnowledgeDocumentRecord) -> tuple[str, list[str]]:
    acl = record.document.acl_json if isinstance(record.document.acl_json, dict) else {}
    visibility = str(acl.get("visibility") or record.source.default_visibility)
    raw_allowed_users = acl.get("allowed_users") or []
    allowed_users = (
        [str(item) for item in raw_allowed_users]
        if isinstance(raw_allowed_users, list)
        else []
    )
    return visibility, allowed_users


def _safe_file_name(record: KnowledgeDocumentRecord) -> str:
    value = PurePosixPath(record.document.repository_path).name
    cleaned = "".join(
        character
        for character in value
        if character not in {'"', "\\", "/", "\r", "\n"}
        and ord(character) >= 32
    ).strip(" .")
    if cleaned:
        return cleaned[:255]
    suffix = PurePosixPath(value).suffix.lower()
    return f"{record.document.doc_id}{suffix}"[:255]


def _extract_text_preview(
    record: KnowledgeDocumentRecord,
    raw: bytes,
    settings: Settings,
) -> tuple[str, str, list[str]]:
    document_type = record.document.document_type
    if document_type in {"markdown", "text"}:
        return (
            "markdown" if document_type == "markdown" else "plain_text",
            raw.decode("utf-8-sig"),
            [],
        )
    suffixes = {
        "pdf": ".pdf",
        "powerpoint": ".pptx",
        "spreadsheet": ".xlsx",
        "word": ".docx",
    }
    suffix = suffixes.get(document_type)
    if suffix is None:
        raise KnowledgeDocumentPreviewUnsupportedError(
            "当前文档类型不支持安全文本预览"
        )
    with TemporaryDirectory(prefix="knowledge-preview-") as temp_dir:
        path = Path(temp_dir) / f"source{suffix}"
        path.write_bytes(raw)
        validate_knowledge_document_package(
            path,
            document_type=document_type,
            limits=KnowledgeDocumentValidationLimits(
                max_file_bytes=settings.gitlab_source_file_max_bytes,
                max_pdf_pages=settings.pdf_max_pages,
            ),
        )
        if document_type == "powerpoint":
            loaded = PowerPointDocumentLoader(
                max_image_bytes=settings.vision_max_image_bytes,
                max_image_pixels=settings.vision_max_image_pixels,
            ).load_file(path, source_path=record.document.repository_path)
            return (
                "extracted_text",
                loaded.content,
                list(loaded.metadata.get("extraction_warnings") or []),
            )
        if document_type == "spreadsheet":
            loaded = ExcelDocumentLoader().load_file(
                path,
                source_path=record.document.repository_path,
            )
            return (
                "extracted_text",
                loaded.content,
                list(loaded.metadata.get("extraction_warnings") or []),
            )
        if document_type == "word":
            loaded = WordDocumentLoader(
                max_image_bytes=settings.vision_max_image_bytes,
                max_image_pixels=settings.vision_max_image_pixels,
            ).load_structured_file(
                path,
                source_path=record.document.repository_path,
            )
            content = "\n\n".join(block.text for block in loaded.blocks if block.text)
            warnings = [
                *loaded.warnings,
                *(loaded.metadata.get("extraction_warnings") or []),
            ]
            return "extracted_text", content, warnings
        loaded = PdfDocumentLoader(settings).load_structured_file(
            path,
            source_path=record.document.repository_path,
        )
        content = "\n\n".join(
            f"Page {page.page_number}\n{page.native_text}".strip()
            for page in loaded.pages
            if page.native_text
        )
        warnings = [
            *loaded.warnings,
            *(loaded.metadata.get("extraction_warnings") or []),
            *(warning for page in loaded.pages for warning in page.warnings),
        ]
        if not content:
            warnings.append("pdf_text_content_unavailable")
        return "extracted_text", content, warnings


def _git_blob_id(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("utf-8")
    return hashlib.sha1(header + content).hexdigest()


def _normalize_optional(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _encode_cursor(updated_at: datetime, doc_id: str) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "doc_id": doc_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        doc_id = payload["doc_id"]
        if updated_at.tzinfo is None or not isinstance(doc_id, str) or not doc_id:
            raise ValueError
        return updated_at, doc_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise KnowledgeDocumentCursorInvalidError(
            "知识文档列表 cursor 无效"
        ) from exc


__all__ = [
    "KnowledgeDocumentDownload",
    "KnowledgeDocumentReadService",
    "PREVIEW_MAX_CHARACTERS",
]
