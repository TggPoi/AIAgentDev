from dataclasses import dataclass, field

from fast_app.evaluation.offline_eval_models import OfflineRagEvalReport


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
