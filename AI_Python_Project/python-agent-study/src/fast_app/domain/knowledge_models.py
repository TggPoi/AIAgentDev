from dataclasses import dataclass, field
from typing import Any, Literal

# 所有 Loader 输出共享的文档类型；Office 类型由各自 Builder 分块后复用索引设施。
DocumentType = Literal["markdown", "text", "pdf", "powerpoint", "spreadsheet"]

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


@dataclass
class LoadedPowerPointDocument:
    """PPT Loader 输出给专属 Builder 的结构化文档。"""

    source_path: str
    slides: list[PowerPointSlide]
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
