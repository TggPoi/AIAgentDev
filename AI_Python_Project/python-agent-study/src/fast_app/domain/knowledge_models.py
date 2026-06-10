from dataclasses import dataclass, field
from typing import Any


@dataclass
class KnowledgeChunk:
    id: str
    content: str
    source: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)