from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fast_app.schemas.rag_chat_schema import RagRetrievalFilters, RetrievalMode


EvalCaseType = Literal["answerable", "no_answer"]

# 预期命中的source
class ExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str | None = Field(
        default=None,
        description="期望命中的原始文档路径",
    )
    section_keywords: list[str] = Field(
        default_factory=list,
        description="期望命中章节路径、标题或内容中出现的关键词",
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="期望命中的 chunk id；早期评测集可以先为空",
    )

# rag评估单条case
class RagEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="评测样例唯一 id")
    case_type: EvalCaseType = Field(description="answerable 或 no_answer")
    question: str = Field(min_length=1, description="用户问题")
    mode: RetrievalMode = Field(default="hybrid", description="检索模式")
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最终参与评测的检索结果数量；Recall@K / MRR 只看前 top_k 条结果",
    )
    candidate_k: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="每个召回源先取多少候选结果；通常大于等于 top_k，用于给融合或截取前保留更多候选",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低检索分数阈值；用于模拟 /rag/chat 请求中的 min_score 过滤条件",
    )
    filters: RagRetrievalFilters = Field(
        default_factory=RagRetrievalFilters,
        description="metadata 过滤条件；用于限定 source_path 或 section_path 等检索范围",
    )
    expected_sources: list[ExpectedSource] = Field(
        default_factory=list,
        description="期望命中的来源线索；检索评测会用它判断 RetrievedDoc 是否命中正确材料",
    )
    expected_answer_keywords: list[str] = Field(
        default_factory=list,
        description="最终回答中应该出现的关键词；后续生成评测用于判断 answer 是否覆盖关键点",
    )
    forbidden_answer_keywords: list[str] = Field(
        default_factory=list,
        description="最终回答中不应该出现的关键词；常用于 no_answer 样例检查模型是否编造",
    )
    note: str = Field(default="", description="样例设计说明")

    @model_validator(mode="after")
    def validate_eval_expectations(self) -> "RagEvalCase":
        if self.case_type == "answerable" and not (
            self.expected_sources or self.expected_answer_keywords
        ):
            raise ValueError(
                "answerable 样例至少需要 expected_sources 或 expected_answer_keywords"
            )

        if self.case_type == "no_answer" and not (
            self.forbidden_answer_keywords or self.note
        ):
            raise ValueError(
                "no_answer 样例至少需要 forbidden_answer_keywords 或 note"
            )

        return self

# rag评估问题集合
class RagEvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    knowledge_base_dir: str = Field(min_length=1)
    cases: list[RagEvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> "RagEvalDataset":
        case_ids = [case.id for case in self.cases]
        duplicate_ids = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})

        if duplicate_ids:
            raise ValueError(f"评测样例 id 重复: {duplicate_ids}")

        return self
