from dataclasses import dataclass

# `RetrievedDoc` 和 `RagContext` 是内部业务对象

@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str


@dataclass
class RagContext:
    text: str
    docs: list[RetrievedDoc]