from dataclasses import dataclass, field
from typing import Any, Literal

# 支持三种文件类型
DocumentType = Literal["markdown", "text", "pdf"]

# 表达读取到的原始 文档
@dataclass
class LoadedDocument:
    source_path: str
    content: str
    document_type: DocumentType
    metadata: dict[str, Any] = field(default_factory=dict)

# MarkdownDocument 作为过渡别名，避免一次性大范围改动
MarkdownDocument = LoadedDocument

# 表示切分后的知识片段
@dataclass
class KnowledgeChunk:
    id: str
    content: str
    source: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)