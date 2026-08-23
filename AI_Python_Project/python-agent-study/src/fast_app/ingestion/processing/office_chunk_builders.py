from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from fast_app.domain.knowledge_models import (
    ExcelFieldValue,
    ExcelRecord,
    ExcelRow,
    ExcelSheet,
    KnowledgeChunk,
    LoadedExcelDocument,
    LoadedPdfDocument,
    LoadedPowerPointDocument,
    LoadedWordDocument,
    PdfPage,
    VisionAnalysisResult,
    WordBlock,
)
from fast_app.ingestion.processing.chunk_builders import ChunkBuildOptions, TextSplitter
from fast_app.ingestion.processing.document_vision import render_vision_result
from fast_app.ingestion.processing.metadata_models import build_chunk_metadata


BUILDER_SCHEMA_VERSION = "office-vision-v2"


class ExcelConfigurationRequired(ValueError):
    """Excel 无法按现有 Profile 唯一解释时暂停任务。"""

    def __init__(self, message: str, preview: dict[str, Any]) -> None:
        super().__init__(message)
        self.preview = preview


def build_embedding_fingerprint(settings: Any) -> str:
    """把会改变向量语义的配置压缩成稳定指纹。"""

    raw = "|".join(
        [
            str(settings.embedding_provider),
            str(settings.embedding_model_name),
            str(settings.embedding_dim),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_excel_preview(document: LoadedExcelDocument) -> dict[str, Any]:
    """生成供 React 确认 Record/Section Profile 的稳定预览。"""

    sheets = [
        {
            "sheet_name": sheet.name,
            "business_header_hint": sheet.business_header_hint,
            "sample_rows": [
                {"row_number": row.row_number, "values": row.values}
                for row in sheet.rows[:5]
            ],
        }
        for sheet in document.sheets
    ]
    fingerprint = hashlib.sha256(
        json.dumps(sheets, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {"sheets": sheets, "preview_fingerprint": fingerprint}


class PowerPointChunkBuilder:
    """按稳定 slide_id 构造页内局部 Chunk。"""

    def __init__(self, splitter: TextSplitter | None = None) -> None:
        self.splitter = splitter or TextSplitter()

    def build(
        self,
        document: LoadedPowerPointDocument,
        options: ChunkBuildOptions,
        *,
        embedding_fingerprint: str,
        vision_results: dict[str, VisionAnalysisResult] | None = None,
        vision_strategy_fingerprint: str = "vision-disabled",
    ) -> list[KnowledgeChunk]:
        """把每页内容切为局部 Chunk，页码变化只影响 index_hash。"""

        chunks: list[KnowledgeChunk] = []
        doc_id = str(document.metadata["doc_id"])
        for slide in document.slides:
            identity_key = f"ppt:slide:{slide.slide_id}"
            title = slide.title or f"Slide {slide.slide_number}"
            vision_texts = [
                render_vision_result(vision_results[occurrence_id])
                for occurrence_id in slide.vision_occurrence_ids
                if vision_results and occurrence_id in vision_results
            ]
            content = "\n\n".join(
                part
                for part in (
                    title,
                    slide.content,
                    f"Notes: {slide.notes}" if slide.notes else "",
                    *vision_texts,
                )
                if part
            )
            for local_index, part in enumerate(
                self.splitter.split(content, options), start=1
            ):
                chunk_id = _office_chunk_id(doc_id, identity_key, local_index)
                metadata = build_chunk_metadata(
                    document_metadata=document.metadata,
                    chunk_id=chunk_id,
                    title=title,
                    section_path=[f"Slide {slide.slide_number}: {title}"],
                    heading_level=1,
                    section_index=slide.slide_number,
                    chunk_index=local_index,
                )
                metadata.update(
                    identity_key=identity_key,
                    slide_id=slide.slide_id,
                    slide_number=slide.slide_number,
                    slide_warnings=list(slide.warnings),
                    slide_chunk_index=local_index,
                    has_vision_content=bool(vision_texts),
                    vision_occurrence_ids=list(slide.vision_occurrence_ids),
                    vision_warning_codes=list(slide.warnings),
                    vision_strategy_fingerprint=vision_strategy_fingerprint,
                )
                _add_hashes(metadata, part, embedding_fingerprint)
                chunks.append(
                    KnowledgeChunk(
                        id=chunk_id,
                        content=part,
                        source=options.source,
                        title=title,
                        metadata=metadata,
                    )
                )
        return chunks


class WordChunkBuilder:
    """优先按完整 DOCX block 装箱，只在单 block 超限时块内拆分。"""

    def __init__(self, splitter: TextSplitter | None = None) -> None:
        self.splitter = splitter or TextSplitter()

    def build(
        self,
        document: LoadedWordDocument,
        options: ChunkBuildOptions,
        *,
        embedding_fingerprint: str,
        vision_results: dict[str, VisionAnalysisResult] | None = None,
        vision_strategy_fingerprint: str = "vision-disabled",
    ) -> list[KnowledgeChunk]:
        rendered = [
            (block, self._block_parts(block, options, vision_results or {}))
            for block in document.blocks
        ]
        units: list[tuple[WordBlock, int, str]] = [
            (block, part_index, part)
            for block, parts in rendered
            for part_index, part in enumerate(parts, start=1)
            if part.strip()
        ]
        packed: list[list[tuple[WordBlock, int, str]]] = []
        current: list[tuple[WordBlock, int, str]] = []
        for item in units:
            candidate = "\n\n".join(
                [*(text for _, _, text in current), item[2]]
            )
            same_section = not current or current[-1][0].section_id == item[0].section_id
            if current and (
                not same_section
                or len(candidate) > options.max_chars
                or self.splitter.token_counter.count(candidate) > options.max_tokens
            ):
                packed.append(current)
                current = []
            current.append(item)
        if current:
            packed.append(current)

        chunks: list[KnowledgeChunk] = []
        doc_id = str(document.metadata["doc_id"])
        for chunk_index, group in enumerate(packed, start=1):
            first_block = group[0][0]
            first_part_index = group[0][1]
            content = "\n\n".join(text for _, _, text in group)
            identity_key = (
                f"docx:section:{first_block.section_id}:block:{first_block.block_id}:"
                f"part:{first_part_index}"
            )
            chunk_id = _office_chunk_id(doc_id, identity_key, 1)
            occurrence_ids = [
                occurrence_id
                for block, _, _ in group
                for occurrence_id in block.vision_occurrence_ids
            ]
            metadata = build_chunk_metadata(
                document_metadata=document.metadata,
                chunk_id=chunk_id,
                title=first_block.section_title,
                section_path=[first_block.section_title],
                heading_level=first_block.heading_level,
                section_index=chunk_index,
                chunk_index=chunk_index,
            )
            metadata.update(
                identity_key=identity_key,
                block_ids=[block.block_id for block, _, _ in group],
                has_vision_content=any(
                    occurrence_id in (vision_results or {})
                    for occurrence_id in occurrence_ids
                ),
                vision_occurrence_ids=occurrence_ids,
                vision_warning_codes=list(document.warnings),
                vision_strategy_fingerprint=vision_strategy_fingerprint,
            )
            _add_hashes(metadata, content, embedding_fingerprint)
            chunks.append(
                KnowledgeChunk(
                    id=chunk_id,
                    content=content,
                    source=options.source,
                    title=first_block.section_title,
                    metadata=metadata,
                )
            )
        return chunks

    def _block_parts(
        self,
        block: WordBlock,
        options: ChunkBuildOptions,
        vision_results: dict[str, VisionAnalysisResult],
    ) -> list[str]:
        vision = "\n\n".join(
            render_vision_result(vision_results[occurrence_id])
            for occurrence_id in block.vision_occurrence_ids
            if occurrence_id in vision_results
        )
        combined = "\n\n".join(part for part in (block.text, vision) if part)
        if (
            len(combined) <= options.max_chars
            and self.splitter.token_counter.count(combined) <= options.max_tokens
        ):
            return [combined] if combined else []
        if not vision:
            return self.splitter.split(block.text, options)
        available_chars = max(options.min_chars, options.max_chars - len(vision) - 2)
        adjusted = ChunkBuildOptions(
            source=options.source,
            max_chars=available_chars,
            overlap_chars=min(options.overlap_chars, max(0, available_chars - 1)),
            max_tokens=max(1, options.max_tokens - self.splitter.token_counter.count(vision)),
            min_chars=min(options.min_chars, available_chars),
        )
        text_parts = self.splitter.split(block.text, adjusted) or [""]
        return ["\n\n".join(part for part in (text, vision) if part) for text in text_parts]


class PdfChunkBuilder:
    """按 PDF 页构造 Chunk，扫描页只消费 full-page Vision 结果。"""

    def __init__(self, splitter: TextSplitter | None = None) -> None:
        self.splitter = splitter or TextSplitter()

    def build(
        self,
        document: LoadedPdfDocument,
        options: ChunkBuildOptions,
        *,
        embedding_fingerprint: str,
        vision_results: dict[str, VisionAnalysisResult] | None = None,
        vision_strategy_fingerprint: str = "vision-disabled",
    ) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        doc_id = str(document.metadata["doc_id"])
        for page in document.pages:
            vision_texts = [
                render_vision_result(vision_results[occurrence_id])
                for occurrence_id in page.vision_occurrence_ids
                if vision_results and occurrence_id in vision_results
            ]
            content = "\n\n".join(
                part for part in (page.native_text, *vision_texts) if part
            )
            for local_index, part in enumerate(self.splitter.split(content, options), start=1):
                identity_key = f"pdf:page:{page.page_number}"
                chunk_id = _office_chunk_id(doc_id, identity_key, local_index)
                metadata = build_chunk_metadata(
                    document_metadata=document.metadata,
                    chunk_id=chunk_id,
                    title=f"Page {page.page_number}",
                    section_path=[f"Page {page.page_number}"],
                    heading_level=1,
                    section_index=page.page_number,
                    chunk_index=local_index,
                )
                metadata.update(
                    identity_key=identity_key,
                    page_number=page.page_number,
                    scanned_candidate=page.scanned_candidate,
                    has_vision_content=bool(vision_texts),
                    vision_occurrence_ids=list(page.vision_occurrence_ids),
                    vision_warning_codes=list(page.warnings),
                    vision_strategy_fingerprint=vision_strategy_fingerprint,
                )
                _add_hashes(metadata, part, embedding_fingerprint)
                chunks.append(
                    KnowledgeChunk(
                        id=chunk_id,
                        content=part,
                        source=options.source,
                        title=f"Page {page.page_number}",
                        metadata=metadata,
                    )
                )
        return chunks


class ExcelChunkBuilder:
    """按 Profile 构造 Record Chunk，或按 Sheet 区段构造 Section Chunk。"""

    row_block_size = 100

    def __init__(self, splitter: TextSplitter | None = None) -> None:
        self.splitter = splitter or TextSplitter()

    def build(
        self,
        document: LoadedExcelDocument,
        options: ChunkBuildOptions,
        *,
        profile: dict[str, Any],
        embedding_fingerprint: str,
    ) -> list[KnowledgeChunk]:
        """按 Workbook 默认模式和可选 Sheet mode 分派构建逻辑。"""

        profile_mode = profile.get("mode")
        configs = list(profile.get("sheets") or [])
        # 历史 Section Profile 没有 Sheet 配置，继续按原行为处理整本工作簿。
        if profile_mode == "section" and not configs:
            return self._build_sections(
                document, options, embedding_fingerprint=embedding_fingerprint
            )
        if profile_mode not in {"record", "section", "mixed"}:
            raise ExcelConfigurationRequired(
                "Excel 尚未确认 Record、Section 或 Mixed 导入模式",
                build_excel_preview(document),
            )
        return self._build_profiled_sheets(
            document,
            options,
            profile=profile,
            embedding_fingerprint=embedding_fingerprint,
        )

    def _build_sections(
        self,
        document: LoadedExcelDocument,
        options: ChunkBuildOptions,
        *,
        embedding_fingerprint: str,
    ) -> list[KnowledgeChunk]:
        """按物理行区段构建 Sheet 局部替换所需的 Chunk。"""

        chunks: list[KnowledgeChunk] = []
        for sheet in document.sheets:
            chunks.extend(
                self._build_sheet_sections(
                    document,
                    sheet,
                    sheet_key=sheet.name,
                    options=options,
                    embedding_fingerprint=embedding_fingerprint,
                )
            )
        return chunks

    def _build_profiled_sheets(
        self,
        document: LoadedExcelDocument,
        options: ChunkBuildOptions,
        *,
        profile: dict[str, Any],
        embedding_fingerprint: str,
    ) -> list[KnowledgeChunk]:
        """逐 Sheet 匹配配置，并按有效 mode 构建 Record 或 Section Chunk。"""

        preview = build_excel_preview(document)
        configs = list(profile.get("sheets") or [])
        profile_mode = str(profile.get("mode") or "")
        chunks: list[KnowledgeChunk] = []
        for sheet in document.sheets:
            config = _match_sheet_config(sheet, configs)
            if config is None:
                if sheet.rows:
                    raise ExcelConfigurationRequired(
                        f"工作表 {sheet.name} 没有匹配的 Profile",
                        preview,
                    )
                continue
            sheet_mode = config.get("mode") or profile_mode
            if profile_mode == "mixed" and config.get("mode") is None:
                raise ExcelConfigurationRequired(
                    f"Mixed Profile 的工作表 {sheet.name} 缺少 mode", preview
                )
            if sheet_mode == "record":
                chunks.extend(
                    self._build_sheet_records(
                        document,
                        sheet,
                        config,
                        options,
                        embedding_fingerprint,
                        preview,
                    )
                )
            elif sheet_mode == "section":
                chunks.extend(
                    self._build_sheet_sections(
                        document,
                        sheet,
                        sheet_key=str(config["sheet_key"]),
                        options=options,
                        embedding_fingerprint=embedding_fingerprint,
                    )
                )
            else:
                raise ExcelConfigurationRequired(
                    f"工作表 {sheet.name} 的 mode 无效", preview
                )
        return chunks

    def _build_sheet_sections(
        self,
        document: LoadedExcelDocument,
        sheet: ExcelSheet,
        *,
        sheet_key: str,
        options: ChunkBuildOptions,
        embedding_fingerprint: str,
    ) -> list[KnowledgeChunk]:
        """为一个 Section Sheet 构建保留实际行列范围的 Chunk。"""

        chunks: list[KnowledgeChunk] = []
        doc_id = str(document.metadata["doc_id"])
        # Section 没有业务行身份；结构变化通过该 Hash 更新整张 Sheet 的 index_hash。
        sheet_structure_hash = _sheet_structure_hash(sheet)
        blocks: dict[int, list[ExcelRow]] = defaultdict(list)
        for row in sheet.rows:
            block_start = (
                (row.row_number - 1) // self.row_block_size
            ) * self.row_block_size + 1
            blocks[block_start].append(row)
        for section_index, block_start in enumerate(sorted(blocks), start=1):
            rows = blocks[block_start]
            block_end = block_start + self.row_block_size - 1
            identity_key = (
                f"xlsx:sheet:{sheet_key}:rows:{block_start}-{block_end}"
            )
            source_columns = list(sheet.source_columns) or sorted(
                {column for row in rows for column in row.values},
                key=_excel_column_number,
            )
            # 完整行优先装箱，同时返回每个局部 Chunk 真正覆盖的行范围。
            parts = _split_section_rows(sheet, rows, options, self.splitter)
            for local_index, (part, row_start, row_end) in enumerate(parts, start=1):
                chunk_id = _office_chunk_id(doc_id, identity_key, local_index)
                title = f"Sheet {sheet.name} / Rows {row_start}-{row_end}"
                metadata = build_chunk_metadata(
                    document_metadata=document.metadata,
                    chunk_id=chunk_id,
                    title=title,
                    section_path=[
                        f"Sheet: {sheet.name}",
                        f"Rows {row_start}-{row_end}",
                    ],
                    heading_level=2,
                    section_index=section_index,
                    chunk_index=local_index,
                )
                metadata.update(
                    identity_key=identity_key,
                    excel_mode="section",
                    sheet_key=sheet_key,
                    sheet_name=sheet.name,
                    sheet_structure_hash=sheet_structure_hash,
                    row_start=row_start,
                    row_end=row_end,
                    source_columns=source_columns,
                    section_chunk_index=local_index,
                )
                _add_hashes(metadata, part, embedding_fingerprint)
                chunks.append(
                    KnowledgeChunk(chunk_id, part, options.source, title, metadata)
                )
        return chunks

    def _build_sheet_records(
        self,
        document: LoadedExcelDocument,
        sheet: ExcelSheet,
        config: dict[str, Any],
        options: ChunkBuildOptions,
        embedding_fingerprint: str,
        preview: dict[str, Any],
    ) -> list[KnowledgeChunk]:
        """校验表头和主键后，按记录及可选字段组生成稳定 Chunk。"""

        header_row_number = int(config.get("header_row") or 1)
        header_row = next(
            (row for row in sheet.rows if row.row_number == header_row_number), None
        )
        if header_row is None:
            raise ExcelConfigurationRequired(
                f"工作表 {sheet.name} 缺少表头行 {header_row_number}", preview
            )

        fields = list(config.get("fields") or [])
        column_by_field = _resolve_field_columns(header_row.values, fields, preview)
        # 可选字段在本版本中可能不存在；只有已唯一映射到物理列的字段才参与分块。
        indexed_fields = [
            field
            for field in fields
            if field.get("indexed", True)
            and str(field["field_id"]) in column_by_field
        ]
        identity_ids = list(config.get("identity_field_ids") or [])
        if not identity_ids or any(field_id not in column_by_field for field_id in identity_ids):
            raise ExcelConfigurationRequired(
                f"工作表 {sheet.name} 的主键字段缺失", preview
            )

        mapped_columns = set(column_by_field.values())
        unknown_populated = sorted(
            {
                column
                for row in sheet.rows
                if row.row_number > header_row_number
                for column, value in row.values.items()
                if column not in mapped_columns and value
            }
        )
        if unknown_populated:
            raise ExcelConfigurationRequired(
                f"工作表 {sheet.name} 存在未配置的有值列: {', '.join(unknown_populated)}",
                preview,
            )
        blank_unconfigured = sorted(set(sheet.source_columns) - mapped_columns)
        if blank_unconfigured:
            warnings = set(document.metadata.get("extraction_warnings", []))
            warnings.add("xlsx_unconfigured_blank_column_skipped")
            document.metadata["extraction_warnings"] = sorted(warnings)

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for field in indexed_fields:
            groups[str(field.get("field_group") or "record")].append(field)
        field_by_id = {str(field["field_id"]): field for field in fields}
        seen_identities: set[str] = set()
        chunks: list[KnowledgeChunk] = []
        doc_id = str(document.metadata["doc_id"])
        sheet_key = str(config["sheet_key"])

        for row in sheet.rows:
            if row.row_number <= header_row_number:
                continue
            identity_values = [
                row.values.get(column_by_field[field_id], "").strip()
                for field_id in identity_ids
            ]
            if not any(row.values.values()):
                continue
            if any(not value for value in identity_values):
                raise ExcelConfigurationRequired(
                    f"工作表 {sheet.name} 第 {row.row_number} 行主键为空", preview
                )
            row_identity = "|".join(identity_values)
            if row_identity in seen_identities:
                raise ExcelConfigurationRequired(
                    f"工作表 {sheet.name} 存在重复主键: {row_identity}", preview
                )
            seen_identities.add(row_identity)

            # Profile 映射在这里把易变 A/B/C 坐标提升为稳定 field_id。
            record = ExcelRecord(
                sheet_key=sheet_key,
                row_identity=row_identity,
                row_number=row.row_number,
                fields={
                    field_id: row.cells.get(
                        column,
                        ExcelFieldValue(
                            value=row.values.get(column, ""),
                            formula=None,
                            cached_value=None,
                            source_column=column,
                            source_coordinate=f"{column}{row.row_number}",
                        ),
                    )
                    for field_id, column in column_by_field.items()
                },
            )

            for group_name, group_fields in groups.items():
                selected_ids = list(
                    dict.fromkeys(identity_ids + [str(item["field_id"]) for item in group_fields])
                )
                rendered: list[str] = []
                coordinates: dict[str, str] = {}
                for field_id in selected_ids:
                    field = field_by_id[field_id]
                    column = column_by_field[field_id]
                    value = record.fields[field_id].value
                    if value:
                        # 检索正文使用稳定 field_id；展示名变化不应触发重新 Embedding。
                        rendered.append(f"{field_id}={value}")
                    coordinates[field_id] = record.fields[
                        field_id
                    ].source_coordinate
                if not rendered:
                    continue
                content = "\n".join(rendered)
                row_key = hashlib.sha256(row_identity.encode("utf-8")).hexdigest()[:24]
                identity_key = f"xlsx:sheet:{sheet_key}:row:{row_key}:group:{group_name}"
                for local_index, part in enumerate(
                    self.splitter.split(content, options), start=1
                ):
                    chunk_id = _office_chunk_id(doc_id, identity_key, local_index)
                    title = f"{sheet.name} / {row_identity}"
                    metadata = build_chunk_metadata(
                        document_metadata=document.metadata,
                        chunk_id=chunk_id,
                        title=title,
                        section_path=[f"Sheet: {sheet.name}", f"Record: {row_identity}"],
                        heading_level=2,
                        section_index=row.row_number,
                        chunk_index=local_index,
                    )
                    metadata.update(
                        identity_key=identity_key,
                        excel_mode="record",
                        sheet_key=sheet_key,
                        sheet_name=sheet.name,
                        row_identity=row_identity,
                        row_number=row.row_number,
                        field_group=group_name,
                        field_coordinates=coordinates,
                        field_display_names={
                            field_id: str(field_by_id[field_id]["display_name"])
                            for field_id in selected_ids
                        },
                        record_chunk_index=local_index,
                    )
                    _add_hashes(metadata, part, embedding_fingerprint)
                    chunks.append(
                        KnowledgeChunk(chunk_id, part, options.source, title, metadata)
                    )
        return chunks


def _resolve_field_columns(
    headers: dict[str, str],
    fields: list[dict[str, Any]],
    preview: dict[str, Any],
) -> dict[str, str]:
    """通过 display_name/aliases 把稳定 field_id 唯一映射到当前物理列。"""

    normalized_headers: dict[str, list[str]] = defaultdict(list)
    for column, value in headers.items():
        normalized_headers[_normalize_label(value)].append(column)
    result: dict[str, str] = {}
    for field in fields:
        field_id = str(field["field_id"])
        aliases = [field.get("display_name"), *(field.get("header_aliases") or [])]
        matches = {
            column
            for alias in aliases
            for column in normalized_headers.get(_normalize_label(alias), [])
        }
        if len(matches) == 1:
            result[field_id] = matches.pop()
        elif field.get("required") or matches:
            raise ExcelConfigurationRequired(
                f"字段 {field_id} 无法唯一匹配表头", preview
            )
    return result


def _match_sheet_config(
    sheet: ExcelSheet, configs: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """通过稳定 sheet_key 和名称别名唯一匹配一个 Sheet Profile。"""

    name = _normalize_label(sheet.name)
    matches = [
        config
        for config in configs
        if name
        in {
            _normalize_label(alias)
            for alias in [config.get("sheet_key"), *(config.get("sheet_name_aliases") or [])]
        }
    ]
    return matches[0] if len(matches) == 1 else None


def _render_section_rows(sheet: ExcelSheet, rows: list[ExcelRow]) -> str:
    """按 A/B/C 自然顺序渲染保留原始行列坐标的 Section 正文。"""

    columns = sorted(
        {column for row in rows for column in row.values}, key=_excel_column_number
    )
    lines = [
        f"Sheet: {sheet.name}",
        f"| Row | {' | '.join(columns)} |",
        f"| --- | {' | '.join(['---'] * len(columns))} |",
    ]
    lines.extend(
        f"| {row.row_number} | {' | '.join(row.values.get(column, '') for column in columns)} |"
        for row in rows
    )
    return "\n".join(lines)


def _split_section_rows(
    sheet: ExcelSheet,
    rows: list[ExcelRow],
    options: ChunkBuildOptions,
    splitter: TextSplitter,
) -> list[tuple[str, int, int]]:
    """按完整 Excel 行贪心装箱；只有单行超限时才退回行内切割。"""

    columns = sorted(
        {column for row in rows for column in row.values}, key=_excel_column_number
    )
    header = "\n".join(
        [
            f"Sheet: {sheet.name}",
            f"| Row | {' | '.join(columns)} |",
            f"| --- | {' | '.join(['---'] * len(columns))} |",
        ]
    )
    row_lines = [
        (
            row.row_number,
            f"| {row.row_number} | {' | '.join(row.values.get(column, '') for column in columns)} |",
        )
        for row in rows
    ]
    result: list[tuple[str, int, int]] = []
    packed: list[tuple[int, str]] = []

    def fits(lines: list[tuple[int, str]]) -> bool:
        text = "\n".join([header, *(line for _, line in lines)])
        return len(text) <= options.max_chars and splitter.token_counter.count(text) <= options.max_tokens

    for row_number, row_line in row_lines:
        item = (row_number, row_line)
        if fits([*packed, item]):
            packed.append(item)
            continue
        if packed:
            result.append(
                (
                    "\n".join([header, *(line for _, line in packed)]),
                    packed[0][0],
                    packed[-1][0],
                )
            )
            packed = []
        if fits([item]):
            packed.append(item)
            continue

        # 单行本身超限时保留表头，并只切割这一行。
        header_chars = len(header) + 1
        header_tokens = splitter.token_counter.count(header)
        row_options = ChunkBuildOptions(
            source=options.source,
            max_chars=max(1, options.max_chars - header_chars),
            overlap_chars=options.overlap_chars,
            max_tokens=max(1, options.max_tokens - header_tokens),
            min_chars=1,
        )
        result.extend(
            ("\n".join([header, part]), row_number, row_number)
            for part in splitter.split(row_line, row_options)
        )

    if packed:
        result.append(
            (
                "\n".join([header, *(line for _, line in packed)]),
                packed[0][0],
                packed[-1][0],
            )
        )
    return result


def _office_chunk_id(doc_id: str, identity_key: str, local_index: int) -> str:
    """用文档身份、局部业务身份和局部序号生成稳定 Chunk ID。"""

    raw = f"{doc_id}|{identity_key}|{local_index}"
    return f"chunk_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _add_hashes(
    metadata: dict[str, Any], content: str, embedding_fingerprint: str
) -> None:
    """计算正文 Hash，以及包含 ACL、来源位置和配置指纹的索引 Hash。"""

    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    index_payload = {
        "content_hash": content_hash,
        "identity_key": metadata["identity_key"],
        "section_path": metadata["section_path"],
        "title": metadata["title"],
        "visibility": metadata.get("visibility"),
        "allowed_departments": sorted(
            {str(value) for value in metadata.get("allowed_departments", [])}
        ),
        "allowed_users": sorted(
            {str(value) for value in metadata.get("allowed_users", [])}
        ),
        "source_coordinates": {
            key: metadata[key]
            for key in (
                "slide_number",
                "page_number",
                "row_number",
                "row_start",
                "row_end",
                "field_coordinates",
                "source_columns",
                "sheet_structure_hash",
                "block_ids",
                "vision_occurrence_ids",
                "vision_content_ids",
            )
            if key in metadata
        },
        "builder_schema_version": BUILDER_SCHEMA_VERSION,
        "embedding_fingerprint": embedding_fingerprint,
        "vision_strategy_fingerprint": metadata.get(
            "vision_strategy_fingerprint", "vision-disabled"
        ),
    }
    metadata.update(
        content_hash=content_hash,
        index_hash=hashlib.sha256(
            json.dumps(
                index_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        embedding_fingerprint=embedding_fingerprint,
    )


def _normalize_label(value: object) -> str:
    """只用于名称匹配的大小写和空白规范化。"""

    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _sheet_structure_hash(sheet: ExcelSheet) -> str:
    """计算 Section 模式的整 Sheet 行列结构指纹。"""

    payload = {
        "source_columns": sheet.source_columns,
        "rows": [
            {"row_number": row.row_number, "values": row.values}
            for row in sheet.rows
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _excel_column_number(column: str) -> int:
    """把 A/Z/AA 等列坐标转为自然排序整数。"""

    result = 0
    for char in column:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


__all__ = [
    "ExcelChunkBuilder",
    "ExcelConfigurationRequired",
    "PowerPointChunkBuilder",
    "PdfChunkBuilder",
    "WordChunkBuilder",
    "build_embedding_fingerprint",
    "build_excel_preview",
]
