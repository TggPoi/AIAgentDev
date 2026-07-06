from dataclasses import dataclass, field
from typing import Any, Literal

# 支持三种文件类型
DocumentType = Literal["markdown", "text", "pdf"]

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
