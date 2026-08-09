"""验证 Eval 八项核心指标的版本化语义与统一结果契约。"""

from collections.abc import Callable

from fast_app.evaluation.contracts import (
    METRIC_CONTRACTS,
    MetricEvidence,
    MetricResult,
    get_metric_contract,
    get_metric_versions,
)
from fast_app.evaluation.generation.models import (
    GenerationCaseResult,
    GenerationContextUnit,
    GenerationDatasetReport,
    GenerationMetricInput,
    RequiredKeyFact,
)
from fast_app.evaluation.pipeline.models import (
    EvaluationContractVersions,
    EvaluationError,
    OfflineRagEvalCaseOutput,
    OfflineRagEvalReport,
)
from fast_app.evaluation.reports.serialization import to_jsonable
from fast_app.evaluation.retrieval.models import (
    RetrievalCaseResult,
    RetrievalDatasetReport,
    RetrievalMetricInput,
)
from fast_app.evaluation.thresholds.models import (
    MetricThreshold,
    MetricThresholdProfile,
)


EXPECTED_METRIC_NAMES = {
    "retrieval_recall_at_k",
    "retrieval_precision_at_k",
    "retrieval_hit_rate_at_k",
    "retrieval_mrr",
    "generation_faithfulness",
    "generation_answer_relevance",
    "generation_answer_completeness",
    "generation_context_utilization",
}


def assert_raises_value_error(action: Callable[[], object]) -> None:
    try:
        action()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def run_contract_catalog_checks() -> None:
    assert len(METRIC_CONTRACTS) == 8
    assert {contract.name for contract in METRIC_CONTRACTS} == EXPECTED_METRIC_NAMES
    assert len({contract.version for contract in METRIC_CONTRACTS}) == 8
    assert get_metric_versions() == {
        contract.name: contract.version for contract in METRIC_CONTRACTS
    }

    hard_failure_metrics = {
        contract.name
        for contract in METRIC_CONTRACTS
        if contract.allows_hard_failure
    }
    assert hard_failure_metrics == {
        "generation_faithfulness",
        "generation_answer_completeness",
    }
    assert all(
        contract.hard_failure_semantics
        for contract in METRIC_CONTRACTS
        if contract.allows_hard_failure
    )


def run_metric_result_checks() -> None:
    recall_contract = get_metric_contract("retrieval_recall_at_k")
    evidence = MetricEvidence(
        evidence_id="evidence-1",
        kind="retrieved_unit",
        description="命中的黄金逻辑子块",
        reference_id="chunk-logical-1",
    )
    evaluated = MetricResult(
        name=recall_contract.name,
        version=recall_contract.version,
        status="evaluated",
        score=0.5,
        reason="Top K 命中 1/2 个黄金逻辑子块。",
        threshold=0.4,
        passed=True,
        evidence=[evidence],
    )
    assert evaluated.score == 0.5
    assert evaluated.passed is True

    skipped = MetricResult(
        name=recall_contract.name,
        version=recall_contract.version,
        status="skipped",
        score=None,
        reason="该样例没有黄金相关逻辑子块。",
    )
    assert skipped.score is None

    empty_result = MetricResult(
        name=recall_contract.name,
        version=recall_contract.version,
        status="evaluated",
        score=0.0,
        reason="answerable case 没有返回任何逻辑子块。",
        evidence=[
            MetricEvidence(
                evidence_id="empty-result",
                kind="system",
                description="Top K 去重结果为空。",
            )
        ],
    )
    assert empty_result.score == 0.0

    error = MetricResult(
        name=recall_contract.name,
        version=recall_contract.version,
        status="error",
        score=None,
        reason="指标输入快照读取失败。",
        error_code="EVAL_INPUT_UNAVAILABLE",
        retryable=True,
    )
    assert error.retryable is True

    assert_raises_value_error(
        lambda: MetricResult(
            name=recall_contract.name,
            version=recall_contract.version,
            status="evaluated",
            score=1.1,
            reason="非法分数。",
        )
    )
    assert_raises_value_error(
        lambda: MetricResult(
            name=recall_contract.name,
            version=recall_contract.version,
            status="evaluated",
            score=0.5,
            reason="阈值与通过状态不成对。",
            threshold=0.6,
            evidence=[evidence],
        )
    )
    assert_raises_value_error(
        lambda: MetricResult(
            name=recall_contract.name,
            version=recall_contract.version,
            status="evaluated",
            score=0.0,
            reason="检索指标不允许硬失败。",
            hard_failure=True,
        )
    )
    assert_raises_value_error(
        lambda: MetricResult(
            name=recall_contract.name,
            version="retrieval_recall_at_k.v0",
            status="evaluated",
            score=0.5,
            reason="版本不匹配。",
        )
    )
    assert_raises_value_error(
        lambda: MetricResult(
            name=recall_contract.name,
            version=recall_contract.version,
            status="error",
            score=None,
            reason="缺少稳定错误码。",
        )
    )
    assert_raises_value_error(
        lambda: MetricEvidence(
            evidence_id="",
            kind="system",
            description="非法空 ID。",
        )
    )

    faithfulness = get_metric_contract("generation_faithfulness")
    hard_failure = MetricResult(
        name=faithfulness.name,
        version=faithfulness.version,
        status="evaluated",
        score=0.2,
        reason="关键原子声明缺少上下文支持。",
        threshold=0.8,
        passed=False,
        hard_failure=True,
        evidence=[
            MetricEvidence(
                evidence_id="claim-1",
                kind="answer_span",
                description="关键声明没有上下文支持。",
                excerpt="系统一定会自动批准。",
            )
        ],
    )
    assert hard_failure.hard_failure is True


