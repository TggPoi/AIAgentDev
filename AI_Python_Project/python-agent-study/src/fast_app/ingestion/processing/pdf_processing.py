"""PDF native text、embedded image 与扫描页渲染。"""

from __future__ import annotations

import math
import re
import threading
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import (
    LoadedPdfDocument,
    PdfPage,
    VisionImageContent,
    VisionImageOccurrence,
)
from fast_app.ingestion.processing.metadata_models import build_document_metadata


PDFIUM_LOCK = threading.Lock()


class PdfProcessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PdfDocumentLoader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, base_dir: str) -> list[LoadedPdfDocument]:
        root = Path(base_dir)
        return [
            self.load_structured_file(
                path, source_path=path.as_posix(), knowledge_base_dir=base_dir
            )
            for path in sorted(root.rglob("*.pdf"))
        ]

    def load_structured_file(
        self,
        path: str | Path,
        *,
        source_path: str | None = None,
        knowledge_base_dir: str | None = None,
    ) -> LoadedPdfDocument:
        file_path = Path(path)
        source = source_path or file_path.as_posix()
        reader = PdfReader(file_path)
        metadata = build_document_metadata(
            source_path=source,
            document_type="pdf",
            knowledge_base_dir=knowledge_base_dir,
        )
        doc_id = str(metadata["doc_id"])
        pages: list[PdfPage] = []
        contents: dict[str, VisionImageContent] = {}
        occurrences: list[VisionImageOccurrence] = []
        warnings: list[str] = []
        scanned_count = 0

        for page_index, page in enumerate(reader.pages):
            page_number = page_index + 1
            native_text = _normalize_visible_text(page.extract_text() or "")
            try:
                # pypdf 会列出继承自 PDF /Resources 的全部图片，其中一部分并未在
                # 当前页内容流中执行。只分析真正绘制的图片，避免把共享资源重复
                # 注入每一页正文。
                embedded_images = [
                    image
                    for image in page.images
                    if getattr(image, "is_displayed", True) is not False
                ]
            except Exception:
                embedded_images = []
                warnings.append("PDF_EMBEDDED_IMAGE_ENUMERATION_FAILED")
            scanned = len(native_text) == 0 or (
                len(native_text) < self._settings.pdf_scanned_text_threshold
                and bool(embedded_images)
            )
            page_occurrences: list[VisionImageOccurrence] = []
            page_warnings: list[str] = []
            if scanned:
                scanned_count += 1
                if scanned_count > self._settings.vision_max_scanned_pages:
                    raise PdfProcessingError(
                        "PDF_SCANNED_PAGE_LIMIT_EXCEEDED", "扫描候选页数量超过限制"
                    )
                raw = _render_pdf_page(
                    file_path,
                    page_index,
                    configured_scale=self._settings.pdf_render_scale,
                    min_scale=self._settings.pdf_min_render_scale,
                    max_pixels=self._settings.vision_max_image_pixels,
                )
                content = VisionImageContent.from_raw(
                    raw,
                    media_type="image/png",
                    max_bytes=self._settings.vision_max_image_bytes,
                    max_pixels=self._settings.vision_max_image_pixels,
                )
                contents.setdefault(content.content_id, content)
                page_occurrences.append(
                    VisionImageOccurrence(
                        occurrence_id=f"imgocc:pdf:{doc_id}:page:{page_number}:scanned",
                        content_id=content.content_id,
                        source_locator=f"page[{page_number}]/render",
                        page_or_slide_number=page_number,
                        anchor_id=f"page:{page_number}",
                        occurrence_index=1,
                    )
                )
            else:
                for ordinal, image in enumerate(embedded_images, start=1):
                    try:
                        content = VisionImageContent.from_raw(
                            bytes(image.data),
                            media_type="application/octet-stream",
                            max_bytes=self._settings.vision_max_image_bytes,
                            max_pixels=self._settings.vision_max_image_pixels,
                        )
                    except Exception:
                        page_warnings.append("PDF_EMBEDDED_IMAGE_EXTRACTION_FAILED")
                        continue
                    contents.setdefault(content.content_id, content)
                    page_occurrences.append(
                        VisionImageOccurrence(
                            occurrence_id=(
                                f"imgocc:pdf:{doc_id}:page:{page_number}:embedded:"
                                f"{ordinal}:{content.content_id}"
                            ),
                            content_id=content.content_id,
                            source_locator=f"page[{page_number}]/embedded[{ordinal}]",
                            page_or_slide_number=page_number,
                            anchor_id=str(getattr(image, "name", "") or ordinal),
                            occurrence_index=ordinal,
                        )
                    )
            occurrences.extend(page_occurrences)
            pages.append(
                PdfPage(
                    page_number=page_number,
                    native_text=native_text,
                    scanned_candidate=scanned,
                    vision_occurrence_ids=tuple(
                        item.occurrence_id for item in page_occurrences
                    ),
                    warnings=tuple(sorted(set(page_warnings))),
                )
            )
        metadata.update(
            page_count=len(pages),
            scanned_candidate_count=scanned_count,
            image_occurrence_count=len(occurrences),
            extraction_warnings=sorted(set(warnings)),
        )
        return LoadedPdfDocument(
            source_path=source,
            pages=pages,
            vision_contents=contents,
            vision_occurrences=occurrences,
            warnings=sorted(set(warnings)),
            metadata=metadata,
        )


def _render_pdf_page(
    path: Path,
    page_index: int,
    *,
    configured_scale: float,
    min_scale: float,
    max_pixels: int,
) -> bytes:
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(path)
        page = None
        bitmap = None
        try:
            page = document[page_index]
            width, height = page.get_size()
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                raise PdfProcessingError(
                    "PDF_RENDER_PIXEL_BUDGET_EXCEEDED", "PDF 页面尺寸非法"
                )
            allowed_scale = math.sqrt(max_pixels / (width * height))
            scale = min(configured_scale, allowed_scale)
            if scale < min_scale or math.ceil(width * scale) * math.ceil(height * scale) > max_pixels:
                raise PdfProcessingError(
                    "PDF_RENDER_PIXEL_BUDGET_EXCEEDED", "PDF 页面无法在像素预算内安全渲染"
                )
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
        finally:
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()
            document.close()


def _normalize_visible_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


__all__ = ["PDFIUM_LOCK", "PdfDocumentLoader", "PdfProcessingError"]
