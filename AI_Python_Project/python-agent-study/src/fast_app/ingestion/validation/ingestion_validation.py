from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.processing.markdown_hierarchy import (
    MARKDOWN_CHILD_RECORD_TYPE,
    MarkdownParentChunk,
)


IssueLevel = Literal["error", "warning"]

REQUIRED_METADATA_KEYS = [
    "doc_id",
    "chunk_id",
    "title",
    "source_path",
    "section_path",
    "document_type",
    "file_name",
    "file_extension",
    "heading_level",
    "section_index",
    "chunk_index",
]

ALLOWED_DOCUMENT_TYPES = {"markdown", "text", "pdf", "powerpoint", "spreadsheet"}


@dataclass(frozen=True)
class IngestionValidationIssue:
    level: IssueLevel
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionValidationReport:
    document_count: int
    chunk_count: int
    doc_id_count: int
    source_path_count: int
    min_chunk_chars: int
    max_chunk_chars: int
    parent_count: int
    orphan_child_count: int
    parent_without_child_count: int
    max_parent_tokens: int
    max_child_tokens: int
    issues: list[IngestionValidationIssue]

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")

    @property
    def passed(self) -> bool:
        return self.error_count == 0


def validate_ingestion_result(
    documents: list[LoadedDocument],
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk] | None = None,
) -> IngestionValidationReport:
    issues: list[IngestionValidationIssue] = []
    parent_records = parents or []

    if not documents:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="no_documents",
                message="没有读取到任何文档",
            )
        )

    if not chunks:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="no_chunks",
                message="没有生成任何 chunk",
            )
        )

    source_paths = {document.source_path for document in documents}
    doc_ids: set[str] = set()

    _validate_documents(documents=documents, issues=issues)
    _validate_chunk_ids(chunks=chunks, issues=issues)
    _validate_chunks(
        chunks=chunks,
        source_paths=source_paths,
        doc_ids=doc_ids,
        issues=issues,
    )
    orphan_child_count, parent_without_child_count = _validate_parent_links(
        chunks=chunks,
        parents=parent_records,
        issues=issues,
    )

    chunk_lengths = [len(chunk.content) for chunk in chunks]

    return IngestionValidationReport(
        document_count=len(documents),
        chunk_count=len(chunks),
        doc_id_count=len(doc_ids),
        source_path_count=len(source_paths),
        min_chunk_chars=min(chunk_lengths, default=0),
        max_chunk_chars=max(chunk_lengths, default=0),
        parent_count=len(parent_records),
        orphan_child_count=orphan_child_count,
        parent_without_child_count=parent_without_child_count,
        max_parent_tokens=max(
            (int(parent.metadata.get("token_count") or 0) for parent in parent_records),
            default=0,
        ),
        max_child_tokens=max(
            (int(chunk.metadata.get("token_count") or 0) for chunk in chunks),
            default=0,
        ),
        issues=issues,
    )


def _validate_parent_links(
    *,
    chunks: list[KnowledgeChunk],
    parents: list[MarkdownParentChunk],
    issues: list[IngestionValidationIssue],
) -> tuple[int, int]:
    parent_by_id = {parent.id: parent for parent in parents}
    if len(parent_by_id) != len(parents):
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="duplicate_parent_ids",
                message="Markdown parent.id 存在重复",
            )
        )
    child_parent_ids: set[str] = set()
    orphan_count = 0
    for chunk in chunks:
        if chunk.metadata.get("record_type") != MARKDOWN_CHILD_RECORD_TYPE:
            continue
        parent_id = str(chunk.metadata.get("parent_id") or "")
        parent = parent_by_id.get(parent_id)
        if parent is None:
            orphan_count += 1
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="orphan_markdown_child",
                    message="Markdown child 无法关联 parent",
                    detail={"chunk_id": chunk.id, "parent_id": parent_id},
                )
            )
            continue
        child_parent_ids.add(parent_id)
        for key in ("doc_id", "visibility", "allowed_departments", "allowed_users"):
            if chunk.metadata.get(key) != parent.metadata.get(key):
                issues.append(
                    IngestionValidationIssue(
                        level="error",
                        code="parent_child_metadata_mismatch",
                        message=f"Markdown parent/child metadata.{key} 不一致",
                        detail={"chunk_id": chunk.id, "parent_id": parent_id},
                    )
                )
    parent_without_child = len(set(parent_by_id) - child_parent_ids)
    if parent_without_child:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="markdown_parent_without_child",
                message="存在没有 child 的 Markdown parent",
                detail={"count": parent_without_child},
            )
        )
    return orphan_count, parent_without_child


