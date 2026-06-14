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
    top_k: int = Field(default=5, ge=1, le=20, description="返回文档数量")
    candidate_k: int | None = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filters: RagRetrievalFilters = Field(default_factory=RagRetrievalFilters)
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    expected_answer_keywords: list[str] = Field(default_factory=list)
    forbidden_answer_keywords: list[str] = Field(default_factory=list)
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
