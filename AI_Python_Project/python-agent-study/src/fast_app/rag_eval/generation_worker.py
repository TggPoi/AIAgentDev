"""只在隔离 Eval 虚拟环境中运行的 DeepEval JSON Worker。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import redirect_stdout
import json
import sys
from typing import Any

from fast_app.rag_eval.models import (
    GenerationEvaluationRequest,
    GenerationEvaluationResponse,
    RagEvalError,
    RagEvalMetricName,
    RagEvalMetricResult,
)


GENERATION_METRIC_NAMES: tuple[RagEvalMetricName, ...] = (
    "generation_faithfulness",
    "generation_answer_relevance",
    "generation_answer_completeness",
    "generation_context_utilization",
)
DEFAULT_GENERATION_THRESHOLDS: dict[RagEvalMetricName, float] = {
    name: 0.5 for name in GENERATION_METRIC_NAMES
}

COMPLETENESS_STEPS = [
    "逐条读取 expected output 中编号的 required key facts。",
    "判断 actual output 是否明确表达了每条事实的核心语义，不要求逐字相同。",
    "仅按覆盖比例给出 0 到 10 的整数分数；不要因文风、长度或额外正确信息加分。",
]
CONTEXT_UTILIZATION_STEPS = [
    "识别 actual output 中用于回答 input 的主要信息点。",
    "逐项检查这些信息点是否由 retrieval context 支撑或合理归纳。",
    "同时判断 retrieval context 中与问题直接相关的证据是否被答案有效使用。",
    "综合有效使用与无依据内容比例给出 0 到 10 的整数分数。",
]


def _skipped(name: RagEvalMetricName, reason: str) -> RagEvalMetricResult:
    return RagEvalMetricResult(
        metric_name=name,
        status="skipped",
        short_reason=reason,
    )


def _zero(name: RagEvalMetricName, threshold: float, reason: str) -> RagEvalMetricResult:
    return RagEvalMetricResult(
        metric_name=name,
        score=0.0,
        threshold=threshold,
        passed=False,
        status="evaluated",
        short_reason=reason,
    )


def _error(name: RagEvalMetricName, exc: Exception) -> RagEvalMetricResult:
    chain: list[str] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 5:
        chain.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    lowered = " | ".join(chain).lower()
    if "timeout" in lowered:
        code, retryable = "judge_timeout", True
    elif "rate" in lowered or "429" in lowered:
        code, retryable = "judge_rate_limited", True
    elif "json" in lowered or "schema" in lowered or "validation" in lowered:
        code, retryable = "judge_invalid_output", False
    else:
        code, retryable = "judge_metric_failed", False
    return RagEvalMetricResult(
        metric_name=name,
        status="error",
        short_reason=f"{name} Judge 执行失败",
        error=RagEvalError(
            code=code,
            message=(str(exc) or type(exc).__name__)[:500],
            retryable=retryable,
        ),
    )


def _metric_result(
    name: RagEvalMetricName,
    metric: Any,
    threshold: float,
    include_reason: bool,
) -> RagEvalMetricResult:
    score = max(0.0, min(1.0, float(metric.score)))
    passed = score >= threshold
    reason = getattr(metric, "reason", None)
    if include_reason and isinstance(reason, str) and reason.strip():
        short_reason = reason.strip()[:1000]
    else:
        comparison = ">=" if passed else "<"
        short_reason = f"score={score:.4f} {comparison} threshold={threshold:.4f}"
    return RagEvalMetricResult(
        metric_name=name,
        score=score,
        threshold=threshold,
        passed=passed,
        status="evaluated",
        short_reason=short_reason,
    )


async def evaluate_request(
    request: GenerationEvaluationRequest,
) -> GenerationEvaluationResponse:
    # 必须先由 Adapter 设置安全环境，再导入 DeepEval 其余模块。
    from fast_app.rag_eval.config import RagEvalJudgeSettings
    from fast_app.rag_eval.deep_eval_adapter import QwenDeepEvalModel
    settings = RagEvalJudgeSettings.from_environment()
    model = QwenDeepEvalModel(settings=settings)
    return await evaluate_with_model(
        request,
        model=model,
        judge_model=settings.model_name,
    )


async def _evaluate_without_stdout_noise(
    request: GenerationEvaluationRequest,
    *,
    evaluator: Callable[
        [GenerationEvaluationRequest],
        Awaitable[GenerationEvaluationResponse],
    ] = evaluate_request,
) -> GenerationEvaluationResponse:
    """把 DeepEval 的提示和进度输出隔离到 stderr，保留 stdout JSON 协议。"""

    with redirect_stdout(sys.stderr):
        return await evaluator(request)


async def evaluate_with_model(
    request: GenerationEvaluationRequest,
    *,
    model: Any,
    judge_model: str,
) -> GenerationEvaluationResponse:
    """在已配置的本地 Judge 上逐项执行并隔离单项失败。"""

    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    expected_output = "\n".join(
        f"{index}. {fact}"
        for index, fact in enumerate(request.required_key_facts, start=1)
    )
    test_case = LLMTestCase(
        input=request.question,
        actual_output=request.answer,
        expected_output=expected_output or None,
        retrieval_context=request.retrieval_context or None,
    )
    results: dict[RagEvalMetricName, RagEvalMetricResult] = {}

    for name in request.metrics:
        threshold = request.thresholds.get(name, DEFAULT_GENERATION_THRESHOLDS[name])
        if name in {
            "generation_faithfulness",
            "generation_context_utilization",
        } and not request.retrieval_context:
            results[name] = _skipped(name, "没有可重放的最终 RagContext")
            continue
        if name == "generation_answer_completeness" and not request.required_key_facts:
            results[name] = _skipped(name, "no-answer case 没有 required_key_facts")
            continue
        if not request.answer.strip():
            results[name] = _zero(name, threshold, "最终答案为空，分数为 0")
            continue

        try:
            if name == "generation_faithfulness":
                metric = FaithfulnessMetric(
                    threshold=threshold,
                    model=model,
                    include_reason=request.include_judge_reason,
                    async_mode=True,
                )
            elif name == "generation_answer_relevance":
                metric = AnswerRelevancyMetric(
                    threshold=threshold,
                    model=model,
                    include_reason=request.include_judge_reason,
                    async_mode=True,
                )
            elif name == "generation_answer_completeness":
                metric = GEval(
                    name="Answer Completeness",
                    evaluation_params=[
                        SingleTurnParams.INPUT,
                        SingleTurnParams.ACTUAL_OUTPUT,
                        SingleTurnParams.EXPECTED_OUTPUT,
                    ],
                    evaluation_steps=COMPLETENESS_STEPS,
                    model=model,
                    threshold=threshold,
                    async_mode=True,
                )
            else:
                metric = GEval(
                    name="Context Utilization",
                    evaluation_params=[
                        SingleTurnParams.INPUT,
                        SingleTurnParams.ACTUAL_OUTPUT,
                        SingleTurnParams.RETRIEVAL_CONTEXT,
                    ],
                    evaluation_steps=CONTEXT_UTILIZATION_STEPS,
                    model=model,
                    threshold=threshold,
                    async_mode=True,
                )
            await metric.a_measure(test_case)
            results[name] = _metric_result(
                name,
                metric,
                threshold,
                request.include_judge_reason,
            )
        except Exception as exc:
            results[name] = _error(name, exc)

    return GenerationEvaluationResponse(
        case_id=request.case_id,
        judge_model=judge_model,
        metrics=results,
    )


async def _main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        request = GenerationEvaluationRequest.model_validate(payload)
        response = await _evaluate_without_stdout_noise(request)
        sys.stdout.write(response.model_dump_json())
        return 0
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
