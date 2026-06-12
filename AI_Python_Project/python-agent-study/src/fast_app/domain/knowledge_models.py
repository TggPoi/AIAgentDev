from dataclasses import dataclass, field
from typing import Any

# 表达读取到的原始 Markdown 文件
@dataclass
class MarkdownDocument:
    source_path: str
    content: str

# 表示切分后的知识片段
@dataclass
class KnowledgeChunk:
    id: str
    content: str
    source: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)