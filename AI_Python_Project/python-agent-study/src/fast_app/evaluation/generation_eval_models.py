from dataclasses import dataclass, field
from typing import Literal


GenerationCheckName = Literal[
    "expected_keywords",
    "forbidden_keywords",
    "no_answer_refusal",
    "source_presence",
    "source_citation",
]


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


@dataclass(frozen=True)
class GenerationDatasetReport:
    """一批评测样例的生成评测汇总。"""

    case_count: int
    evaluated_case_count: int
    passed_case_count: int
    failed_case_count: int
    pass_rate: float
    results: list[GenerationCaseResult] = field(default_factory=list)
