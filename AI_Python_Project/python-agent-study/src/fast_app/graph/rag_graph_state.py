from typing import Literal, TypedDict

from fast_app.domain.rag_models import RagContext, RetrievedDoc


RagMode = Literal["vector", "keyword", "hybrid"]


class GraphRagState(TypedDict):
    query: str
    mode: RagMode
    top_k: int
    candidate_k: int | None
    min_score: float
    filters: dict[str, object]

    docs: list[RetrievedDoc]
    context: RagContext | None
    answer: str | None
