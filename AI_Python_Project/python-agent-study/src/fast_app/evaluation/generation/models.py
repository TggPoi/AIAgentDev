from dataclasses import dataclass, field
from typing import Literal

from fast_app.evaluation.contracts import MetricResult


GenerationCheckName = Literal[
    "expected_keywords",
    "forbidden_keywords",
    "no_answer_refusal",
    "source_presence",
    "source_citation",
]


@dataclass(frozen=True)
class GenerationContextUnit:
    """生成评测看到的一个最终上下文单元。"""

    context_unit_id: str
    content: str

    def __post_init__(self) -> None:
        if not self.context_unit_id.strip():
            raise ValueError("generation context_unit_id 不能为空")
        if not self.content.strip():
            raise ValueError("generation context content 不能为空")


@dataclass(frozen=True)
class RequiredKeyFact:
    """答案完整性评测所需的一条人工审核关键事实。"""

    fact_id: str
    text: str
    weight: float = 1.0
    critical: bool = False

    def __post_init__(self) -> None:
        if not self.fact_id.strip():
            raise ValueError("required key fact_id 不能为空")
        if not self.text.strip():
            raise ValueError("required key fact text 不能为空")
        if self.weight <= 0:
            raise ValueError("required key fact weight 必须大于 0")


@dataclass(frozen=True)
class GenerationMetricInput:
    """生成层四项指标共用的单 case 输入快照。"""

    case_id: str
    question: str
    answer: str
    context_units: list[GenerationContextUnit]
    question_intent: str | None = None
    constraints: list[str] = field(default_factory=list)
    required_key_facts: list[RequiredKeyFact] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("generation metric case_id 不能为空")
        if not self.question.strip():
            raise ValueError("generation metric question 不能为空")
        if self.question_intent is not None and not self.question_intent.strip():
            raise ValueError("question_intent 提供后不能为空")
        if any(not constraint.strip() for constraint in self.constraints):
            raise ValueError("generation metric constraint 不能为空")

        context_ids = [unit.context_unit_id for unit in self.context_units]
        if len(set(context_ids)) != len(context_ids):
            raise ValueError("generation context_unit_id 不能重复")

        fact_ids = [fact.fact_id for fact in self.required_key_facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("required key fact_id 不能重复")


@dataclass(frozen=True)
class GenerationCheck:
    """单条生成质量规则检查结果。

    一个 GenerationCaseResult 会包含多条 GenerationCheck。
    例如 answerable 样例通常会检查 expected_keywords、source_presence、
    source_citation。
    """

    name: GenerationCheckName
    passed: bool
    message: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationCaseResult:
    """单条评测样例的生成评测结果。

    这里评测的是 RagChatResponse.answer 和 RagChatResponse.sources，
    不再评测 RetrievedDoc 是否命中。
    """

    case_id: str
    question: str
    case_type: str
    passed: bool
    answer_length: int
    source_count: int
    checks: list[GenerationCheck] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)


@dataclass(frozen=True)
class GenerationDatasetReport:
    """一批评测样例的生成评测汇总。"""

    case_count: int
    evaluated_case_count: int
    passed_case_count: int
    failed_case_count: int
    pass_rate: float
    results: list[GenerationCaseResult] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)
