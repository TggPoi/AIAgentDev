from dataclasses import dataclass, field
from typing import Literal


MetricName = Literal[
    "retrieval_recall_at_k",
    "retrieval_precision_at_k",
    "retrieval_hit_rate_at_k",
    "retrieval_mrr",
    "generation_faithfulness",
    "generation_answer_relevance",
    "generation_answer_completeness",
    "generation_context_utilization",
]
MetricLayer = Literal["retrieval", "generation"]
MetricEvaluationStatus = Literal["evaluated", "skipped", "error"]
MetricEvidenceKind = Literal[
    "retrieved_unit",
    "context_unit",
    "answer_span",
    "required_fact",
    "system",
]


@dataclass(frozen=True)
class MetricContract:
    """一个版本化指标的稳定业务语义。"""

    name: MetricName
    version: str
    layer: MetricLayer
    input_semantics: str
    score_semantics: str
    empty_input_policy: str
    allows_hard_failure: bool = False
    hard_failure_semantics: str | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("metric version 不能为空")
        if not self.input_semantics.strip():
            raise ValueError("metric input_semantics 不能为空")
        if not self.score_semantics.strip():
            raise ValueError("metric score_semantics 不能为空")
        if not self.empty_input_policy.strip():
            raise ValueError("metric empty_input_policy 不能为空")
        if self.allows_hard_failure != (self.hard_failure_semantics is not None):
            raise ValueError(
                "allows_hard_failure 与 hard_failure_semantics 必须同时启用或禁用"
            )
        if (
            self.hard_failure_semantics is not None
            and not self.hard_failure_semantics.strip()
        ):
            raise ValueError("metric hard_failure_semantics 提供后不能为空")


@dataclass(frozen=True)
class MetricEvidence:
    """支撑某项指标判定的可审计证据引用。"""

    evidence_id: str
    kind: MetricEvidenceKind
    description: str
    reference_id: str | None = None
    excerpt: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("metric evidence_id 不能为空")
        if not self.description.strip():
            raise ValueError("metric evidence description 不能为空")


@dataclass(frozen=True)
class MetricResult:
    """八项指标共用的版本化输出契约。

    evaluated：必须有 0～1 score；threshold 和 passed 必须同时存在或同时为空。
    skipped：没有 score，reason 说明为什么该 case 不适用这个指标。
    error：没有 score，必须提供稳定 error_code 和 retryable 分类。
    """

    name: MetricName
    version: str
    status: MetricEvaluationStatus
    score: float | None
    reason: str
    threshold: float | None = None
    passed: bool | None = None
    hard_failure: bool = False
    evidence: list[MetricEvidence] = field(default_factory=list)
    detail: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        contract = get_metric_contract(self.name)
        if self.version != contract.version:
            raise ValueError(
                f"metric result version 必须匹配 {self.name} 当前契约 {contract.version}"
            )
        if not self.version.strip():
            raise ValueError("metric result version 不能为空")
        if not self.reason.strip():
            raise ValueError("metric result reason 不能为空")
        if self.hard_failure and not contract.allows_hard_failure:
            raise ValueError(f"{self.name} 契约不允许 hard_failure")

        if self.status == "evaluated":
            self._validate_evaluated()
            return

        if self.status == "skipped":
            self._validate_without_score(status="skipped", require_error=False)
            return

        if self.status == "error":
            self._validate_without_score(status="error", require_error=True)
            return

        raise ValueError(f"未知 metric status: {self.status}")

    def _validate_evaluated(self) -> None:
        if self.score is None or not 0.0 <= self.score <= 1.0:
            raise ValueError("evaluated metric score 必须位于 0 到 1")
        if not self.evidence:
            raise ValueError("evaluated metric 必须提供可审计 evidence")
        if (self.threshold is None) != (self.passed is None):
            raise ValueError("metric threshold 和 passed 必须同时存在或同时为空")
        if self.threshold is not None and not 0.0 <= self.threshold <= 1.0:
            raise ValueError("metric threshold 必须位于 0 到 1")
        if self.error_code is not None or self.retryable:
            raise ValueError("evaluated metric 不能携带 error_code 或 retryable")
        if self.hard_failure and self.passed is True:
            raise ValueError("hard_failure metric 不能同时 passed=True")

    def _validate_without_score(
        self,
        *,
        status: Literal["skipped", "error"],
        require_error: bool,
    ) -> None:
        if self.score is not None or self.threshold is not None or self.passed is not None:
            raise ValueError(f"{status} metric 不能携带 score、threshold 或 passed")
        if self.hard_failure:
            raise ValueError(f"{status} metric 不能标记 hard_failure")
        if require_error and not (self.error_code and self.error_code.strip()):
            raise ValueError("error metric 必须提供 error_code")
        if not require_error and (self.error_code is not None or self.retryable):
            raise ValueError("skipped metric 不能携带 error_code 或 retryable")


