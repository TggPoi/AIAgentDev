from dataclasses import dataclass, field
from typing import Any, Literal


RagMode = Literal["vector", "keyword", "hybrid"]


# 内部业务检索对象
@dataclass
class RetrievalFilters:
    # 限定检索的原始文档路径；为空表示不按来源文件过滤。
    source_path: str | None = None
    # 限定检索的章节路径；为空表示不按章节过滤。
    section_path: list[str] = field(default_factory=list)
    # 是否允许读取全部文档；管理员或高权限用户可设为 true。
    can_read_all: bool = False
    # 当前检索用户 ID，用于私有文档过滤或审计扩展。
    user_id: str | None = None
    # 当前用户可读取的部门 code 列表，用于部门级 ACL 过滤。
    department_codes: list[str] = field(default_factory=list)
    # 是否允许读取公共文档。
    allow_public: bool = True


@dataclass
class RetrievalOptions:
    # 最终返回给上游的文档数量。
    top_k: int
    # 每个召回源或融合前先取的候选数量。
    candidate_k: int
    # 检索过滤条件，包含来源、章节和权限范围。
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    # 底层检索引擎需要返回的额外字段名。
    output_fields: list[str] = field(default_factory=list)

#内部业务对象

@dataclass
class ScoreBreakdown:
    # Milvus 向量检索原始分数。
    vector_score: float | None = None
    # ElasticSearch 关键词检索原始分数。
    keyword_score: float | None = None
    # RRF 融合后的分数。
    rrf_score: float | None = None
    # Rerank 精排后的分数。
    rerank_score: float | None = None


@dataclass
class RetrievedDoc:
    # 命中的 chunk ID。
    id: str
    # 命中 chunk 的完整文本内容。
    content: str
    # 当前阶段用于排序的最终分数。
    score: float
    # 主要检索来源，例如 milvus 或 elasticsearch。
    source: str
    # chunk 所属标题，可能为空。
    title: str | None = None
    # chunk 结构化 metadata，例如 source_path、section_path、department_codes。
    metadata: dict[str, Any] = field(default_factory=dict)
    # 实际命中过该 chunk 的召回来源列表。
    retrieval_sources: list[str] = field(default_factory=list)
    # 多阶段检索和排序分数明细。
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)


@dataclass
class RagContext:
    # 实际用于构建上下文的 query，可能是多轮改写后的问题。
    query: str
    # 参与回答构建的检索文档列表。
    docs: list[RetrievedDoc]
    # 拼接后传给 LLM 的上下文文本。
    context_text: str
