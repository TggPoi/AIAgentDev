import hashlib
from pathlib import Path
from typing import Any

from fast_app.domain.knowledge_models import DocumentType


def normalize_source_path(source_path: str) -> str:
    return Path(source_path).as_posix()


def build_doc_id(source_path: str) -> str:
    normalized = normalize_source_path(source_path)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def build_chunk_id(
    doc_id: str,
    section_path: list[str],
    chunk_index: int,
) -> str:
    raw = "|".join([doc_id, *section_path, str(chunk_index)])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


def build_document_metadata(
    source_path: str,
    document_type: DocumentType,
) -> dict[str, Any]:
    normalized = normalize_source_path(source_path)
    path = Path(normalized)

    return {
        "doc_id": build_doc_id(normalized),
        "source_path": normalized,
        "document_type": document_type,
        "file_name": path.name,
        "file_extension": path.suffix,
    }


def build_chunk_metadata(
    document_metadata: dict[str, Any],
    chunk_id: str,
    title: str,
    section_path: list[str],
    heading_level: int,
    section_index: int,
    chunk_index: int,
) -> dict[str, Any]:
    return {
        **document_metadata,
        "chunk_id": chunk_id,
        "title": title,
        "section_path": section_path,
        "heading_level": heading_level,
        "section_index": section_index,
        "chunk_index": chunk_index,
    }