METRIC_CONTRACTS: tuple[MetricContract, ...] = (
    MetricContract(
        name="retrieval_recall_at_k",
        version="retrieval_recall_at_k.v1",
        layer="retrieval",
        input_semantics=(
            "同一 case、同一检索阶段下，Top K 去重逻辑子块身份与人工审核的黄金相关逻辑子块身份。"
        ),
        score_semantics=(
            "Top K 命中的黄金相关逻辑子块数除以黄金相关逻辑子块总数；数据集结果为 answerable case 宏平均。"
        ),
        empty_input_policy="answerable case 没有返回结果时为 0；没有黄金相关子块时标记 skipped。",
    ),
    MetricContract(
        name="retrieval_precision_at_k",
        version="retrieval_precision_at_k.v1",
        layer="retrieval",
        input_semantics=(
            "同一 case、同一检索阶段下，Top K 去重逻辑子块身份与人工审核的黄金相关逻辑子块身份。"
        ),
        score_semantics=(
            "Top K 命中的黄金相关逻辑子块数除以 min(K, 实际去重返回数)；数据集结果为 answerable case 宏平均。"
        ),
        empty_input_policy="answerable case 没有返回结果时为 0；没有黄金相关子块时标记 skipped。",
    ),
    MetricContract(
        name="retrieval_hit_rate_at_k",
        version="retrieval_hit_rate_at_k.v1",
        layer="retrieval",
        input_semantics=(
            "每个 answerable case 的 Top K 去重逻辑子块身份与黄金相关逻辑子块身份。"
        ),
        score_semantics=(
            "单 case 至少命中一个黄金相关逻辑子块时 Hit@K=1，否则为 0；HitRate@K 是所有可评 case 的宏平均。"
        ),
        empty_input_policy="answerable case 没有返回结果时 Hit@K=0；没有黄金相关子块时标记 skipped。",
    ),
    MetricContract(
        name="retrieval_mrr",
        version="retrieval_mrr.v1",
        layer="retrieval",
        input_semantics=(
            "每个 answerable case 的 Top K 有序去重逻辑子块身份与黄金相关逻辑子块身份。"
        ),
        score_semantics=(
            "单 case 为第一个黄金相关逻辑子块排名的倒数，未命中为 0；MRR 是所有可评 case 的宏平均。"
        ),
        empty_input_policy="answerable case 没有返回结果时为 0；没有黄金相关子块时标记 skipped。",
    ),
    MetricContract(
        name="generation_faithfulness",
        version="generation_faithfulness.v1",
        layer="generation",
        input_semantics="最终答案中的原子可验证声明，以及模型实际看到的完整最终上下文单元。",
        score_semantics=(
            "依据逐声明 supported、partial、unsupported 判定聚合为 0～1；partial 权重属于 metric version。"
        ),
        empty_input_policy=(
            "没有可验证声明时标记 skipped；普通 RAG 答案没有最终上下文时标记 skipped，而不是伪造 0 分。"
        ),
        allows_hard_failure=True,
        hard_failure_semantics="任一被标记为关键的原子声明判为 unsupported 时触发。",
    ),
    MetricContract(
        name="generation_answer_relevance",
        version="generation_answer_relevance.v1",
        layer="generation",
        input_semantics="当前问题、冻结后的改写问题、人工审核的问题意图与约束，以及最终答案。",
        score_semantics=(
            "评估答案是否直接回应当前问题意图与约束；不把事实支持度、source 数量或参考答案文本相似度混入分数。"
        ),
        empty_input_policy="最终答案为空时为 0；问题或意图契约缺失导致无法判断时标记 error。",
    ),
    MetricContract(
        name="generation_answer_completeness",
        version="generation_answer_completeness.v1",
        layer="generation",
        input_semantics="最终答案与人工审核的带权 required key facts。",
        score_semantics=(
            "依据逐关键事实 covered、partial、missing 判定做带权聚合；partial 权重属于 metric version。"
        ),
        empty_input_policy="没有 required key facts 时标记 skipped；答案为空且存在 required key facts 时为 0。",
        allows_hard_failure=True,
        hard_failure_semantics="任一 critical required key fact 判为 missing 时触发。",
    ),
    MetricContract(
        name="generation_context_utilization",
        version="generation_context_utilization.v1",
        layer="generation",
        input_semantics=(
            "模型实际看到的最终 RagContext.docs 上下文单元，以及 Faithfulness 产生的 claim-to-context 证据映射。"
        ),
        score_semantics=(
            "至少支撑一个答案声明的最终上下文单元数除以全部最终上下文单元数；同一单元只计一次。"
        ),
        empty_input_policy="没有最终上下文的 direct answer 标记 skipped；有上下文但没有单元被使用时为 0。",
    ),
)

_METRIC_CONTRACT_BY_NAME = {contract.name: contract for contract in METRIC_CONTRACTS}


def get_metric_contract(name: MetricName) -> MetricContract:
    """返回指标的唯一版本化契约。"""

    return _METRIC_CONTRACT_BY_NAME[name]


def get_metric_versions() -> dict[str, str]:
    """返回适合写入报告快照的指标版本映射。"""

    return {contract.name: contract.version for contract in METRIC_CONTRACTS}
