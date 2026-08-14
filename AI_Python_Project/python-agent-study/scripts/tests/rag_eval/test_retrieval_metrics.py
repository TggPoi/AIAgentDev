"""轻量 RAG Eval 检索指标的确定性契约测试。"""

from fast_app.evaluation.cases.loader import load_golden_eval_dataset
from fast_app.evaluation.cases.models import ExpectedSource, RagEvalCase
from fast_app.rag_eval.retrieval import evaluate_retrieval_metrics


def test_ranked_results_are_deduplicated_before_scoring() -> None:
    result = evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=["chunk-a", "chunk-b"],
        ranked_logical_chunk_ids=[
            "chunk-x",
            "chunk-a",
            "chunk-a",
            "chunk-b",
            "chunk-z",
        ],
        k=4,
        answerable=True,
    )

    assert result.returned_count == 4
    assert result.underfilled is False
    assert result.first_relevant_rank == 2
    assert result.metrics["retrieval_recall_at_k"].score == 1.0
    assert result.metrics["retrieval_precision_at_k"].score == 0.5
    assert result.metrics["retrieval_hit_rate_at_k"].score == 1.0
    assert result.metrics["retrieval_mrr"].score == 0.5


def test_underfilled_results_do_not_use_missing_slots_as_precision_denominator() -> None:
    result = evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=["chunk-a", "chunk-b"],
        ranked_logical_chunk_ids=["chunk-a"],
        k=5,
        answerable=True,
    )

    assert result.returned_count == 1
    assert result.underfilled is True
    assert result.metrics["retrieval_recall_at_k"].score == 0.5
    assert result.metrics["retrieval_precision_at_k"].score == 1.0
    assert result.metrics["retrieval_hit_rate_at_k"].score == 1.0
    assert result.metrics["retrieval_mrr"].score == 1.0


def test_empty_answerable_results_score_zero() -> None:
    result = evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=["chunk-a"],
        ranked_logical_chunk_ids=[],
        k=3,
        answerable=True,
    )

    assert result.returned_count == 0
    assert result.underfilled is True
    assert {metric.score for metric in result.metrics.values()} == {0.0}


def test_no_answer_case_skips_retrieval_metrics() -> None:
    result = evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=[],
        ranked_logical_chunk_ids=[],
        k=3,
        answerable=False,
    )

    assert result.first_relevant_rank is None
    assert {metric.status for metric in result.metrics.values()} == {"skipped"}
    assert {metric.score for metric in result.metrics.values()} == {None}


def test_semantic_relevance_and_authoritative_source_policy_are_independent() -> None:
    result = evaluate_retrieval_metrics(
        relevant_logical_chunk_ids=["chunk-authoritative", "chunk-stale"],
        authoritative_logical_ids=["chunk-authoritative"],
        forbidden_logical_ids=["chunk-stale"],
        ranked_logical_chunk_ids=[
            "chunk-stale",
            "chunk-authoritative",
            "chunk-noise",
        ],
        k=3,
        answerable=True,
    )

    # stale Chunk 与问题语义相关，所以 Precision 不能把它伪装成检索跑题。
    assert result.metrics["retrieval_precision_at_k"].score == 2 / 3
    # 但它不是可采用的权威证据，必须由独立来源策略明确判失败。
    assert result.source_policy is not None
    assert result.source_policy.matched_authoritative_logical_ids == [
        "chunk-authoritative"
    ]
    assert result.source_policy.forbidden_retrieved_logical_ids == ["chunk-stale"]
    assert result.source_policy.passed is False


def test_case_schema_separates_semantic_authoritative_and_forbidden_sources() -> None:
    dataset = load_golden_eval_dataset(
        "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json"
    )
    original = next(
        case
        for case in dataset.cases
        if case.case_id == "reader_gitlab_rollback_authoritative"
    )
    payload = original.model_dump(mode="json")
    payload.update(
        {
            "relevant_logical_chunk_ids": [
                "chunk_296a2380e2d87791",
                "chunk_bb13f7442fb8745c",
            ],
            "relevant_doc_ids": [
                "950da54b4e3d83ca25f80c069532a907891291a64ecafc7fd05ebd5d2d3768ca",
                "787f44904efba65722db4a6b252c8ddcc35862f71b7ec084e28456791ca13aca",
            ],
            "authoritative_logical_chunk_ids": ["chunk_296a2380e2d87791"],
            "forbidden_logical_chunk_ids": ["chunk_bb13f7442fb8745c"],
            "expected_sources": [
                *payload["expected_sources"],
                ExpectedSource(
                    logical_doc_id=(
                        "787f44904efba65722db4a6b252c8ddcc35862f71b7ec084e28456791ca13aca"
                    ),
                    source_revision="049c22ae7853e9318018e2e4a32ca49b71ed451d",
                    logical_chunk_ids=["chunk_bb13f7442fb8745c"],
                    source_path="development/gitlab-agent-mr-governance.md",
                    section_keywords=["手动回滚"],
                ).model_dump(mode="json"),
            ],
        }
    )

    case = RagEvalCase.model_validate(payload)
    assert case.authoritative_logical_chunk_ids == ["chunk_296a2380e2d87791"]
    assert set(case.relevant_logical_chunk_ids) & set(
        case.forbidden_logical_chunk_ids
    ) == {"chunk_bb13f7442fb8745c"}


def test_parent_expansion_case_can_score_final_parent_identity() -> None:
    dataset = load_golden_eval_dataset(
        "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json"
    )
    original = next(
        case
        for case in dataset.cases
        if case.case_id == "reader_es_milvus_parent_child_expansion"
    )
    payload = original.model_dump(mode="json")
    payload.update(
        {
            "retrieval_relevance_unit": "logical_parent",
            "relevant_logical_parent_ids": ["parent_19d48d66c7b9141e"],
            "authoritative_logical_parent_ids": ["parent_19d48d66c7b9141e"],
        }
    )

    case = RagEvalCase.model_validate(payload)
    assert case.retrieval_relevance_unit == "logical_parent"
    assert case.relevant_logical_parent_ids == ["parent_19d48d66c7b9141e"]


if __name__ == "__main__":
    test_ranked_results_are_deduplicated_before_scoring()
    test_underfilled_results_do_not_use_missing_slots_as_precision_denominator()
    test_empty_answerable_results_score_zero()
    test_no_answer_case_skips_retrieval_metrics()
    test_semantic_relevance_and_authoritative_source_policy_are_independent()
    test_case_schema_separates_semantic_authoritative_and_forbidden_sources()
    test_parent_expansion_case_can_score_final_parent_identity()
    print("rag_eval retrieval metrics tests passed")
