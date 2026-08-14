from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fast_app.schemas.rag_chat_schema import RagRetrievalFilters, RetrievalMode


EVAL_DATASET_SCHEMA_VERSION = "2.0"

EvalCaseType = Literal["answerable", "no_answer"]
EvalMetricProfile = Literal["rag"]
EvalExpectedRoute = Literal["rag_answer", "rag_no_answer"]
EvalRetrievalRelevanceUnit = Literal["logical_chunk", "logical_parent"]
EvalScenarioTag = Literal[
    "answerable",
    "unanswerable",
    "permission_filter",
    "parent_expansion",
    "multiple_relevant_sources",
    "no_result",
    "underfilled_k",
]
EvalAnnotationMethod = Literal["human", "model_assisted", "legacy_migration"]
EvalReviewStatus = Literal["pending_review", "approved", "rejected"]
EvalDatasetLifecycle = Literal["candidate", "golden"]

REQUIRED_GOLDEN_SCENARIOS: frozenset[EvalScenarioTag] = frozenset(
    {
        "answerable",
        "unanswerable",
        "permission_filter",
        "parent_expansion",
        "multiple_relevant_sources",
        "no_result",
        "underfilled_k",
    }
)


class EvalRetrievalFilters(RagRetrievalFilters):
    """Eval case 可声明的非安全性内容过滤器。"""

    model_config = ConfigDict(extra="forbid")


class ExpectedSource(BaseModel):
    """一个经过审核、可用逻辑身份追溯的相关来源。"""

    model_config = ConfigDict(extra="forbid")

    logical_doc_id: str = Field(
        min_length=1,
        description="跨知识版本稳定的逻辑文档 ID；用于文档级相关性诊断。",
    )
    source_revision: str = Field(
        min_length=1,
        description="该来源文档的不可变 Git commit 或等价 revision；多来源 case 可分别绑定不同修订。",
    )
    logical_chunk_ids: list[str] = Field(
        min_length=1,
        description="该来源中与问题相关的逻辑子块 ID；不得写入版本化物理记录 ID。",
    )
    logical_parent_id: str | None = Field(
        default=None,
        min_length=1,
        description="父块扩展场景的稳定逻辑父块 ID；普通子块来源为空。",
    )
    matched_logical_child_ids: list[str] = Field(
        default_factory=list,
        description="父块被采用时实际支撑命中的逻辑子块 ID；必须属于 logical_chunk_ids。",
    )
    source_path: str = Field(
        min_length=1,
        description="人工审核时使用的来源路径；只用于追溯，不代替逻辑 ID 判定。",
    )
    section_keywords: list[str] = Field(
        default_factory=list,
        description="便于人工复核章节的关键词；只作诊断线索，不作为 V2 主命中键。",
    )

    @field_validator(
        "logical_doc_id",
        "source_revision",
        "logical_parent_id",
        "source_path",
        mode="before",
    )
    @classmethod
    def normalize_optional_identity(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "logical_chunk_ids",
        "matched_logical_child_ids",
        "section_keywords",
    )
    @classmethod
    def validate_unique_non_blank_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("expected source 列表字段不能包含空字符串")
        if len(set(normalized)) != len(normalized):
            raise ValueError("expected source 列表字段不能包含重复值")
        return normalized

    @model_validator(mode="after")
    def validate_parent_trace(self) -> "ExpectedSource":
        if bool(self.logical_parent_id) != bool(self.matched_logical_child_ids):
            raise ValueError(
                "父块来源必须同时提供 logical_parent_id 和 matched_logical_child_ids"
            )
        if not set(self.matched_logical_child_ids).issubset(self.logical_chunk_ids):
            raise ValueError("matched logical child IDs 必须属于 logical_chunk_ids")
        return self

    @property
    def chunk_ids(self) -> list[str]:
        """兼容阶段 11-14 前的旧检索指标读取入口。"""

        return list(self.logical_chunk_ids)


