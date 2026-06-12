from dataclasses import dataclass, field
from typing import Any, Literal


RagMode = Literal["vector", "keyword", "hybrid"]


# 内部业务检索对象
@dataclass
class RetrievalFilters:
    source_path: str | None = None
    section_path: list[str] = field(default_factory=list)


@dataclass
class RetrievalOptions:
    top_k: int
    candidate_k: int
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    output_fields: list[str] = field(default_factory=list)

#内部业务对象

@dataclass
class ScoreBreakdown:
    vector_score: float | None = None
    keyword_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


@dataclass
class RetrievedDoc:
    id: str
    content: str
    score: float
    source: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieval_sources: list[str] = field(default_factory=list)
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)


@dataclass
class RagContext:
    query: str
    docs: list[RetrievedDoc]
    context_text: str