def _validate_documents(
    documents: list[LoadedDocument],
    issues: list[IngestionValidationIssue],
) -> None:
    source_path_counts = Counter(document.source_path for document in documents)
    duplicated_source_paths = sorted(
        source_path
        for source_path, count in source_path_counts.items()
        if count > 1
    )

    if duplicated_source_paths:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="duplicate_document_source_paths",
                message="读取到重复的文档 source_path",
                detail={"source_paths": duplicated_source_paths},
            )
        )

    for document in documents:
        if not document.source_path:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="empty_document_source_path",
                    message="文档 source_path 为空",
                    detail={"document_type": document.document_type},
                )
            )

        if not document.content.strip():
            issues.append(
                IngestionValidationIssue(
                    level="warning",
                    code="empty_document_content",
                    message="文档内容为空，可能不会生成 chunk",
                    detail={"source_path": document.source_path},
                )
            )

        if document.document_type not in ALLOWED_DOCUMENT_TYPES:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="invalid_document_type",
                    message="文档类型不在允许范围内",
                    detail={
                        "source_path": document.source_path,
                        "document_type": document.document_type,
                    },
                )
            )


def _validate_chunk_ids(
    chunks: list[KnowledgeChunk],
    issues: list[IngestionValidationIssue],
) -> None:
    chunk_id_counts = Counter(chunk.id for chunk in chunks)
    duplicated_chunk_ids = sorted(
        chunk_id for chunk_id, count in chunk_id_counts.items() if count > 1
    )

    if duplicated_chunk_ids:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="duplicate_chunk_ids",
                message="chunk.id 存在重复",
                detail={"chunk_ids": duplicated_chunk_ids},
            )
        )


def _validate_chunks(
    chunks: list[KnowledgeChunk],
    source_paths: set[str],
    doc_ids: set[str],
    issues: list[IngestionValidationIssue],
) -> None:
    for chunk in chunks:
        if not chunk.id:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="empty_chunk_id",
                    message="chunk.id 为空",
                )
            )

        if not chunk.content.strip():
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="empty_chunk_content",
                    message="chunk.content 为空",
                    detail={"chunk_id": chunk.id},
                )
            )

        if not chunk.title:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="empty_chunk_title",
                    message="chunk.title 为空",
                    detail={"chunk_id": chunk.id},
                )
            )

        if not chunk.source:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="empty_chunk_source",
                    message="chunk.source 为空",
                    detail={"chunk_id": chunk.id},
                )
            )

        _validate_chunk_metadata(
            chunk=chunk,
            source_paths=source_paths,
            doc_ids=doc_ids,
            issues=issues,
        )


def _validate_chunk_metadata(
    chunk: KnowledgeChunk,
    source_paths: set[str],
    doc_ids: set[str],
    issues: list[IngestionValidationIssue],
) -> None:
    for key in REQUIRED_METADATA_KEYS:
        if key not in chunk.metadata:
            issues.append(
                IngestionValidationIssue(
                    level="error",
                    code="missing_metadata",
                    message=f"chunk 缺少 metadata.{key}",
                    detail={"chunk_id": chunk.id, "key": key},
                )
            )

    if chunk.metadata.get("chunk_id") != chunk.id:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="chunk_id_mismatch",
                message="metadata.chunk_id 与 chunk.id 不一致",
                detail={
                    "chunk_id": chunk.id,
                    "metadata_chunk_id": chunk.metadata.get("chunk_id"),
                },
            )
        )

    if chunk.metadata.get("title") != chunk.title:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="title_mismatch",
                message="metadata.title 与 chunk.title 不一致",
                detail={
                    "chunk_id": chunk.id,
                    "chunk_title": chunk.title,
                    "metadata_title": chunk.metadata.get("title"),
                },
            )
        )

    source_path = chunk.metadata.get("source_path")
    if source_path not in source_paths:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="unknown_source_path",
                message="chunk.metadata.source_path 无法对应到已读取文档",
                detail={"chunk_id": chunk.id, "source_path": source_path},
            )
        )

    section_path = chunk.metadata.get("section_path")
    if not isinstance(section_path, list) or not section_path:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="invalid_section_path",
                message="metadata.section_path 必须是非空 list",
                detail={"chunk_id": chunk.id, "section_path": section_path},
            )
        )

    document_type = chunk.metadata.get("document_type")
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="invalid_chunk_document_type",
                message="chunk.metadata.document_type 不在允许范围内",
                detail={"chunk_id": chunk.id, "document_type": document_type},
            )
        )

    chunk_index = chunk.metadata.get("chunk_index")
    if not isinstance(chunk_index, int) or chunk_index < 1:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="invalid_chunk_index",
                message="metadata.chunk_index 必须是正整数",
                detail={"chunk_id": chunk.id, "chunk_index": chunk_index},
            )
        )

    doc_id = chunk.metadata.get("doc_id")
    if isinstance(doc_id, str) and doc_id:
        doc_ids.add(doc_id)
    else:
        issues.append(
            IngestionValidationIssue(
                level="error",
                code="invalid_doc_id",
                message="metadata.doc_id 必须是非空字符串",
                detail={"chunk_id": chunk.id, "doc_id": doc_id},
            )
        )
