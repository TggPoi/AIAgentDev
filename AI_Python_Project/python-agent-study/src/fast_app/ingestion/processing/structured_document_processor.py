"""所有知识文档格式共用的解析、Vision、分块编排模块。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fast_app.components.vision.base import BeforeExternalCall
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import DocumentType, KnowledgeChunk, LoadedDocument
from fast_app.ingestion.processing.chunk_builders import (
    ChunkBuildOptions,
    MarkdownChunkBuilder,
)
from fast_app.ingestion.processing.document_loaders import (
    ExcelDocumentLoader,
    PowerPointDocumentLoader,
)
from fast_app.ingestion.processing.document_vision import (
    DocumentProcessingWarning,
    DocumentVisionService,
)
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
    MarkdownParentChunk,
)
from fast_app.ingestion.processing.metadata_models import build_document_metadata
from fast_app.ingestion.processing.office_chunk_builders import (
    ExcelChunkBuilder,
    PdfChunkBuilder,
    PowerPointChunkBuilder,
    WordChunkBuilder,
    build_embedding_fingerprint,
)
from fast_app.ingestion.processing.pdf_processing import PdfDocumentLoader
from fast_app.ingestion.processing.word_processing import WordDocumentLoader


class DocumentProcessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProcessedKnowledgeDocument:
    parents: list[MarkdownParentChunk] = field(default_factory=list)
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    warnings: list[DocumentProcessingWarning] = field(default_factory=list)


class StructuredDocumentProcessor:
    """隐藏格式差异，对调用者只暴露最终 parents/chunks/warnings。"""

    def __init__(
        self,
        *,
        settings: Settings,
        vision_service: DocumentVisionService | None = None,
    ) -> None:
        self._settings = settings
        self._vision = vision_service or DocumentVisionService(settings=settings)
        self._ppt_builder = PowerPointChunkBuilder()
        self._word_builder = WordChunkBuilder()
        self._pdf_builder = PdfChunkBuilder()
        self._excel_builder = ExcelChunkBuilder()
        self._text_builder = MarkdownChunkBuilder()
        self._markdown_builder = MarkdownHierarchyBuilder()

    async def process_file(
        self,
        path: str | Path,
        *,
        document_type: DocumentType,
        source_path: str,
        options: ChunkBuildOptions,
        document_metadata: dict[str, Any] | None = None,
        excel_profile: dict[str, Any] | None = None,
        before_external_call: BeforeExternalCall | None = None,
    ) -> ProcessedKnowledgeDocument:
        file_path = Path(path)
        metadata = build_document_metadata(
            source_path=source_path,
            document_type=document_type,
            knowledge_base_dir=self._settings.knowledge_base_dir,
        )
        metadata.update(document_metadata or {})
        embedding_fingerprint = build_embedding_fingerprint(self._settings)
        vision_fingerprint = self.vision_strategy_fingerprint()

        if document_type in {"markdown", "text"}:
            document = LoadedDocument(
                source_path=source_path,
                content=file_path.read_text(encoding="utf-8"),
                document_type=document_type,
                metadata=metadata,
            )
            if document_type == "markdown":
                hierarchy = self._markdown_builder.build(
                    [document], self._markdown_options(options.source)
                )
                return ProcessedKnowledgeDocument(
                    parents=hierarchy.parents, chunks=hierarchy.children
                )
            return ProcessedKnowledgeDocument(
                chunks=self._text_builder.build([document], options)
            )

        if document_type == "powerpoint":
            document = await asyncio.to_thread(
                PowerPointDocumentLoader(
                    max_image_bytes=self._settings.vision_max_image_bytes,
                    max_image_pixels=self._settings.vision_max_image_pixels,
                ).load_structured_file,
                file_path,
                source_path=source_path,
            )
            document.metadata.update(metadata)
            outcome = await self._vision.analyze_assets_with_warnings(
                contents=document.vision_contents,
                occurrences=document.vision_occurrences,
                mode="embedded_image",
                before_external_call=before_external_call,
            )
            chunks = self._ppt_builder.build(
                    document,
                    options,
                    embedding_fingerprint=embedding_fingerprint,
                    vision_results=outcome.results,
                    vision_strategy_fingerprint=vision_fingerprint,
                )
            self._stamp_vision_metadata(
                chunks, document.vision_occurrences, outcome.warnings
            )
            return ProcessedKnowledgeDocument(
                chunks=chunks,
                warnings=outcome.warnings,
            )

        if document_type == "word":
            document = await asyncio.to_thread(
                WordDocumentLoader(
                    max_image_bytes=self._settings.vision_max_image_bytes,
                    max_image_pixels=self._settings.vision_max_image_pixels,
                ).load_structured_file,
                file_path,
                source_path=source_path,
            )
            document.metadata.update(metadata)
            outcome = await self._vision.analyze_assets_with_warnings(
                contents=document.vision_contents,
                occurrences=document.vision_occurrences,
                mode="embedded_image",
                before_external_call=before_external_call,
            )
            chunks = self._word_builder.build(
                    document,
                    options,
                    embedding_fingerprint=embedding_fingerprint,
                    vision_results=outcome.results,
                    vision_strategy_fingerprint=vision_fingerprint,
                )
            self._stamp_vision_metadata(
                chunks, document.vision_occurrences, outcome.warnings
            )
            return ProcessedKnowledgeDocument(
                chunks=chunks,
                warnings=outcome.warnings,
            )

        if document_type == "pdf":
            document = await asyncio.to_thread(
                PdfDocumentLoader(self._settings).load_structured_file,
                file_path,
                source_path=source_path,
            )
            document.metadata.update(metadata)
            results = {}
            warnings: list[DocumentProcessingWarning] = []
            for scanned, mode in ((False, "embedded_image"), (True, "scanned_page")):
                ids = {
                    occurrence_id
                    for page in document.pages
                    if page.scanned_candidate is scanned
                    for occurrence_id in page.vision_occurrence_ids
                }
                occurrences = [
                    item for item in document.vision_occurrences if item.occurrence_id in ids
                ]
                if not occurrences:
                    continue
                content_ids = {item.content_id for item in occurrences}
                outcome = await self._vision.analyze_assets_with_warnings(
                    contents={
                        key: value
                        for key, value in document.vision_contents.items()
                        if key in content_ids
                    },
                    occurrences=occurrences,
                    mode=mode,
                    before_external_call=before_external_call,
                )
                results.update(outcome.results)
                warnings.extend(outcome.warnings)
            unavailable = [
                page.page_number
                for page in document.pages
                if page.scanned_candidate
                and not page.native_text
                and not any(key in results for key in page.vision_occurrence_ids)
            ]
            if unavailable:
                raise DocumentProcessingError(
                    "PDF_PAGE_CONTENT_UNAVAILABLE",
                    "扫描页没有原生正文且图片识别不可用: "
                    + ", ".join(map(str, unavailable)),
                )
            chunks = self._pdf_builder.build(
                    document,
                    options,
                    embedding_fingerprint=embedding_fingerprint,
                    vision_results=results,
                    vision_strategy_fingerprint=vision_fingerprint,
                )
            self._stamp_vision_metadata(chunks, document.vision_occurrences, warnings)
            return ProcessedKnowledgeDocument(
                chunks=chunks,
                warnings=warnings,
            )

        if document_type == "spreadsheet":
            if excel_profile is None:
                raise DocumentProcessingError(
                    "EXCEL_PROFILE_REQUIRED", "Excel 必须提供显式 Profile"
                )
            document = await asyncio.to_thread(
                ExcelDocumentLoader().load_structured_file,
                file_path,
                source_path=source_path,
            )
            document.metadata.update(metadata)
            return ProcessedKnowledgeDocument(
                chunks=self._excel_builder.build(
                    document,
                    options,
                    profile=excel_profile,
                    embedding_fingerprint=embedding_fingerprint,
                )
            )
        raise DocumentProcessingError("UNSUPPORTED_DOCUMENT_TYPE", "不支持的文档类型")

    def vision_strategy_fingerprint(self) -> str:
        payload = {
            "enabled": self._settings.vision_enabled,
            "model": self._settings.vision_model_name,
            "prompt": self._settings.vision_prompt_version,
            "preprocess": self._settings.vision_preprocess_version,
            "schema": self._settings.vision_schema_version,
            "pdf_scanned_text_threshold": self._settings.pdf_scanned_text_threshold,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _stamp_vision_metadata(self, chunks, occurrences, warnings) -> None:
        occurrence_content = {
            item.occurrence_id: item.content_id for item in occurrences
        }
        locator_occurrence = {
            item.source_locator: item.occurrence_id for item in occurrences
        }
        warning_codes: dict[str, set[str]] = {}
        for warning in warnings:
            occurrence_id = locator_occurrence.get(warning.source_locator)
            if occurrence_id is not None:
                warning_codes.setdefault(occurrence_id, set()).add(warning.code)
        attached_warning_codes: set[str] = set()
        for chunk in chunks:
            occurrence_ids = list(chunk.metadata.get("vision_occurrence_ids") or [])
            existing_warning_codes = set(
                chunk.metadata.get("vision_warning_codes") or []
            )
            existing_warning_codes.update(
                code
                for occurrence_id in occurrence_ids
                for code in warning_codes.get(occurrence_id, set())
            )
            attached_warning_codes.update(existing_warning_codes)
            chunk.metadata.update(
                vision_content_ids=sorted(
                    {
                        occurrence_content[item]
                        for item in occurrence_ids
                        if item in occurrence_content
                    }
                ),
                vision_model_name=self._settings.vision_model_name,
                vision_prompt_version=self._settings.vision_prompt_version,
                vision_preprocess_version=self._settings.vision_preprocess_version,
                vision_warning_codes=sorted(existing_warning_codes),
            )
        # image-only block 分析失败时没有可生成的正文 Chunk；文档仍可降级导入，
        # 但 warning 不能只存在于临时报告中，因此归档到该文档首个 Chunk。
        all_warning_codes = {
            code for codes in warning_codes.values() for code in codes
        }
        unattached = all_warning_codes - attached_warning_codes
        if chunks and unattached:
            chunks[0].metadata["vision_warning_codes"] = sorted(
                {
                    *(chunks[0].metadata.get("vision_warning_codes") or []),
                    *unattached,
                }
            )

    def _markdown_options(self, source: str) -> MarkdownHierarchyOptions:
        return MarkdownHierarchyOptions(
            source=source,
            parent_target_tokens=self._settings.markdown_parent_target_tokens,
            parent_max_tokens=self._settings.markdown_parent_max_tokens,
            parent_max_chars=self._settings.markdown_parent_max_chars,
            child_target_tokens=self._settings.markdown_child_target_tokens,
            child_max_tokens=self._settings.markdown_child_max_tokens,
            child_min_tokens=self._settings.markdown_child_min_tokens,
            child_overlap_tokens=self._settings.markdown_child_overlap_tokens,
        )


__all__ = [
    "DocumentProcessingError",
    "ProcessedKnowledgeDocument",
    "StructuredDocumentProcessor",
]