def run_metric_input_checks() -> None:
    retrieval_input = RetrievalMetricInput(
        case_id="retrieval-1",
        retrieval_stage="rerank",
        requested_k=3,
        retrieved_logical_chunk_ids=["chunk-1", "chunk-1", "chunk-2"],
        relevant_logical_chunk_ids=["chunk-1", "chunk-3"],
    )
    assert retrieval_input.retrieved_logical_chunk_ids.count("chunk-1") == 2
    assert retrieval_input.unique_retrieved_count == 2
    assert retrieval_input.underfilled is True
    assert_raises_value_error(
        lambda: RetrievalMetricInput(
            case_id="retrieval-2",
            retrieval_stage="vector",
            requested_k=0,
            retrieved_logical_chunk_ids=[],
            relevant_logical_chunk_ids=["chunk-1"],
        )
    )
    assert_raises_value_error(
        lambda: RetrievalMetricInput(
            case_id="retrieval-3",
            retrieval_stage="keyword",
            requested_k=2,
            retrieved_logical_chunk_ids=["chunk-1"],
            relevant_logical_chunk_ids=["chunk-1", "chunk-1"],
        )
    )

    generation_input = GenerationMetricInput(
        case_id="generation-1",
        question="系统如何处理文档？",
        question_intent="说明文档处理流程",
        constraints=["覆盖检索和生成"],
        answer="系统先检索，再基于上下文生成答案。",
        context_units=[
            GenerationContextUnit(
                context_unit_id="context-1",
                content="系统先检索相关文档。",
            )
        ],
        required_key_facts=[
            RequiredKeyFact(
                fact_id="fact-1",
                text="系统先检索相关文档",
                weight=2.0,
                critical=True,
            )
        ],
    )
    assert generation_input.required_key_facts[0].critical is True
    assert_raises_value_error(
        lambda: GenerationMetricInput(
            case_id="generation-2",
            question="问题",
            answer="答案",
            context_units=[
                GenerationContextUnit("context-1", "材料一"),
                GenerationContextUnit("context-1", "材料二"),
            ],
        )
    )
    assert_raises_value_error(
        lambda: RequiredKeyFact(
            fact_id="fact-invalid",
            text="非法权重",
            weight=0.0,
        )
    )


def run_version_and_compatibility_checks() -> None:
    snapshot = EvaluationContractVersions(dataset_version="dataset.v1")
    serialized = to_jsonable(snapshot)
    assert serialized["dataset_version"] == "dataset.v1"
    assert set(serialized["metric_versions"]) == EXPECTED_METRIC_NAMES

    recall_contract = get_metric_contract("retrieval_recall_at_k")
    threshold = MetricThreshold(
        metric_name=recall_contract.name,
        metric_version=recall_contract.version,
        minimum_score=0.8,
    )
    profile = MetricThresholdProfile(
        profile_id="default-rag",
        version="default-rag.v1",
        thresholds=[threshold],
    )
    assert profile.thresholds[0].minimum_score == 0.8
    assert_raises_value_error(
        lambda: MetricThreshold(
            metric_name=recall_contract.name,
            metric_version="retrieval_recall_at_k.v0",
            minimum_score=0.8,
        )
    )
    assert_raises_value_error(
        lambda: MetricThresholdProfile(
            profile_id="duplicate",
            version="duplicate.v1",
            thresholds=[threshold, threshold],
        )
    )

    legacy_retrieval_result = RetrievalCaseResult(
        case_id="legacy-retrieval",
        question="问题",
        case_type="answerable",
        retrieved_count=1,
        expected_source_count=1,
        hit_count=1,
        recall_at_k=1.0,
        reciprocal_rank=1.0,
        first_hit_rank=1,
        passed=True,
    )
    legacy_generation_result = GenerationCaseResult(
        case_id="legacy-generation",
        question="问题",
        case_type="answerable",
        passed=True,
        answer_length=2,
        source_count=1,
    )
    assert legacy_retrieval_result.metric_results == []
    assert legacy_generation_result.metric_results == []

    failed_output = OfflineRagEvalCaseOutput(
        case_id="failed-case",
        response=None,
        status="failed",
        errors=[
            EvaluationError(
                code="EVAL_TARGET_TIMEOUT",
                message="被测目标调用超时。",
                retryable=True,
            )
        ],
    )
    assert failed_output.response is None
    assert_raises_value_error(
        lambda: OfflineRagEvalCaseOutput(
            case_id="failed-without-error",
            response=None,
            status="failed",
        )
    )
    assert_raises_value_error(
        lambda: OfflineRagEvalCaseOutput(
            case_id="skipped-without-reason",
            response=None,
            status="skipped",
        )
    )

    report = OfflineRagEvalReport(
        dataset_name="contract-test",
        case_count=1,
        response_count=0,
        retrieval_report=RetrievalDatasetReport(
            case_count=1,
            evaluated_case_count=0,
            skipped_case_count=0,
            passed_case_count=0,
            failed_case_count=1,
            mean_recall_at_k=0.0,
            mean_mrr=0.0,
        ),
        generation_report=GenerationDatasetReport(
            case_count=1,
            evaluated_case_count=0,
            passed_case_count=0,
            failed_case_count=1,
            pass_rate=0.0,
        ),
        status="partial",
        outputs=[failed_output],
    )
    assert report.status == "partial"
    assert set(to_jsonable(report)["contract_versions"]["metric_versions"]) == (
        EXPECTED_METRIC_NAMES
    )


def run_checks() -> None:
    run_contract_catalog_checks()
    run_metric_result_checks()
    run_metric_input_checks()
    run_version_and_compatibility_checks()


if __name__ == "__main__":
    run_checks()
    print("Eval metric contract checks passed.")
