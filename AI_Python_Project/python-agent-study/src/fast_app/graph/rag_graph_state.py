from typing import Literal, NotRequired, TypedDict

from fast_app.domain.rag_models import RagContext, RetrievedDoc


RagMode = Literal["vector", "keyword", "hybrid"]
GraphRagOperation = Literal["run", "stream", "stream_events"]


class GraphRagState(TypedDict):
    query: str
    mode: RagMode
    top_k: int
    candidate_k: int | None
    min_score: float
    filters: dict[str, object]
    operation: NotRequired[GraphRagOperation]

    docs: list[RetrievedDoc]
    context: RagContext | None
    answer: str | None
