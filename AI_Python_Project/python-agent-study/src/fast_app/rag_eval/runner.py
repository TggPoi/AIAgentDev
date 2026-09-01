"""轻量流式 RAG Eval 的用例编排与数据集聚合。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Literal, Protocol
from uuid import uuid4

from fast_app.core.config import Settings
from fast_app.evaluation.cases.models import RagEvalCase, RagEvalDataset
from fast_app.evaluation.pipeline.snapshot_capture import read_snapshot_value
from fast_app.rag_eval.generation import GenerationEvaluator
from fast_app.rag_eval.models import (
    GenerationEvaluationRequest,
    RagEvalCaseReport,
    RagEvalError,
    RagEvalMetricName,
    RagEvalMetricResult,
    RagEvalMetricSummary,
    RagEvalRunReport,
)
from fast_app.rag_eval.retrieval import RETRIEVAL_METRIC_NAMES, evaluate_retrieval_metrics
from fast_app.rag_eval.target import RagEvalTargetExecution


GENERATION_METRIC_NAMES: tuple[RagEvalMetricName, ...] = (
    "generation_faithfulness",
    "generation_answer_relevance",
    "generation_answer_completeness",
    "generation_context_utilization",
)
ALL_METRIC_NAMES = RETRIEVAL_METRIC_NAMES + GENERATION_METRIC_NAMES


class EvalTarget(Protocol):
    """Runner 只需要每条 case 的真实流式执行结果。"""

    async def execute(self, case: RagEvalCase) -> RagEvalTargetExecution: ...


class LightweightRagEvalRunner:
    """顺序执行真实 case，确保外部 Provider 与 Judge 压力可控。"""

    def __init__(
        self,
        *,
        target: EvalTarget,
        settings: Settings,
        pipeline_provider: Literal["classic", "langgraph", "rag_agent"],
        mode: Literal["retrieval", "generation", "all"],
        selected_metrics: Iterable[RagEvalMetricName],
        generation_evaluator: GenerationEvaluator | None = None,
        include_judge_reason: bool = False,
        thresholds: Mapping[RagEvalMetricName, float] | None = None,
        allow_candidate: bool = False,
    ) -> None:
        metrics = list(selected_metrics)
        if not metrics or len(metrics) != len(set(metrics)):
            raise ValueError("selected_metrics 必须非空且不能重复")
        allowed = set(metrics_for_mode(mode))
        invalid = [name for name in metrics if name not in allowed]
        if invalid:
            raise ValueError(f"指标与 mode={mode} 不匹配: {invalid}")
        needs_generation = any(name in GENERATION_METRIC_NAMES for name in metrics)
        if needs_generation and generation_evaluator is None:
            raise ValueError("生成指标需要 generation_evaluator")
        configured_thresholds = dict(thresholds or {})
        invalid_thresholds = [
            name
            for name, value in configured_thresholds.items()
            if name not in metrics or not 0.0 <= value <= 1.0
        ]
        if invalid_thresholds:
            raise ValueError(f"指标阈值未被选择或范围非法: {invalid_thresholds}")
        self.target = target
        self.settings = settings
        self.pipeline_provider = pipeline_provider
        self.mode = mode
        self.selected_metrics = metrics
        self.generation_evaluator = generation_evaluator
        self.include_judge_reason = include_judge_reason
        self.thresholds = configured_thresholds
        self.allow_candidate = allow_candidate

    async def run(self, dataset: RagEvalDataset) -> RagEvalRunReport:
        if dataset.lifecycle != "golden" and not self.allow_candidate:
            raise ValueError("轻量回归评测只接受经过审核的 Golden V2 数据集")
        self.validate_dataset_configuration(dataset)
        started = perf_counter()
        case_reports: list[RagEvalCaseReport] = []
        judge_model: str | None = None
        tested_model = self.settings.llm_model_name

        for case in dataset.cases:
            if case.metric_profile != "rag":
                # 当前 V2 Schema 仅允许 rag；保留明确分支以防后续 profile 扩展。
                case_reports.append(self._skipped_case(case))
                continue
            execution = await self.target.execute(case)
            tested_model = execution.snapshot.payload.target.generator
            report, case_judge = await self._evaluate_case(case, execution)
            case_reports.append(report)
            judge_model = case_judge or judge_model

        summaries = summarize_metrics(self.selected_metrics, case_reports)
        failed = sum(case.status == "failed" for case in case_reports)
        skipped = sum(case.status == "skipped" for case in case_reports)
        metric_errors = sum(
            result.status == "error"
            for case in case_reports
            for result in case.metrics.values()
        )
        source_policy_failures = sum(
            case.retrieval_source_policy is not None
            and not case.retrieval_source_policy.passed
            for case in case_reports
        )
        metric_failures = sum(
            result.passed is False
            for case in case_reports
            for result in case.metrics.values()
        )
        if failed == len(case_reports) and case_reports:
            status = "failed"
        elif (
            failed
            or skipped
            or metric_errors
            or metric_failures
            or source_policy_failures
        ):
            status = "partial"
        else:
            status = "completed"

        return RagEvalRunReport(
            schema_version="1.2",
            run_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            status=status,
            pipeline_provider=self.pipeline_provider,
            mode=self.mode,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            dataset_hash=dataset.content_sha256,
            source_revision=dataset.source_revision,
            tested_model=tested_model,
            judge_model=judge_model,
            selected_metrics=self.selected_metrics,
            case_count=len(case_reports),
            evaluated_case_count=sum(
                case.status == "evaluated" for case in case_reports
            ),
            failed_case_count=failed,
            skipped_case_count=skipped,
            duration_ms=(perf_counter() - started) * 1000,
            metric_summaries=summaries,
            cases=case_reports,
        )

    def validate_dataset_configuration(self, dataset: RagEvalDataset) -> None:
        """在启动真实目标前拒绝理论上不可能通过的检索配置。"""

        if not any(name in RETRIEVAL_METRIC_NAMES for name in self.selected_metrics):
            return
        recall_threshold = self.thresholds.get("retrieval_recall_at_k")
        for case in dataset.cases:
            if case.metric_profile != "rag" or not case.answerable:
                continue
            effective_k = min(case.top_k, self.settings.rerank_top_k)
            if case.retrieval_relevance_unit == "logical_parent":
                relevant_ids = set(case.relevant_logical_parent_ids)
                authoritative_ids = set(case.authoritative_logical_parent_ids)
            else:
                relevant_ids = set(case.relevant_logical_chunk_ids)
                authoritative_ids = set(case.authoritative_logical_chunk_ids)

            if len(authoritative_ids) > effective_k:
                raise ValueError(
                    "evaluation_config_invalid: "
                    f"case={case.case_id} authoritative_count={len(authoritative_ids)} "
                    f"超过 effective_k={effective_k}，全部权威来源门禁不可能通过"
                )
            if recall_threshold is not None and relevant_ids:
                max_recall = min(effective_k, len(relevant_ids)) / len(relevant_ids)
                if recall_threshold > max_recall:
                    raise ValueError(
                        "evaluation_config_invalid: "
                        f"case={case.case_id} max_recall_at_k={max_recall:.4f} "
                        f"低于 threshold={recall_threshold:.4f}"
                    )

    async def _evaluate_case(
        self,
        case: RagEvalCase,
        execution: RagEvalTargetExecution,
    ) -> tuple[RagEvalCaseReport, str | None]:
        metrics: dict[RagEvalMetricName, RagEvalMetricResult] = {}
        judge_model: str | None = None
        retrieval_evaluation = None
        retrieval_source_policy = None
        if execution.status == "evaluated":
            retrieval_names = [
                name for name in self.selected_metrics if name in RETRIEVAL_METRIC_NAMES
            ]
            if retrieval_names:
                retrieval = _evaluate_retrieval(
                    case,
                    execution,
                    self.thresholds,
                    effective_k=min(case.top_k, self.settings.rerank_top_k),
                )
                retrieval_evaluation = retrieval
                retrieval_source_policy = retrieval.source_policy
                metrics.update(
                    (name, retrieval.metrics[name]) for name in retrieval_names
                )

            generation_names = [
                name
                for name in self.selected_metrics
                if name in GENERATION_METRIC_NAMES
            ]
            if generation_names:
                request = GenerationEvaluationRequest(
                    case_id=case.case_id,
                    question=case.question,
                    answer=execution.stream.answer,
                    retrieval_context=_read_final_context(execution, self.settings),
                    required_key_facts=[fact.text for fact in case.required_key_facts],
                    metrics=generation_names,
                    thresholds={
                        name: self.thresholds[name]
                        for name in generation_names
                        if name in self.thresholds
                    },
                    include_judge_reason=self.include_judge_reason,
                )
                try:
                    evaluator = self.generation_evaluator
                    if evaluator is None:
                        raise RuntimeError("generation evaluator 未配置")
                    response = await evaluator.evaluate(request)
                    metrics.update(response.metrics)
                    judge_model = response.judge_model
                except Exception as exc:
                    for name in generation_names:
                        metrics[name] = RagEvalMetricResult(
                            metric_name=name,
                            status="error",
                            short_reason="隔离 DeepEval Worker 执行失败",
                            error=RagEvalError(
                                code="generation_worker_failed",
                                message=(str(exc) or type(exc).__name__)[:500],
                                retryable=False,
                            ),
                        )

        payload = execution.snapshot.payload
        return (
            RagEvalCaseReport(
                case_id=case.case_id,
                status=execution.status,
                answerable=case.answerable,
                expected_route=case.expected_route,
                actual_route=_actual_route(execution),
                knowledge_retrieval_performed=execution.knowledge_retrieval_performed,
                request_id=execution.stream.request_id or payload.request_id,
                trace_id=execution.stream.trace_id or payload.trace_id,
                knowledge_version=(
                    execution.stream.knowledge_version or payload.knowledge_version
                ),
                snapshot_id=execution.snapshot.snapshot_id,
                snapshot_hash=execution.snapshot.payload_hash,
                latency_ms=payload.latency_ms,
                metrics=metrics,
                retrieval_evaluation=retrieval_evaluation,
                retrieval_source_policy=retrieval_source_policy,
                error=execution.error,
            ),
            judge_model,
        )

    def _skipped_case(self, case: RagEvalCase) -> RagEvalCaseReport:
        return RagEvalCaseReport(
            case_id=case.case_id,
            status="skipped",
            answerable=case.answerable,
            expected_route=case.expected_route,
            actual_route=None,
            knowledge_retrieval_performed=False,
            latency_ms=0.0,
            metrics={},
            skipped_reason=(
                f"metric_profile={case.metric_profile} 不属于普通 RAG 指标 profile"
            ),
        )


def _evaluate_retrieval(
    case: RagEvalCase,
    execution: RagEvalTargetExecution,
    thresholds: Mapping[RagEvalMetricName, float],
    *,
    effective_k: int,
):
    rerank = execution.snapshot.payload.retrieval_stages["rerank"]
    ranked_chunk_ids = [
        document.logical_chunk_id or f"__missing_logical_id__:{document.id}"
        for document in rerank.documents
    ]
    if case.retrieval_relevance_unit == "logical_parent":
        context = execution.snapshot.payload.final_context
        context_documents = context.documents if context is not None else []
        ranked_ids = [
            document.logical_parent_id
            or document.parent_id
            or f"__missing_logical_parent_id__:{document.id}"
            for document in context_documents
        ]
        relevant_ids = case.relevant_logical_parent_ids
        authoritative_ids = case.authoritative_logical_parent_ids
    else:
        ranked_ids = ranked_chunk_ids
        relevant_ids = case.relevant_logical_chunk_ids
        authoritative_ids = case.authoritative_logical_chunk_ids
    return evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=relevant_ids,
        ranked_logical_chunk_ids=ranked_ids,
        k=effective_k,
        requested_k=case.top_k,
        answerable=case.answerable,
        authoritative_logical_ids=authoritative_ids,
        forbidden_logical_ids=case.forbidden_logical_chunk_ids,
        ranked_forbidden_logical_ids=ranked_chunk_ids,
        thresholds=thresholds,
    )


def _actual_route(execution: RagEvalTargetExecution) -> str | None:
    intent = execution.stream.route_intent
    if execution.knowledge_retrieval_performed:
        return f"{intent} -> knowledge_retrieval" if intent else "knowledge_retrieval"
    if intent:
        return f"{intent} -> no_knowledge_retrieval"
    return None


def _read_final_context(
    execution: RagEvalTargetExecution,
    settings: Settings,
) -> list[str]:
    context = execution.snapshot.payload.final_context
    if context is None:
        return []
    try:
        full_context = read_snapshot_value(context.context_text, settings)
    except Exception:
        return []
    return [full_context] if full_context else []


def summarize_metrics(
    selected_metrics: Iterable[RagEvalMetricName],
    cases: Iterable[RagEvalCaseReport],
) -> dict[RagEvalMetricName, RagEvalMetricSummary]:
    case_list = list(cases)
    summaries: dict[RagEvalMetricName, RagEvalMetricSummary] = {}
    for name in selected_metrics:
        values = [case.metrics[name] for case in case_list if name in case.metrics]
        scores = [value.score for value in values if value.status == "evaluated"]
        summaries[name] = RagEvalMetricSummary(
            metric_name=name,
            mean_score=(sum(scores) / len(scores) if scores else None),
            evaluated_count=len(scores),
            passed_count=sum(value.passed is True for value in values),
            skipped_count=sum(value.status == "skipped" for value in values),
            error_count=sum(value.status == "error" for value in values),
        )
    return summaries


def metrics_for_mode(
    mode: Literal["retrieval", "generation", "all"],
) -> tuple[RagEvalMetricName, ...]:
    if mode == "retrieval":
        return RETRIEVAL_METRIC_NAMES
    if mode == "generation":
        return GENERATION_METRIC_NAMES
    return ALL_METRIC_NAMES


__all__ = [
    "ALL_METRIC_NAMES",
    "GENERATION_METRIC_NAMES",
    "LightweightRagEvalRunner",
    "metrics_for_mode",
    "summarize_metrics",
]
