"""DOCX block-aware 文本与图片 occurrence 提取。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from fast_app.domain.knowledge_models import (
    LoadedWordDocument,
    VisionImageContent,
    VisionImageOccurrence,
    WordBlock,
)
from fast_app.ingestion.processing.metadata_models import build_document_metadata


_W14_PARA_ID = qn("w14:paraId")
_R_EMBED = qn("r:embed")
_R_LINK = qn("r:link")


class WordDocumentLoader:
    """保留 DOCX block 顺序、稳定身份和 inline image 位置。"""

    def __init__(
        self,
        *,
        max_image_bytes: int | None = None,
        max_image_pixels: int | None = None,
    ) -> None:
        self._max_image_bytes = max_image_bytes
        self._max_image_pixels = max_image_pixels

    def load(self, base_dir: str) -> list[LoadedWordDocument]:
        root = Path(base_dir)
        return [
            self.load_structured_file(
                path, source_path=path.as_posix(), knowledge_base_dir=base_dir
            )
            for path in sorted(root.rglob("*.docx"))
        ]

    def load_structured_file(
        self,
        path: str | Path,
        *,
        source_path: str | None = None,
        knowledge_base_dir: str | None = None,
    ) -> LoadedWordDocument:
        file_path = Path(path)
        source = source_path or file_path.as_posix()
        document = Document(file_path)
        metadata = build_document_metadata(
            source_path=source,
            document_type="word",
            knowledge_base_dir=knowledge_base_dir,
        )
        doc_id = str(metadata["doc_id"])
        blocks: list[WordBlock] = []
        contents: dict[str, VisionImageContent] = {}
        occurrences: list[VisionImageOccurrence] = []
        warnings: list[str] = []
        duplicate_counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
        heading_counts: defaultdict[tuple[str, int, str], int] = defaultdict(int)
        current_section_id = "docx:section:root"
        current_section_title = Path(source).stem
        current_heading_level = 0
        section_stack: list[tuple[int, str, str]] = []

        for item in _iter_body_blocks(document):
            if isinstance(item, Paragraph):
                text = _normalize_text(item.text)
                heading_level = _heading_level(item)
                if heading_level is not None:
                    while section_stack and section_stack[-1][0] >= heading_level:
                        section_stack.pop()
                    parent_id = section_stack[-1][1] if section_stack else "docx:section:root"
                    key = (parent_id, heading_level, text.casefold())
                    heading_counts[key] += 1
                    current_section_id = _paragraph_native_id(item) or _stable_id(
                        "docx:section:fallback",
                        parent_id,
                        str(heading_level),
                        text.casefold(),
                        str(heading_counts[key]),
                    )
                    current_section_title = text or current_section_title
                    current_heading_level = heading_level
                    section_stack.append(
                        (heading_level, current_section_id, current_section_title)
                    )
                    block_type = "heading"
                else:
                    block_type = "list" if _is_list_paragraph(item) else "paragraph"
                block_id = _block_id(
                    item,
                    block_type=block_type,
                    section_id=current_section_id,
                    text=text,
                    duplicate_counts=duplicate_counts,
                )
                block_occurrences = _extract_blips(
                    item._p,
                    part=item.part,
                    doc_id=doc_id,
                    block_id=block_id,
                    locator=f"body/{block_type}[{block_id}]",
                    contents=contents,
                    warnings=warnings,
                    max_image_bytes=self._max_image_bytes,
                    max_image_pixels=self._max_image_pixels,
                )
            else:
                text = _table_markdown(item)
                canonical = json.dumps(
                    [[_normalize_text(cell.text) for cell in row.cells] for row in item.rows],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                duplicate_key = (current_section_id, "table", canonical)
                duplicate_counts[duplicate_key] += 1
                block_id = _stable_id(
                    "docx:block:table",
                    current_section_id,
                    hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    str(duplicate_counts[duplicate_key]),
                )
                block_type = "table"
                block_occurrences = _extract_blips(
                    item._tbl,
                    part=item.part,
                    doc_id=doc_id,
                    block_id=block_id,
                    locator=f"body/table[{block_id}]",
                    contents=contents,
                    warnings=warnings,
                    max_image_bytes=self._max_image_bytes,
                    max_image_pixels=self._max_image_pixels,
                )
            occurrences.extend(block_occurrences)
            blocks.append(
                WordBlock(
                    block_id=block_id,
                    block_type=block_type,
                    section_id=current_section_id,
                    section_title=current_section_title,
                    heading_level=current_heading_level,
                    text=text,
                    vision_occurrence_ids=tuple(
                        occurrence.occurrence_id for occurrence in block_occurrences
                    ),
                )
            )

        metadata.update(
            block_count=len(blocks),
            image_occurrence_count=len(occurrences),
            extraction_warnings=sorted(set(warnings)),
            unsupported_scopes=[
                "header_footer",
                "textbox",
                "footnote_endnote",
                "comments_drawing_canvas",
            ],
        )
        return LoadedWordDocument(
            source_path=source,
            blocks=blocks,
            vision_contents=contents,
            vision_occurrences=occurrences,
            warnings=sorted(set(warnings)),
            metadata=metadata,
        )


def _iter_body_blocks(document: DocxDocument) -> Iterable[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int | None:
    name = str(getattr(paragraph.style, "name", "") or "")
    match = re.match(r"Heading\s+(\d+)$", name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _is_list_paragraph(paragraph: Paragraph) -> bool:
    properties = paragraph._p.pPr
    return bool(properties is not None and properties.numPr is not None)


def _paragraph_native_id(paragraph: Paragraph) -> str | None:
    value = paragraph._p.get(_W14_PARA_ID)
    return f"docx:para:{value.lower()}" if value else None


def _block_id(
    paragraph: Paragraph,
    *,
    block_type: str,
    section_id: str,
    text: str,
    duplicate_counts: defaultdict[tuple[str, str, str], int],
) -> str:
    native = _paragraph_native_id(paragraph)
    if native:
        return native
    key = (section_id, block_type, text.casefold())
    duplicate_counts[key] += 1
    return _stable_id(
        f"docx:block:{block_type}",
        section_id,
        hashlib.sha256(text.casefold().encode("utf-8")).hexdigest(),
        str(duplicate_counts[key]),
    )


def _extract_blips(
    element,
    *,
    part,
    doc_id: str,
    block_id: str,
    locator: str,
    contents: dict[str, VisionImageContent],
    warnings: list[str],
    max_image_bytes: int | None,
    max_image_pixels: int | None,
) -> list[VisionImageOccurrence]:
    result: list[VisionImageOccurrence] = []
    for ordinal, blip in enumerate(element.xpath(".//a:blip"), start=1):
        relationship_id = blip.get(_R_EMBED)
        external_id = blip.get(_R_LINK)
        if external_id:
            warnings.append("DOCX_EXTERNAL_IMAGE_SKIPPED")
            continue
        relationship = part.rels.get(relationship_id) if relationship_id else None
        if relationship is None or relationship.is_external:
            warnings.append("DOCX_EXTERNAL_IMAGE_SKIPPED")
            continue
        try:
            content = VisionImageContent.from_raw(
                bytes(relationship.target_part.blob),
                media_type="application/octet-stream",
                max_bytes=max_image_bytes,
                max_pixels=max_image_pixels,
            )
        except Exception:
            warnings.append("DOCX_IMAGE_EXTRACTION_FAILED")
            continue
        contents.setdefault(content.content_id, content)
        occurrence_id = (
            f"imgocc:docx:{doc_id}:{block_id}:{relationship_id}:{ordinal}:"
            f"{content.content_id}"
        )
        result.append(
            VisionImageOccurrence(
                occurrence_id=occurrence_id,
                content_id=content.content_id,
                source_locator=f"{locator}/image[{ordinal}]",
                block_id=block_id,
                relationship_id=relationship_id,
                occurrence_index=ordinal,
            )
        )
    return result


def _table_markdown(table: Table) -> str:
    rows = [[_normalize_text(cell.text).replace("|", "\\|") for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    return "\n".join(
        [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
            *("| " + " | ".join(row) + " |" for row in rows[1:]),
        ]
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


__all__ = ["WordDocumentLoader"]
