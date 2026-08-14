"""验证 V2.1.2 Golden 的相关性、权威性和不可变版本契约。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_eval_dataset, load_golden_eval_dataset


ROOT = Path(__file__).resolve().parents[3]
V211_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json"
)
V212_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.2.json"
)
V211_HASH = "ddd0983fbd2653fb9204fb116528bf460bec0c1109c7dff81d2ae200972da573"


def load_cases():
    previous = load_eval_dataset(V211_PATH)
    dataset = load_golden_eval_dataset(
        V212_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return previous, dataset, {case.case_id: case for case in dataset.cases}


def test_version_and_review_boundary() -> None:
    previous, dataset, cases = load_cases()
    assert previous.content_sha256 == V211_HASH
    assert previous.dataset_version == "2.1.1"
    assert previous.lifecycle == "golden"

    assert dataset.dataset_version == "2.1.2"
    assert dataset.lifecycle == "golden"
    assert len(cases) == 15
    assert {case.dataset_version for case in cases.values()} == {"2.1.2"}
    assert {case.review_status for case in cases.values()} == {"approved"}
    assert {case.reviewed_by for case in cases.values()} == {"human:TGG"}
    assert all(case.reviewed_at is not None for case in cases.values())
    assert all(case.review_note.strip() for case in cases.values())


def test_parent_expansion_uses_final_parent_identity() -> None:
    _, _, cases = load_cases()
    case = cases["reader_es_milvus_parent_child_expansion"]
    assert case.retrieval_relevance_unit == "logical_parent"
    assert case.relevant_logical_parent_ids == ["parent_19d48d66c7b9141e"]
    assert case.authoritative_logical_parent_ids == ["parent_19d48d66c7b9141e"]
    assert case.relevant_logical_chunk_ids == [
        "chunk_d26c5a41d92d12dd",
        "chunk_7f03bd18244ce719",
        "chunk_315425934f0cd8b4",
    ]


def test_semantic_qrels_and_authority_are_separate() -> None:
    _, _, cases = load_cases()

    rollback = cases["reader_gitlab_rollback_authoritative"]
    assert rollback.relevant_logical_chunk_ids == [
        "chunk_296a2380e2d87791",
        "chunk_bb13f7442fb8745c",
        "chunk_58906be3fa1f61ce",
    ]
    assert rollback.authoritative_logical_chunk_ids == [
        "chunk_296a2380e2d87791"
    ]
    assert rollback.forbidden_logical_chunk_ids == [
        "chunk_bb13f7442fb8745c",
        "chunk_58906be3fa1f61ce",
    ]

    assert set(
        cases["reader_webhook_worker_multi_source"].relevant_logical_chunk_ids
    ) == {
        "chunk_dea252b8024f71e1",
        "chunk_0452d406311e7d7b",
        "chunk_1bad0a3f3f2ac852",
        "chunk_cb80f57b1ca93ed4",
        "chunk_6a62985afb908b63",
    }
    assert set(cases["reader_milvus_index_check"].relevant_logical_chunk_ids) == {
        "chunk_4e797af9683c05c2",
        "chunk_550d5fb338ceb75a",
    }
    assert set(cases["reader_visibility_positive"].relevant_logical_chunk_ids) == {
        "chunk_f8a53eabbef5743c",
        "chunk_e61f024c79efd70d",
        "chunk_ef414e98d607ed62",
        "chunk_0516c4cb2db53ade",
    }
    assert set(
        cases["reader_worker_failure_recovery"].relevant_logical_chunk_ids
    ) == {"chunk_bf7e323eb34c4674", "chunk_31f6a030be67925c"}


if __name__ == "__main__":
    test_version_and_review_boundary()
    test_parent_expansion_uses_final_parent_identity()
    test_semantic_qrels_and_authority_are_separate()
    print("Eval dataset V2.1.2 Golden checks passed")
