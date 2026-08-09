from dataclasses import dataclass, field

from fast_app.evaluation.contracts import MetricName, get_metric_contract
from fast_app.evaluation.pipeline.models import OfflineRagEvalReport


@dataclass(frozen=True)
class MetricThreshold:
    """一个确定指标版本的最低分与硬失败策略。"""

    metric_name: MetricName
    metric_version: str
    minimum_score: float
    hard_failure_blocks: bool = True

    def __post_init__(self) -> None:
        contract = get_metric_contract(self.metric_name)
        if self.metric_version != contract.version:
            raise ValueError(
                f"metric_version 必须匹配 {self.metric_name} 当前契约 {contract.version}"
            )
        if not 0.0 <= self.minimum_score <= 1.0:
            raise ValueError("metric minimum_score 必须位于 0 到 1")


@dataclass(frozen=True)
class MetricThresholdProfile:
    """八项指标可版本化、可审计的阈值配置。"""

    profile_id: str
    version: str
    thresholds: list[MetricThreshold] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("threshold profile_id 不能为空")
        if not self.version.strip():
            raise ValueError("threshold profile version 不能为空")
        names = [threshold.metric_name for threshold in self.thresholds]
        if len(set(names)) != len(names):
            raise ValueError("threshold profile 中同一指标不能重复")


@dataclass(frozen=True)
class EvalThresholds:
    """一次离线评测的最低通过标准。"""

    min_retrieval_recall_at_k: float = 0.0
    min_retrieval_mrr: float = 0.0
    min_generation_pass_rate: float = 0.0


@dataclass(frozen=True)
class EvalThresholdCheck:
    """单个指标的阈值检查结果。"""

    name: str
    actual: float
    expected_min: float
    passed: bool


@dataclass(frozen=True)
class EvalThresholdResult:
    """所有阈值检查的汇总结果。"""

    passed: bool
    checks: list[EvalThresholdCheck] = field(default_factory=list)


def check_offline_eval_thresholds(
    report: OfflineRagEvalReport,
    thresholds: EvalThresholds,
) -> EvalThresholdResult:
    """把真实评测报告中的指标和最低阈值逐项比较。"""

    checks = [
        EvalThresholdCheck(
            name="retrieval_mean_recall_at_k",
            actual=report.retrieval_report.mean_recall_at_k,
            expected_min=thresholds.min_retrieval_recall_at_k,
            passed=(
                report.retrieval_report.mean_recall_at_k
                >= thresholds.min_retrieval_recall_at_k
            ),
        ),
        EvalThresholdCheck(
            name="retrieval_mean_mrr",
            actual=report.retrieval_report.mean_mrr,
            expected_min=thresholds.min_retrieval_mrr,
            passed=report.retrieval_report.mean_mrr >= thresholds.min_retrieval_mrr,
        ),
        EvalThresholdCheck(
            name="generation_pass_rate",
            actual=report.generation_report.pass_rate,
            expected_min=thresholds.min_generation_pass_rate,
            passed=(
                report.generation_report.pass_rate
                >= thresholds.min_generation_pass_rate
            ),
        ),
    ]

    return EvalThresholdResult(
        passed=all(check.passed for check in checks),
        checks=checks,
    )
