from typing import Any, Literal

from pydantic import BaseModel, Field

from fast_app.schemas.rag_chat_schema import RagScoreBreakdown


class DebugTraceRequestSnapshot(BaseModel):
    query: str = Field(description="debug trace 对应的原始或改写后 query。")
    mode: str = Field(description="本次请求使用的检索模式。")
    top_k: int = Field(description="最终返回来源数量上限。")
    candidate_k: int | None = Field(description="每个召回源先取的候选数量；为空时按 top_k。")
    min_score: float = Field(description="过滤低分文档的最低分数阈值。")
    filters: dict[str, Any] = Field(description="本次请求使用的检索过滤条件。")


class DebugTraceRuntimeSnapshot(BaseModel):
    pipeline_provider: str = Field(description="本次请求使用的 pipeline provider。")
    llm_provider: str = Field(description="本次请求使用的 LLM provider。")
    llm_model_name: str = Field(description="本次请求使用的 LLM 模型名。")
    vector_retriever_provider: str = Field(description="向量检索组件 provider。")
    keyword_retriever_provider: str = Field(description="关键词检索组件 provider。")
    reranker_provider: str = Field(description="rerank 组件 provider。")
    rerank_model_name: str = Field(description="rerank 模型名。")
    langsmith_project: str = Field(description="当前 LangSmith project 配置。")


class DebugTraceSourceSnapshot(BaseModel):
    id: str = Field(description="命中 chunk ID。")
    source: str = Field(description="主要检索来源，例如 milvus / elasticsearch。")
    retrieval_sources: list[str] = Field(description="实际命中过该 chunk 的召回来源列表。")
    title: str | None = Field(description="命中 chunk 所属标题。")
    section_path: list[str] = Field(description="命中 chunk 所属章节路径。")
    score: float = Field(description="当前最终排序分数。")
    scores: RagScoreBreakdown = Field(description="多阶段检索和排序分数明细。")
    metadata: dict[str, Any] = Field(description="命中 chunk 的结构化 metadata。")
    content_preview: str = Field(description="命中内容预览。")


class DebugTraceErrorSnapshot(BaseModel):
    code: str = Field(description="内部错误 code。")
    message: str = Field(description="面向 debug 调用方展示的错误信息。")
    error_category: str = Field(description="错误分类，例如 validation / provider / unexpected。")
    error_type: str = Field(description="Python 异常类型名或业务错误类型。")


class RagDebugTraceResponse(BaseModel):
    status: Literal["success", "failed"] = Field(description="debug trace 执行状态。")
    request_id: str | None = Field(description="本次请求的 request_id。")
    trace_id: str | None = Field(description="本次请求的 trace_id。")
    request: DebugTraceRequestSnapshot = Field(description="请求参数快照。")
    runtime: DebugTraceRuntimeSnapshot = Field(description="运行时 provider 和模型配置快照。")
    latency_ms: float | None = Field(default=None, description="本次请求总耗时，单位毫秒。")
    answer_length: int | None = Field(default=None, description="回答文本长度；失败时可为空。")
    source_count: int = Field(default=0, description="本次请求返回的 sources 数量。")
    sources: list[DebugTraceSourceSnapshot] = Field(default_factory=list, description="检索来源快照列表。")
    error: DebugTraceErrorSnapshot | None = Field(default=None, description="失败时的错误快照；成功时为空。")
