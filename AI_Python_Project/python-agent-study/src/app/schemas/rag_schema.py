# Pydantic：外部请求 / 响应模型

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 检索模式只能是三种之一
RetrievalMode = Literal["vector", "keyword", "hybrid"]


class RagRequest(BaseModel):
    # 禁止外部传入模型未声明的字段
    # 例如传入 debug=True 会直接校验失败
    model_config = ConfigDict(extra="forbid")

    # 用户问题
    # min_length=1 只能拦截空字符串 ""
    # 后面 field_validator 会进一步拦截全空格字符串 "   "
    query: str = Field(
        min_length=1,
        max_length=500,
        description="用户问题",
    )

    # 检索模式
    # vector：只走向量召回
    # keyword：只走关键词召回
    # hybrid：Milvus + ES 并发召回
    mode: RetrievalMode = Field(
        default="hybrid",
        description="检索模式",
    )

    # 最多返回多少个文档
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="返回文档数量",
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
        # 去掉用户输入首尾空格
        normalized = value.strip()

        # 防止 query="   " 这种无意义输入
        if normalized == "":
            raise ValueError("query 不能只包含空白字符")

        # 返回值会成为模型中最终保存的 query
        return normalized


class RagResponse(BaseModel):
    # 原始问题
    query: str

    # 最终回答
    answer: str

    # 使用到的文档 ID
    sources: list[str] = Field(default_factory=list)