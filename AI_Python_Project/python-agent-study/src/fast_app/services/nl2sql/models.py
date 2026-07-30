from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PrivacyClassification = Literal["sensitive", "non_sensitive"]
Nl2SqlAction = Literal["query", "report"]


class DatasetDefinition(BaseModel):
    """服务端可信 Dataset 配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(description="对外稳定 Dataset ID。")
    name: str = Field(description="Dataset 中文展示名称。")
    domain: Literal["real_estate", "game"] = Field(description="业务领域。")
    database_key: str = Field(description="连接 URL 映射键；不会进入模型或 API。")
    privacy_classification: PrivacyClassification = Field(description="数据隐私等级。")
    scope_column: str = Field(description="RLS 使用的项目范围列。")
    allowed_views: tuple[str, ...] = Field(description="模型可查询的 analytics 白名单视图。")
    logical_view_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="逻辑视图名到物理 analytics 视图名的服务端映射。",
    )
    entity_tokenization_rules: tuple[str, ...] = Field(
        default_factory=tuple,
        description="敏感 Dataset 必须在本地标记化的实体类型。",
    )
    relationships: tuple[str, ...] = Field(
        default_factory=tuple,
        description="白名单视图之间可用 JOIN 的业务关系。",
    )
    synonyms: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="字段或视图对应的业务同义词。",
    )
    report_supported: bool = Field(description="是否允许进入外部模型文档报告链路。")
    enabled: bool = Field(description="当前部署是否启用该 Dataset。")


class Nl2SqlDatasetItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(description="当前用户可访问的 Dataset ID。")
    name: str = Field(description="Dataset 展示名称。")
    domain: str = Field(description="Dataset 业务领域。")
    privacy_classification: PrivacyClassification = Field(description="Dataset 隐私等级。")
    report_supported: bool = Field(description="该 Dataset 是否支持外部模型生成报告。")


class Nl2SqlQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=128, description="服务端注册的 Dataset ID。")
    question: str = Field(
        min_length=1,
        max_length=1000,
        description="要转换成只读 SQL 的自然语言问题。",
    )
    max_rows: int = Field(
        default=200,
        ge=1,
        le=500,
        description="最多返回的业务结果行数；后端会额外取一行判断是否截断。",
    )


class SqlGenerationResult(BaseModel):
    """外部 SQL 模型唯一允许输出的结构。"""

    model_config = ConfigDict(extra="forbid")

    parameterized_sql: str = Field(
        min_length=1,
        description="单条 PostgreSQL SELECT；参数使用 :name，不得包含真实数据库凭证。",
    )
    parameters: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="SQL 参数；敏感 Dataset 只能返回问题中的占位符，不得还原真实实体。",
    )
    summary_template: str = Field(
        default="查询返回 {row_count} 行结果。",
        max_length=1000,
        description="房地产仅允许 row_count 等受限字段的中文结论模板；游戏查询也可作为初始结论。",
    )


class Nl2SqlQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(description="本次 NL2SQL 查询的稳定审计 ID。")
    request_id: str | None = Field(description="关联 HTTP 请求日志的 request_id。")
    trace_id: str | None = Field(description="关联业务 trace 的 trace_id。")
    dataset_id: str = Field(description="实际查询的服务端 Dataset ID。")
    parameterized_sql: str = Field(description="通过安全策略的参数化只读 SQL。")
    columns: list[str] = Field(description="结果列名，顺序与 rows 中每行字段一致。")
    rows: list[dict[str, Any]] = Field(description="已序列化且受行数、长度限制的查询结果。")
    row_count: int = Field(description="本响应实际返回的结果行数。")
    truncated: bool = Field(description="数据库是否存在超过 max_rows 的更多结果。")
    execution_ms: int = Field(description="数据库只读事务执行耗时，单位毫秒。")
    attempt_count: int = Field(description="SQL 生成尝试次数；最多为首次加一次修复。")
    summary: str = Field(description="中文查询结论；敏感 Dataset 由本地模板回填。")
    warnings: list[str] = Field(description="截断、长文本裁剪等非致命提示。")
    markdown_table: str = Field(
        default="",
        description="后端基于结果确定性生成的 Markdown 表格，供报告证据使用。",
    )


class DatasetAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(description="已完成 RBAC 与 Grant 校验的 Dataset ID。")
    scope_ids: tuple[str, ...] = Field(description="服务端 Grant 合并出的可信项目范围。")


__all__ = [
    "DatasetAuthorization",
    "DatasetDefinition",
    "Nl2SqlAction",
    "Nl2SqlDatasetItem",
    "Nl2SqlQueryRequest",
    "Nl2SqlQueryResult",
    "PrivacyClassification",
    "SqlGenerationResult",
]
