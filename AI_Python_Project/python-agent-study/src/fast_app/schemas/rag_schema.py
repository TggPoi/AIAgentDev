from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RetrievalMode = Literal["vector", "keyword", "hybrid"]


class SearchRequest(BaseModel):
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
    id: str
    content: str
    score: float = Field(ge=0.0, le=1.0)
    source: str


class SearchResponse(BaseModel):
    query: str
    mode: RetrievalMode
    documents: list[RetrievedDocument] = Field(default_factory=list)