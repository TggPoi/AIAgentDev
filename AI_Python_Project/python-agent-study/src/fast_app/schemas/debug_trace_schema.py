from typing import Any, Literal

from pydantic import BaseModel, Field

from fast_app.schemas.rag_chat_schema import RagScoreBreakdown


class DebugTraceRequestSnapshot(BaseModel):
    query: str
    mode: str
    top_k: int
    candidate_k: int | None
    min_score: float
    filters: dict[str, Any]


class DebugTraceRuntimeSnapshot(BaseModel):
    pipeline_provider: str
    llm_provider: str
    llm_model_name: str
    vector_retriever_provider: str
    keyword_retriever_provider: str
    reranker_provider: str
    rerank_model_name: str
    langsmith_project: str


class DebugTraceSourceSnapshot(BaseModel):
    id: str
    source: str
    retrieval_sources: list[str]
    title: str | None
    section_path: list[str]
    score: float
    scores: RagScoreBreakdown
    metadata: dict[str, Any]
    content_preview: str


class DebugTraceErrorSnapshot(BaseModel):
    code: str
    message: str
    error_category: str
    error_type: str


class RagDebugTraceResponse(BaseModel):
    status: Literal["success", "failed"]
    request_id: str | None
    trace_id: str | None
    request: DebugTraceRequestSnapshot
    runtime: DebugTraceRuntimeSnapshot
    answer_length: int | None = None
    source_count: int = 0
    sources: list[DebugTraceSourceSnapshot] = Field(default_factory=list)
    error: DebugTraceErrorSnapshot | None = None
