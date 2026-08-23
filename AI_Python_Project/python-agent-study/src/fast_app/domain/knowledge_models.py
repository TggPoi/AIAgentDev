from dataclasses import dataclass, field
import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 所有 Loader 输出共享的文档类型；Office 类型由各自 Builder 分块后复用索引设施。
DocumentType = Literal["markdown", "text", "pdf", "powerpoint", "spreadsheet", "word"]


class VisionImageContent(BaseModel):
    """只在文档处理进程内存在的标准化图片内容。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content_id: str = Field(description="图片内容的稳定身份，由原始图片字节 SHA256 构造。")
    sha256: str = Field(description="原始图片字节的十六进制 SHA256。")
    media_type: str = Field(description="标准化图片的 MIME 类型。")
    normalized_bytes: bytes = Field(
        exclude=True,
        repr=False,
        description="仅在当前 Worker 内存中使用的标准化图片字节，禁止持久化或公开。",
    )
    width: int = Field(gt=0, description="标准化图片宽度像素数。")
    height: int = Field(gt=0, description="标准化图片高度像素数。")

    @classmethod
    def from_raw(
        cls,
        raw: bytes,
        *,
        media_type: str,
        max_bytes: int | None = None,
        max_pixels: int | None = None,
    ) -> "VisionImageContent":
        """校验并规范化 raster 图片，同时保留原始内容身份。"""

        from io import BytesIO

        from PIL import Image

        if max_bytes is not None and len(raw) > max_bytes:
            raise ValueError("VISION_IMAGE_BYTES_EXCEEDED")
        digest = hashlib.sha256(raw).hexdigest()
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            if max_pixels is not None and width * height > max_pixels:
                raise ValueError("VISION_IMAGE_PIXELS_EXCEEDED")
            image.load()
            normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = BytesIO()
            normalized.save(output, format="PNG", optimize=True)
            width, height = normalized.size
        normalized_bytes = output.getvalue()
        if max_bytes is not None and len(normalized_bytes) > max_bytes:
            raise ValueError("VISION_IMAGE_BYTES_EXCEEDED")
        return cls(
            content_id=f"img:{digest}",
            sha256=digest,
            media_type="image/png",
            normalized_bytes=normalized_bytes,
            width=width,
            height=height,
        )


class VisionImageOccurrence(BaseModel):
    """图片内容在文档结构中的一个稳定出现位置。"""

    occurrence_id: str = Field(description="由文档、结构位置和内容身份组成的稳定出现位置 ID。")
    content_id: str = Field(description="关联 VisionImageContent.content_id。")
    source_locator: str = Field(description="格式专用且可审计的出现位置，例如 slide/shape 或 body/paragraph。")
    page_or_slide_number: int | None = Field(
        default=None, ge=1, description="PDF 页码或 PPT 页码；DOCX 等无可靠页码格式为 null。"
    )
    anchor_id: str | None = Field(default=None, description="格式原生的稳定锚点 ID；不存在时为 null。")
    block_id: str | None = Field(default=None, description="DOCX 等块结构中的稳定 block ID；不适用时为 null。")
    relationship_id: str | None = Field(default=None, description="OOXML 图片 relationship ID；不适用时为 null。")
    occurrence_index: int = Field(ge=1, description="同一结构位置中的一基出现序号。")


class VisionAnalysisResult(BaseModel):
    """Vision LLM 的结构化、可确定性渲染结果。"""

    extracted_text: str = Field(description="图片中可可靠读取的文字；没有时为空字符串。")
    summary: str = Field(description="图片与所属文档块相关的简短语义摘要。")
    table_markdown: str | None = Field(
        default=None, description="图片包含表格时的 Markdown；不包含表格时为 null。"
    )
    visual_facts: list[str] = Field(
        default_factory=list, description="从图形关系、流程或布局中读取的可核验事实。"
    )

# 表达读取到的原始 文档
@dataclass
class LoadedDocument:
    # 原始文档路径，用于 metadata、日志和后续 chunk 溯源。
    source_path: str
    # 原始文档完整内容，尚未经过 chunk 切分。
    content: str
    # 文档类型，决定后续使用哪类 loader / parser 处理。
    document_type: DocumentType
    # 文档级 metadata，例如 source_path、标题、部门权限信息。
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PowerPointSlide:
    """PPT 中一个具备稳定 slide_id 的可检索页面。"""

    slide_id: int
    slide_number: int
    title: str
    content: str
    notes: str = ""
    warnings: tuple[str, ...] = ()
    vision_occurrence_ids: tuple[str, ...] = ()


@dataclass
class LoadedPowerPointDocument:
    """PPT Loader 输出给专属 Builder 的结构化文档。"""

    source_path: str
    slides: list[PowerPointSlide]
    vision_contents: dict[str, VisionImageContent] = field(default_factory=dict)
    vision_occurrences: list[VisionImageOccurrence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WordBlock:
    """DOCX 正文顺序中的一个可独立装箱块。"""

    block_id: str
    block_type: str
    section_id: str
    section_title: str
    heading_level: int
    text: str
    vision_occurrence_ids: tuple[str, ...] = ()


@dataclass
class LoadedWordDocument:
    source_path: str
    blocks: list[WordBlock]
    vision_contents: dict[str, VisionImageContent] = field(default_factory=dict)
    vision_occurrences: list[VisionImageOccurrence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfPage:
    page_number: int
    native_text: str
    scanned_candidate: bool
    vision_occurrence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class LoadedPdfDocument:
    source_path: str
    pages: list[PdfPage]
    vision_contents: dict[str, VisionImageContent] = field(default_factory=dict)
    vision_occurrences: list[VisionImageOccurrence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcelFieldValue:
    """一个字段的检索值、公式/缓存和当前物理来源位置。"""

    value: str
    formula: str | None
    cached_value: str | None
    source_column: str
    source_coordinate: str


@dataclass(frozen=True)
class ExcelRow:
    """保留原始行号和 A/B/C 坐标值的 Excel 非空行。"""

    row_number: int
    values: dict[str, str]
    cells: dict[str, ExcelFieldValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcelRecord:
    """Profile 映射后具有稳定 Sheet、行和字段身份的一条业务记录。"""

    sheet_key: str
    row_identity: str
    row_number: int
    fields: dict[str, ExcelFieldValue]


@dataclass(frozen=True)
class ExcelSheet:
    """一个可见工作表及其非空行和首行表头提示。"""

    name: str
    rows: list[ExcelRow]
    business_header_hint: dict[str, str]
    # 保留工作表当前物理列范围，才能区分“插入空列”和“根本没有该列”。
    source_columns: list[str] = field(default_factory=list)


@dataclass
class LoadedExcelDocument:
    """Excel Loader 输出给 Record/Section Builder 的结构化文档。"""

    source_path: str
    sheets: list[ExcelSheet]
    metadata: dict[str, Any] = field(default_factory=dict)

# MarkdownDocument 作为过渡别名，避免一次性大范围改动
MarkdownDocument = LoadedDocument

# 表示切分后的知识片段
@dataclass
class KnowledgeChunk:
    # chunk 唯一 ID，用于 ES / Milvus 写入和检索返回。
    id: str
    # chunk 文本内容，是 embedding 和关键词索引的主体。
    content: str
    # chunk 来源文档路径或来源标识。
    source: str
    # chunk 所属标题，供 sources 展示和调试使用。
    title: str
    # chunk 级 metadata，例如 section_path、doc_id、department_codes。
    metadata: dict[str, Any] = field(default_factory=dict)
    # Markdown 父子分块使用的检索文本；为空时继续以 content 作为索引和向量化输入。
    # Office/TXT Builder 不设置该字段，因此其既有行为保持不变。
    search_text: str | None = None
