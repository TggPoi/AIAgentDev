"""本地知识目录的无副作用 prebuild。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.vision.base import BeforeExternalCall
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.processing.chunk_builders import ChunkBuildOptions
from fast_app.ingestion.processing.markdown_hierarchy import MarkdownParentChunk
from fast_app.ingestion.processing.metadata_models import (
    apply_local_corpus_ownership,
    build_doc_id,
)
from fast_app.ingestion.processing.structured_document_processor import (
    StructuredDocumentProcessor,
)
from fast_app.ingestion.validation.document_validation import (
    KnowledgeDocumentValidationLimits,
    validate_knowledge_document_package,
)


SUPPORTED_LOCAL_DOCUMENT_TYPES = {
    ".md": "markdown",
    ".txt": "text",
    ".pptx": "powerpoint",
    ".xlsx": "spreadsheet",
    ".docx": "word",
    ".pdf": "pdf",
}


class LocalCorpusOwnershipConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RegisteredDocumentOwnership:
    doc_id: str
    source_path: str
    status: str
    has_active_job: bool


@dataclass(frozen=True)
class LocalCorpusPrebuildResult:
    local_corpus_id: str
    document_count: int
    parents: list[MarkdownParentChunk]
    chunks: list[KnowledgeChunk]
    vectors: list[list[float]]
    manifest_documents: list[dict]
    warnings: list[dict[str, str]] = field(default_factory=list)
    excluded_source_paths: list[str] = field(default_factory=list)


class LocalKnowledgeCorpusBuilder:
    """扫描、解析、Vision 和 Embedding 全在 Store mutation 前完成。"""

    def __init__(
        self,
        *,
        settings: Settings,
        embedding_client: BaseEmbeddingClient,
        processor: StructuredDocumentProcessor | None = None,
    ) -> None:
        self._settings = settings
        self._embedding = embedding_client
        self._processor = processor or StructuredDocumentProcessor(settings=settings)

    async def prebuild(
        self,
        *,
        source_dir: str | Path,
        registered_documents: list[RegisteredDocumentOwnership],
        excel_default_mode: str | None,
        expected_document_count: int | None = None,
        before_external_call: BeforeExternalCall | None = None,
    ) -> LocalCorpusPrebuildResult:
        root = Path(source_dir)
        if not root.is_dir():
            raise ValueError(f"本地知识目录不存在: {root}")
        registry_by_path, registry_by_doc_id = self._validate_registry(
            registered_documents
        )
        paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_LOCAL_DOCUMENT_TYPES
        )
        parents: list[MarkdownParentChunk] = []
        chunks: list[KnowledgeChunk] = []
        warnings: list[dict[str, str]] = []
        excluded: list[str] = []
        manifests: list[dict] = []
        processed_count = 0
        for owned in registry_by_path.values():
            registered_path = Path(owned.source_path)
            if not _is_within_root(registered_path, root):
                continue
            if owned.status == "active":
                if not registered_path.is_file():
                    warnings.append(
                        {
                            "code": "LOCAL_CORPUS_ACTIVE_OFFICE_FILE_MISSING",
                            "source_path": owned.source_path,
                            "message": "Office Import active 文档对应的磁盘文件不存在",
                        }
                    )
                continue
            if owned.status == "pending":
                code = (
                    "LOCAL_CORPUS_IMPORT_PENDING"
                    if owned.has_active_job
                    else "LOCAL_CORPUS_ORPHAN_PENDING_DOCUMENT"
                )
                raise LocalCorpusOwnershipConflict(
                    code,
                    f"Office Import pending 文档阻止本地重建: {owned.source_path}",
                )
            raise LocalCorpusOwnershipConflict(
                "LOCAL_CORPUS_REGISTRY_STATUS_INVALID",
                f"未知 KnowledgeDocument 状态: {owned.status}",
            )
        options = ChunkBuildOptions(
            source=self._settings.ingestion_source_name,
            max_chars=self._settings.markdown_chunk_max_chars,
            overlap_chars=self._settings.markdown_chunk_overlap_chars,
            max_tokens=self._settings.markdown_chunk_max_tokens,
            min_chars=self._settings.markdown_chunk_min_chars,
        )

        for path in paths:
            source_path = path.as_posix()
            doc_id = build_doc_id(source_path)
            path_owner = registry_by_path.get(source_path)
            doc_owner = registry_by_doc_id.get(doc_id)
            if (
                path_owner is not None
                and doc_owner is not None
                and path_owner != doc_owner
            ):
                raise LocalCorpusOwnershipConflict(
                    "LOCAL_CORPUS_REGISTRY_COLLISION",
                    "source_path 与 doc_id 指向不同 Office ownership 记录",
                )
            owned = path_owner or doc_owner
            if owned is not None:
                if owned.status == "active":
                    excluded.append(source_path)
                    continue
                raise AssertionError("Office registry 状态应已在扫描前完成校验")

            document_type = SUPPORTED_LOCAL_DOCUMENT_TYPES[path.suffix.lower()]
            validate_knowledge_document_package(
                path,
                document_type=document_type,
                limits=KnowledgeDocumentValidationLimits(
                    max_file_bytes=self._settings.max_upload_file_bytes,
                    max_pdf_pages=self._settings.pdf_max_pages,
                ),
            )
            source_revision = _sha256_file(path)
            metadata = apply_local_corpus_ownership(
                {"doc_id": doc_id, "source_path": source_path},
                local_corpus_id=self._settings.local_corpus_id,
                source_revision=source_revision,
            )
            profile = None
            if document_type == "spreadsheet":
                sidecar = Path(f"{path}.profile.json")
                if sidecar.is_file():
                    profile = json.loads(sidecar.read_text(encoding="utf-8"))
                    if not isinstance(profile, dict):
                        raise ValueError(f"Excel Profile 必须是 JSON object: {sidecar}")
                elif excel_default_mode == "section":
                    profile = {"mode": "section", "sheets": []}
                else:
                    raise ValueError(
                        f"Excel 缺少 {path.name}.profile.json；必须显式传 "
                        "--excel-default-mode section"
                    )
            processed = await self._processor.process_file(
                path,
                document_type=document_type,
                source_path=source_path,
                options=options,
                document_metadata=metadata,
                excel_profile=profile,
                before_external_call=before_external_call,
            )
            processed_count += 1
            parents.extend(processed.parents)
            chunks.extend(processed.chunks)
            warnings.extend(
                {
                    "code": warning.code,
                    "source_path": source_path,
                    "message": warning.message,
                }
                for warning in processed.warnings
            )
            manifests.append(
                {
                    "doc_id": doc_id,
                    "source_path": source_path,
                    "document_type": document_type,
                    "source_revision": source_revision,
                    "parent_ids": [item.id for item in processed.parents],
                    "chunk_ids": [item.id for item in processed.chunks],
                }
            )

        if expected_document_count is not None and processed_count != expected_document_count:
            raise ValueError(
                "扫描文档数量与人工验收值不一致: "
                f"actual={processed_count}, expected={expected_document_count}"
            )
        vectors = await self._embedding.embed_documents(
            [chunk.search_text or chunk.content for chunk in chunks]
        )
        if len(vectors) != len(chunks) or any(
            len(vector) != self._settings.embedding_dim for vector in vectors
        ):
            raise RuntimeError("本地语料 Embedding 数量或维度不匹配")
        return LocalCorpusPrebuildResult(
            local_corpus_id=self._settings.local_corpus_id,
            document_count=processed_count,
            parents=parents,
            chunks=chunks,
            vectors=vectors,
            manifest_documents=manifests,
            warnings=warnings,
            excluded_source_paths=sorted(excluded),
        )

    def _validate_registry(
        self, rows: list[RegisteredDocumentOwnership]
    ) -> tuple[dict[str, RegisteredDocumentOwnership], dict[str, RegisteredDocumentOwnership]]:
        by_path: dict[str, RegisteredDocumentOwnership] = {}
        by_doc_id: dict[str, RegisteredDocumentOwnership] = {}
        for row in rows:
            source_path = Path(row.source_path).as_posix()
            if source_path in by_path and by_path[source_path].doc_id != row.doc_id:
                raise LocalCorpusOwnershipConflict(
                    "LOCAL_CORPUS_REGISTRY_COLLISION", "同一 source_path 映射到不同 doc_id"
                )
            if row.doc_id in by_doc_id and by_doc_id[row.doc_id].source_path != row.source_path:
                raise LocalCorpusOwnershipConflict(
                    "LOCAL_CORPUS_REGISTRY_COLLISION", "同一 doc_id 映射到不同 source_path"
                )
            normalized = RegisteredDocumentOwnership(
                doc_id=row.doc_id,
                source_path=source_path,
                status=row.status,
                has_active_job=row.has_active_job,
            )
            by_path[source_path] = normalized
            by_doc_id[row.doc_id] = normalized
        return by_path, by_doc_id


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


__all__ = [
    "LocalCorpusOwnershipConflict",
    "LocalCorpusPrebuildResult",
    "LocalKnowledgeCorpusBuilder",
    "RegisteredDocumentOwnership",
    "SUPPORTED_LOCAL_DOCUMENT_TYPES",
]
