from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


RetrievalMode = Literal["vector", "keyword", "hybrid"]

# 检索过滤
class RagRetrievalFilters(BaseModel):
    source_path: str | None = Field(default=None, description="限定检索的原始文档路径")
    section_path: list[str] = Field(default_factory=list, description="限定检索的章节路径")

class RagChatRequest(BaseModel):
    # 禁止客户端传入未声明字段
    model_config = ConfigDict(extra="forbid")
    # 这两个字段只给服务端内部使用，不会进入 OpenAPI schema，也不能由请求体传入。
    # 阶段 14-9 用它承载认证层解析出的用户上下文，避免把 user_id 暴露成客户端可伪造字段。
    _current_user_id: str | None = PrivateAttr(default=None)
    _external_session_id: str | None = PrivateAttr(default=None)

    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="多轮对话会话 ID；为空时按单轮请求处理",
    )

    # 用户问题
    query: str = Field(
        min_length=1,
        max_length=500,
        description="用户问题",
    )

    # 检索模式
    mode: RetrievalMode = Field(
        default="hybrid",
        description="检索模式：vector / keyword / hybrid",
    )

    # 最多使用多少个文档
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最多返回文档数量",
    )

    # 最低分数阈值
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低文档分数",
    )

    candidate_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="每个召回源先取多少候选文档；为空时使用 top_k",
    )

    filters: RagRetrievalFilters = Field(
        default_factory=RagRetrievalFilters,
        description="metadata 过滤条件",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()

        if normalized == "":
            raise ValueError("query 不能只包含空白字符")

        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if normalized == "":
            raise ValueError("session_id 不能只包含空白字符")

        return normalized

# 不同检索阶段分数拆解
class RagScoreBreakdown(BaseModel):
    vector_score: float | None = Field(default=None, description="Milvus 向量检索原始分数")
    keyword_score: float | None = Field(default=None, description="ElasticSearch 关键词检索原始分数")
    rrf_score: float | None = Field(default=None, description="RRF 融合分数")
    rerank_score: float | None = Field(default=None, description="Rerank 精排分数")

# 检索来源
class RagSource(BaseModel):
    id: str = Field(description="命中的 chunk id")
    source: str = Field(description="检索来源，例如 milvus / elasticsearch")
    retrieval_sources: list[str] = Field(
        default_factory=list,
        description="实际命中过该 chunk 的召回来源列表",
    )
    title: str | None = Field(default=None, description="命中 chunk 所属标题")
    section_path: list[str] = Field(default_factory=list, description="命中 chunk 所属标题路径")
    metadata: dict[str, Any] = Field(default_factory=dict, description="命中 chunk 的结构化 metadata")
    score: float = Field(description="当前最终排序分数")
    scores: RagScoreBreakdown = Field(description="多阶段分数明细")
    content_preview: str = Field(description="命中文档内容预览")
    
# 最终检索结果
class RagChatResponse(BaseModel):
    request_id: str | None = Field(
        default=None,
        description="本次请求的 request_id，用于和后端日志对齐",
    )
    trace_id: str | None = Field(
        default=None,
        description="本次请求的 trace_id，当前阶段默认与 request_id 相同",
    )
    query: str
    answer: str
    sources: list[RagSource]


