"""知识文档包的格式分派与安全校验。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fast_app.domain.knowledge_models import DocumentType
from fast_app.ingestion.validation.ooxml_validation import (
    OOXMLValidationError,
    validate_ooxml_package,
)


class DocumentPackageValidationError(ValueError):
    """携带稳定错误码的统一文档校验错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class KnowledgeDocumentValidationLimits:
    max_file_bytes: int = 20 * 1024 * 1024
    max_uncompressed_bytes: int = 200 * 1024 * 1024
    max_entries: int = 10_000
    max_compression_ratio: float = 100.0
    max_pdf_pages: int = 500


@dataclass(frozen=True)
class KnowledgeDocumentValidationResult:
    document_type: DocumentType
    file_size: int
    page_count: int | None = None


def validate_knowledge_document_package(
    path: str | Path,
    *,
    document_type: DocumentType,
    limits: KnowledgeDocumentValidationLimits | None = None,
) -> KnowledgeDocumentValidationResult:
    """按可信 document_type 分派校验，避免 PDF 被错误送入 OOXML。"""

    file_path = Path(path)
    selected = limits or KnowledgeDocumentValidationLimits()
    size = file_path.stat().st_size
    if size > selected.max_file_bytes:
        raise DocumentPackageValidationError("DOCUMENT_FILE_TOO_LARGE", "文档大小超过限制")
    expected_suffix = {
        "powerpoint": ".pptx",
        "spreadsheet": ".xlsx",
        "word": ".docx",
        "pdf": ".pdf",
        "markdown": ".md",
        "text": ".txt",
    }[document_type]
    if file_path.suffix.lower() != expected_suffix:
        raise DocumentPackageValidationError("DOCUMENT_TYPE_MISMATCH", "文件扩展名与文档类型不一致")
    if document_type in {"powerpoint", "spreadsheet", "word"}:
        try:
            validate_ooxml_package(
                file_path,
                max_uncompressed_bytes=selected.max_uncompressed_bytes,
                max_entries=selected.max_entries,
                max_compression_ratio=selected.max_compression_ratio,
            )
        except OOXMLValidationError as exc:
            raise DocumentPackageValidationError(exc.code, str(exc)) from exc
        return KnowledgeDocumentValidationResult(document_type, size)
    if document_type == "pdf":
        return _validate_pdf(file_path, size=size, limits=selected)
    try:
        file_path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise DocumentPackageValidationError("TEXT_NOT_UTF8", "文本文件必须使用 UTF-8") from exc
    return KnowledgeDocumentValidationResult(document_type, size)


def _validate_pdf(
    path: Path,
    *,
    size: int,
    limits: KnowledgeDocumentValidationLimits,
) -> KnowledgeDocumentValidationResult:
    if path.read_bytes()[:5] != b"%PDF-":
        raise DocumentPackageValidationError("INVALID_PDF_SIGNATURE", "文件不是有效 PDF")
    try:
        from pypdf import PdfReader

        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise DocumentPackageValidationError("PDF_ENCRYPTED", "不支持加密 PDF")
        page_count = len(reader.pages)
    except DocumentPackageValidationError:
        raise
    except Exception as exc:
        raise DocumentPackageValidationError("INVALID_PDF_DOCUMENT", "PDF 结构损坏或不受支持") from exc
    if page_count > limits.max_pdf_pages:
        raise DocumentPackageValidationError("PDF_TOO_MANY_PAGES", "PDF 页数超过限制")
    return KnowledgeDocumentValidationResult("pdf", size, page_count)


__all__ = [
    "DocumentPackageValidationError",
    "KnowledgeDocumentValidationLimits",
    "KnowledgeDocumentValidationResult",
    "validate_knowledge_document_package",
]
