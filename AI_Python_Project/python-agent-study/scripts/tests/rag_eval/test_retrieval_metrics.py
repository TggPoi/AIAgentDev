"""轻量 RAG Eval 检索指标的确定性契约测试。"""

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


if __name__ == "__main__":
    test_ranked_results_are_deduplicated_before_scoring()
    test_underfilled_results_do_not_use_missing_slots_as_precision_denominator()
    test_empty_answerable_results_score_zero()
    test_no_answer_case_skips_retrieval_metrics()
    print("rag_eval retrieval metrics tests passed")
