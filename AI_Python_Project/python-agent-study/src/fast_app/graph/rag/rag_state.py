from typing import TypedDict

from fast_app.domain.rag_models import RagContext, RetrievedDoc

#  `RagState` 模拟后面 LangGraph 的 State

class RagState(TypedDict):
    query: str
    docs: list[RetrievedDoc]
    context: RagContext | None
    answer: str | None