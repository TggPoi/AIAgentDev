from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RetrievalMode = Literal["vector", "keyword", "hybrid"]


class SearchRequest(BaseModel):
    # 禁止客户端传入未声明字段，保持检索 demo 接口参数可控。
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=500,
        description="检索问题",
    )

    mode: RetrievalMode = Field(
        default="hybrid",
        description="检索模式",
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="返回文档数量",
    )

    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低分数",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()

        if value == "":
            raise ValueError("query 不能只包含空白字符")

        return value


class RetrievedDocument(BaseModel):
    id: str = Field(description="命中文档或 chunk ID。")
    content: str = Field(description="命中文档内容。")
    score: float = Field(ge=0.0, le=1.0, description="命中文档相关性分数。")
    source: str = Field(description="命中文档来源。")


class SearchResponse(BaseModel):
    query: str = Field(description="实际执行的检索问题。")
    mode: RetrievalMode = Field(description="本次请求使用的检索模式。")
    documents: list[RetrievedDocument] = Field(default_factory=list, description="检索命中文档列表。")
