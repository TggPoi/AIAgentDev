from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RetrievalMode = Literal["vector", "keyword", "hybrid"]



class RagChatRequest(BaseModel):
    # 禁止客户端传入未声明字段
    model_config = ConfigDict(extra="forbid")

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

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()

        if normalized == "":
            raise ValueError("query 不能只包含空白字符")

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
    score: float = Field(description="当前最终排序分数")
    scores: RagScoreBreakdown = Field(description="多阶段分数明细")
    content_preview: str = Field(description="命中文档内容预览")

# 最终检索结果
class RagChatResponse(BaseModel):
    query: str
    answer: str
    sources: list[RagSource]


