"""不依赖第三方 IR 框架的四个检索指标。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from fast_app.rag_eval.models import (
    RagEvalMetricName,
    RagEvalMetricResult,
    RetrievalMetricEvaluation,
    RetrievalSourcePolicyResult,
)


RETRIEVAL_METRIC_NAMES: tuple[RagEvalMetricName, ...] = (
    "retrieval_recall_at_k",
    "retrieval_precision_at_k",
    "retrieval_hit_rate_at_k",
    "retrieval_mrr",
)
DEFAULT_RETRIEVAL_THRESHOLDS: Mapping[RagEvalMetricName, float] = {
    name: 0.5 for name in RETRIEVAL_METRIC_NAMES
}


def _unique_top_k(values: Iterable[str], k: int) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
        if len(unique) == k:
            break
    return unique


def _evaluated_metric(
    name: RagEvalMetricName,
    score: float,
    threshold: float,
) -> RagEvalMetricResult:
    passed = score >= threshold
    comparison = ">=" if passed else "<"
    return RagEvalMetricResult(
        metric_name=name,
        score=score,
        threshold=threshold,
        passed=passed,
        status="evaluated",
        short_reason=f"score={score:.4f} {comparison} threshold={threshold:.4f}",
    )


def _skipped_metric(name: RagEvalMetricName, reason: str) -> RagEvalMetricResult:
    return RagEvalMetricResult(
        metric_name=name,
        status="skipped",
        short_reason=reason,
    )


def evaluate_retrieval_metrics(
    *,
    relevant_logical_chunk_ids: Iterable[str],
    ranked_logical_chunk_ids: Iterable[str],
    k: int,
    answerable: bool,
    authoritative_logical_ids: Iterable[str] = (),
    forbidden_logical_ids: Iterable[str] = (),
    ranked_forbidden_logical_ids: Iterable[str] | None = None,
    thresholds: Mapping[RagEvalMetricName, float] | None = None,
) -> RetrievalMetricEvaluation:
    """按去重逻辑 Chunk 身份计算单 case 的四个检索指标。"""

    if k < 1:
        raise ValueError("k 必须大于等于 1")

    gold = {value.strip() for value in relevant_logical_chunk_ids if value.strip()}
    ranked = _unique_top_k(ranked_logical_chunk_ids, k)
    authoritative = {
        value.strip() for value in authoritative_logical_ids if value.strip()
    }
    forbidden = {value.strip() for value in forbidden_logical_ids if value.strip()}
    policy_ranked = (
        ranked
        if ranked_forbidden_logical_ids is None
        else _unique_top_k(ranked_forbidden_logical_ids, k)
    )
    matched = [value for value in ranked if value in gold]
    false_positives = [value for value in ranked if value not in gold]
    first_rank = next(
        (rank for rank, value in enumerate(ranked, start=1) if value in gold),
        None,
    )
    source_policy = None
    if authoritative or forbidden:
        matched_authoritative = [
            value for value in ranked if value in authoritative
        ]
        missing_authoritative = sorted(authoritative - set(matched_authoritative))
        forbidden_retrieved = [
            value for value in policy_ranked if value in forbidden
        ]
        source_policy = RetrievalSourcePolicyResult(
            passed=not missing_authoritative and not forbidden_retrieved,
            matched_authoritative_logical_ids=matched_authoritative,
            missing_authoritative_logical_ids=missing_authoritative,
            forbidden_retrieved_logical_ids=forbidden_retrieved,
        )

    if not answerable or not gold:
        metrics = {
            name: _skipped_metric(
                name,
                "no-answer case 没有黄金相关逻辑 Chunk，检索指标不适用",
            )
            for name in RETRIEVAL_METRIC_NAMES
        }
    else:
        effective_thresholds = {
            **DEFAULT_RETRIEVAL_THRESHOLDS,
            **(thresholds or {}),
        }
        returned_count = len(ranked)
        hit_count = len(matched)
        scores: dict[RagEvalMetricName, float] = {
            "retrieval_recall_at_k": hit_count / len(gold),
            "retrieval_precision_at_k": (
                hit_count / min(k, returned_count) if returned_count else 0.0
            ),
            "retrieval_hit_rate_at_k": 1.0 if hit_count else 0.0,
            "retrieval_mrr": 1.0 / first_rank if first_rank is not None else 0.0,
        }
        metrics = {
            name: _evaluated_metric(name, score, effective_thresholds[name])
            for name, score in scores.items()
        }

    return RetrievalMetricEvaluation(
        requested_k=k,
        returned_count=len(ranked),
        underfilled=len(ranked) < k,
        relevant_retrieved_count=len(matched),
        gold_relevant_count=len(gold),
        first_relevant_rank=first_rank,
        matched_logical_chunk_ids=matched,
        false_positive_logical_chunk_ids=false_positives,
        source_policy=source_policy,
        metrics=metrics,
    )


__all__ = [
    "DEFAULT_RETRIEVAL_THRESHOLDS",
    "RETRIEVAL_METRIC_NAMES",
    "evaluate_retrieval_metrics",
]
