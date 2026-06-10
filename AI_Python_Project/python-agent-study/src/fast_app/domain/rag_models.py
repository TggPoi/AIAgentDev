from dataclasses import dataclass

from typing import Literal

# `RetrievedDoc` 和 `RagContext` 是内部业务对象

RagMode = Literal["vector", "keyword", "hybrid"]

@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str


@dataclass
class RagContext:
    query: str
    docs: list[RetrievedDoc]
    context_text: str