class RequiredKeyFact(BaseModel):
    """答案完整性所需的一条带权人工审核事实。"""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(
        min_length=1,
        description="case 内唯一的关键事实 ID，用于 Judge 证据和报告对齐。",
    )
    text: str = Field(
        min_length=1,
        description="回答应覆盖的可核验事实，不应只是脱离语境的关键词。",
    )
    weight: float = Field(
        gt=0,
        description="完整性加权分母中的正权重；越大表示该事实越重要。",
    )
    critical: bool = Field(
        default=False,
        description="是否为缺失后触发 hard gate 的关键事实。",
    )

    @field_validator("fact_id", "text")
    @classmethod
    def normalize_required_fact_text(cls, value: str) -> str:
        return value.strip()


class RagEvalCase(BaseModel):
    """黄金评测集 V2 的单条、身份作用域明确的 RAG case。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(
        min_length=1,
        description="数据集版本内唯一且跨报告稳定的评测 case ID。",
    )
    dataset_version: str = Field(
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$",
        description="创建该 case 时所属的数据集语义版本；必须与父数据集一致。",
    )
    metric_profile: EvalMetricProfile = Field(
        description="该 case 合法使用的指标集合；rag 表示普通 RAG 评测 profile。",
    )
    question: str = Field(
        min_length=1,
        description="向被测 RAG 系统发送的原始问题。",
    )
    answerable: bool = Field(
        description="在指定知识版本和评测身份可见范围内是否存在可回答证据。",
    )
    expected_route: EvalExpectedRoute = Field(
        description="预期回答路线：rag_answer 使用证据回答，rag_no_answer 保守拒答。",
    )
    eval_principal_id: str = Field(
        min_length=1,
        description="服务端评测身份注册表中的稳定引用；Worker 据此重建权限，数据集不得携带 ACL 事实。",
    )
    knowledge_version: int = Field(
        ge=0,
        description="评测目标知识版本；0 仅表示无法重放的 legacy candidate，黄金 case 必须大于 0。",
    )
    source_revision: str = Field(
        min_length=1,
        description="评测语料的不可变 revision；必须与父数据集一致并由 Worker 校验。",
    )
    mode: RetrievalMode = Field(
        default="hybrid",
        description="发送给 RAG 请求的检索模式。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="该 case 的指标 K 和最终上下文最大结果数。",
    )
    candidate_k: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="每个召回源的候选数；为空时由请求契约回退到 top_k。",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="发送给 RAG 请求的最低检索分数。",
    )
    filters: EvalRetrievalFilters = Field(
        default_factory=EvalRetrievalFilters,
        description="非安全性的内容过滤条件；ACL 必须由 eval_principal_id 在服务端重建。",
    )
    retrieval_relevance_unit: EvalRetrievalRelevanceUnit = Field(
        default="logical_chunk",
        description=(
            "检索指标使用的逻辑身份层级：普通 case 按 logical_chunk，父块扩展 case "
            "按模型最终收到的 logical_parent。"
        ),
    )
    relevant_logical_chunk_ids: list[str] = Field(
        default_factory=list,
        description=(
            "与问题语义相关的去重逻辑子块全集；父块评测时用于追溯触发和正文子块，"
            "不直接作为 Precision/Recall 的身份集合。"
        ),
    )
    relevant_logical_parent_ids: list[str] = Field(
        default_factory=list,
        description=(
            "父块扩展 case 中与问题相关、实际进入最终上下文的逻辑父块全集；"
            "仅 retrieval_relevance_unit=logical_parent 时用于检索指标。"
        ),
    )
    relevant_doc_ids: list[str] = Field(
        default_factory=list,
        description="与问题相关的去重逻辑文档 ID，用于来源覆盖和诊断。",
    )
    authoritative_logical_chunk_ids: list[str] = Field(
        default_factory=list,
        description=(
            "必须由检索结果命中的权威逻辑子块 ID；它是语义相关全集的可信子集，"
            "用于独立来源策略判定而不参与 Precision 分母。"
        ),
    )
    authoritative_logical_parent_ids: list[str] = Field(
        default_factory=list,
        description=(
            "父块扩展 case 必须命中的权威逻辑父块 ID；必须属于相关父块全集，"
            "只用于独立来源策略判定。"
        ),
    )
    forbidden_logical_chunk_ids: list[str] = Field(
        default_factory=list,
        description=(
            "当前身份绝不能看到或答案绝不能采用的逻辑子块 ID；可表示 ACL 泄漏或"
            "语义相关但过期冲突的证据，不会注入检索过滤器。"
        ),
    )
    expected_sources: list[ExpectedSource] = Field(
        default_factory=list,
        description="人工可追溯的相关来源；其逻辑子块并集必须等于 relevant_logical_chunk_ids。",
    )
    required_key_facts: list[RequiredKeyFact] = Field(
        default_factory=list,
        description="答案完整性使用的带权关键事实；可回答 case 至少包含一条。",
    )
    question_intent: str | None = Field(
        default=None,
        min_length=1,
        description="人工归纳的问题意图；供答案相关性 Judge 使用。",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="回答必须遵守的显式约束，例如只基于可见知识或不得泄露部门内容。",
    )
    hard_gate_labels: list[str] = Field(
        default_factory=list,
        description="失败后直接阻断质量门禁的稳定标签，例如 acl_no_leak。",
    )
    scenario_tags: list[EvalScenarioTag] = Field(
        min_length=1,
        description="该 case 覆盖的场景标签；黄金数据集必须覆盖完整场景矩阵。",
    )
    expected_answer_keywords: list[str] = Field(
        default_factory=list,
        description="旧规则生成评测的兼容关键词；后续 Judge 以 required_key_facts 为准。",
    )
    forbidden_answer_keywords: list[str] = Field(
        default_factory=list,
        description="回答中禁止出现的泄漏或编造词；主要用于不可回答 case。",
    )
    annotation_method: EvalAnnotationMethod = Field(
        description="标注来源；model_assisted 和 legacy_migration 不能未经审核成为黄金 case。",
    )
    annotated_by: str = Field(
        min_length=1,
        description="创建标注的人员或工具身份，仅用于审计，不作为 reviewer。",
    )
    review_status: EvalReviewStatus = Field(
        description="人工审核状态；只有 approved case 可以进入 golden 数据集。",
    )
    reviewed_by: str | None = Field(
        default=None,
        min_length=1,
        description="完成审核的人工身份；pending_review 时为空。",
    )
    reviewed_at: datetime | None = Field(
        default=None,
        description="带时区的人工审核时间；pending_review 时为空。",
    )
    review_note: str = Field(
        default="",
        description="审核结论或待确认问题；approved/rejected 时不能为空。",
    )
    note: str = Field(
        default="",
        description="case 设计说明，不替代结构化标注字段。",
    )

    @field_validator(
        "case_id",
        "dataset_version",
        "question",
        "eval_principal_id",
        "source_revision",
        "question_intent",
        "annotated_by",
        "reviewed_by",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "relevant_logical_chunk_ids",
        "relevant_logical_parent_ids",
        "relevant_doc_ids",
        "authoritative_logical_chunk_ids",
        "authoritative_logical_parent_ids",
        "forbidden_logical_chunk_ids",
        "constraints",
        "hard_gate_labels",
        "scenario_tags",
        "expected_answer_keywords",
        "forbidden_answer_keywords",
    )
    @classmethod
    def validate_case_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Eval case 列表字段不能包含空字符串")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Eval case 列表字段不能包含重复值")
        return normalized

    @model_validator(mode="after")
    def validate_eval_semantics(self) -> "RagEvalCase":
        if self.candidate_k is not None and self.candidate_k < self.top_k:
            raise ValueError("candidate_k 必须大于等于 top_k")

        expected_logical_ids = {
            logical_id
            for source in self.expected_sources
            for logical_id in source.logical_chunk_ids
        }
        expected_doc_ids = {source.logical_doc_id for source in self.expected_sources}
        expected_parent_ids = {
            source.logical_parent_id
            for source in self.expected_sources
            if source.logical_parent_id is not None
        }
        if expected_logical_ids != set(self.relevant_logical_chunk_ids):
            raise ValueError(
                "expected_sources 的逻辑子块并集必须等于 relevant_logical_chunk_ids"
            )
        if expected_doc_ids != set(self.relevant_doc_ids):
            raise ValueError("expected_sources 的逻辑文档集合必须等于 relevant_doc_ids")
        if self.retrieval_relevance_unit == "logical_parent":
            if expected_parent_ids != set(self.relevant_logical_parent_ids):
                raise ValueError(
                    "父块评测的 expected_sources 父块集合必须等于 relevant_logical_parent_ids"
                )
            if self.authoritative_logical_chunk_ids:
                raise ValueError("父块评测不能同时声明权威逻辑子块")
        else:
            if self.relevant_logical_parent_ids or self.authoritative_logical_parent_ids:
                raise ValueError("子块评测不能声明父块相关性或父块权威来源")

        if self.answerable:
            if self.expected_route != "rag_answer":
                raise ValueError("answerable case 的 expected_route 必须是 rag_answer")
            if not self.relevant_logical_chunk_ids or not self.relevant_doc_ids:
                raise ValueError("answerable case 必须提供相关逻辑子块和逻辑文档 ID")
            if not self.required_key_facts:
                raise ValueError("answerable case 必须提供 required_key_facts")
            if "answerable" not in self.scenario_tags:
                raise ValueError("answerable case 必须包含 answerable 场景标签")
        else:
            if self.expected_route != "rag_no_answer":
                raise ValueError("不可回答 case 的 expected_route 必须是 rag_no_answer")
            if self.relevant_logical_chunk_ids or self.relevant_doc_ids:
                raise ValueError("不可回答 case 不能声明当前身份可见的相关来源")
            if self.expected_sources or self.required_key_facts:
                raise ValueError("不可回答 case 不能声明 expected_sources 或关键事实")
            if "unanswerable" not in self.scenario_tags:
                raise ValueError("不可回答 case 必须包含 unanswerable 场景标签")
            if not (self.forbidden_answer_keywords or self.note):
                raise ValueError("不可回答 case 至少需要禁止词或设计说明")

        has_parent_source = any(
            source.logical_parent_id is not None for source in self.expected_sources
        )
        if "parent_expansion" in self.scenario_tags and not has_parent_source:
            raise ValueError("parent_expansion case 必须提供可追溯的父块来源")
        if "multiple_relevant_sources" in self.scenario_tags and len(
            self.relevant_doc_ids
        ) < 2:
            raise ValueError("multiple_relevant_sources case 至少需要两个相关文档")
        if "permission_filter" in self.scenario_tags and not (
            self.forbidden_logical_chunk_ids or self.answerable
        ):
            raise ValueError("权限过滤负例必须声明禁止出现的逻辑子块")
        if not set(self.authoritative_logical_chunk_ids).issubset(
            self.relevant_logical_chunk_ids
        ):
            raise ValueError("权威逻辑子块必须属于语义相关逻辑子块全集")
        if not set(self.authoritative_logical_parent_ids).issubset(
            self.relevant_logical_parent_ids
        ):
            raise ValueError("权威逻辑父块必须属于语义相关逻辑父块全集")
        if set(self.authoritative_logical_chunk_ids) & set(
            self.forbidden_logical_chunk_ids
        ):
            raise ValueError("权威逻辑子块和禁止逻辑子块不能重叠")

        fact_ids = [fact.fact_id for fact in self.required_key_facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("required key fact_id 不能重复")

        reviewed = self.review_status in {"approved", "rejected"}
        if reviewed:
            if self.reviewed_by is None or self.reviewed_at is None:
                raise ValueError("approved/rejected case 必须记录 reviewer 和审核时间")
            if self.reviewed_at.utcoffset() is None:
                raise ValueError("reviewed_at 必须包含时区")
            if not self.review_note.strip():
                raise ValueError("approved/rejected case 必须记录 review_note")
            if (
                self.annotation_method == "model_assisted"
                and self.reviewed_by == self.annotated_by
            ):
                raise ValueError("模型辅助标注必须由不同的人工 reviewer 审核")
        elif self.reviewed_by is not None or self.reviewed_at is not None:
            raise ValueError("pending_review case 不能预填 reviewer 或审核时间")

        if self.review_status == "approved" and self.knowledge_version < 1:
            raise ValueError("approved case 必须绑定可重建的 knowledge_version")
        return self

    @property
    def id(self) -> str:
        """兼容现有 Runner 和指标模块的 case.id 读取方式。"""

        return self.case_id

    @property
    def case_type(self) -> EvalCaseType:
        """兼容现有规则指标的 answerable/no_answer 分支。"""

        return "answerable" if self.answerable else "no_answer"


class RagEvalDataset(BaseModel):
    """版本化、可审核且可重放的黄金评测数据集 V2。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = Field(
        description="评测数据 JSON Schema 版本；当前固定为 2.0。",
    )
    dataset_id: str = Field(
        min_length=1,
        description="跨版本稳定的数据集身份；语义变化时保留该身份并提升 dataset_version。",
    )
    dataset_version: str = Field(
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$",
        description="不可变的数据集语义版本；旧版本文件必须保留，不能原地改写语义。",
    )
    lifecycle: EvalDatasetLifecycle = Field(
        description="candidate 可包含待审核标注；golden 只能包含已批准 case 和完整场景矩阵。",
    )
    content_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="除本字段外规范化 JSON 的 SHA-256，用于发现同版本文件被意外改写。",
    )
    name: str = Field(
        min_length=1,
        description="面向报告展示的数据集名称。",
    )
    description: str = Field(
        default="",
        description="数据集范围、语料和主要场景说明。",
    )
    knowledge_base_dir: str = Field(
        min_length=1,
        description="本地验收语料目录；生产 Worker 仍按受信任知识源配置解析。",
    )
    source_revision: str = Field(
        min_length=1,
        description="整套语料的不可变 revision；所有 case 必须绑定同一值。",
    )
    created_at: datetime = Field(
        description="创建该语义版本的带时区时间。",
    )
    cases: list[RagEvalCase] = Field(
        min_length=1,
        description="该版本包含的评测 case；case_id 必须唯一。",
    )

    @field_validator(
        "dataset_id",
        "dataset_version",
        "name",
        "knowledge_base_dir",
        "source_revision",
    )
    @classmethod
    def normalize_dataset_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> "RagEvalDataset":
        if self.created_at.utcoffset() is None:
            raise ValueError("dataset created_at 必须包含时区")

        case_ids = [case.case_id for case in self.cases]
        duplicate_ids = sorted(
            {case_id for case_id in case_ids if case_ids.count(case_id) > 1}
        )
        if duplicate_ids:
            raise ValueError(f"评测样例 case_id 重复: {duplicate_ids}")

        if any(case.dataset_version != self.dataset_version for case in self.cases):
            raise ValueError("case.dataset_version 必须与父数据集一致")
        if any(case.source_revision != self.source_revision for case in self.cases):
            raise ValueError("case.source_revision 必须与父数据集一致")

        if self.lifecycle == "golden":
            not_approved = [
                case.case_id
                for case in self.cases
                if case.review_status != "approved"
            ]
            if not_approved:
                raise ValueError(f"golden 数据集包含未批准 case: {not_approved}")
            covered = {
                tag
                for case in self.cases
                for tag in case.scenario_tags
            }
            missing = sorted(REQUIRED_GOLDEN_SCENARIOS - covered)
            if missing:
                raise ValueError(f"golden 数据集缺少场景覆盖: {missing}")
        return self
