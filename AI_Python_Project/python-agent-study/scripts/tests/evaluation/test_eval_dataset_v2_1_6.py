"""验证 V2.1.6 candidate 的完整语义相关集合契约。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_eval_dataset


ROOT = Path(__file__).resolve().parents[3]
V215_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.5.json"
)
V216_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.6.json"
)
V215_HASH = "5cbb639e5a032c2a6bb29fd2be53a371a50e78cc096e6dcb332ea34709d53124"


def load_cases():
    dataset = load_eval_dataset(
        V216_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return dataset, {case.case_id: case for case in dataset.cases}


def test_nne_case_includes_custom_model_entry_chain_as_relevant_evidence() -> None:
    _, cases = load_cases()
    case = cases["reader_pdf_nne_training_runtime"]

    assert case.top_k == 6
    assert case.candidate_k == 10
    assert case.relevant_logical_chunk_ids == [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
        "chunk_1aacfb4570bf0fbe",
        "chunk_d8f7f46961b5a99e",
        "chunk_7c483a7b9ca5fe63",
    ]
    assert case.authoritative_logical_chunk_ids == [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
    ]
    assert {
        chunk_id
        for source in case.expected_sources
        for chunk_id in source.logical_chunk_ids
    } == set(case.relevant_logical_chunk_ids)


def test_mover_case_includes_experimental_status_as_relevant_evidence() -> None:
    _, cases = load_cases()
    case = cases["reader_pdf_mover_migration"]

    assert case.top_k == 5
    assert case.relevant_logical_chunk_ids == [
        "chunk_00499a8f184e0ffd",
        "chunk_50f5a64967ad9d11",
        "chunk_f67c617af929dfce",
        "chunk_0c20779a4e397e0d",
        "chunk_d3e9c4a77c432371",
    ]
    assert case.authoritative_logical_chunk_ids == [
        "chunk_00499a8f184e0ffd",
        "chunk_0c20779a4e397e0d",
    ]
    assert {
        chunk_id
        for source in case.expected_sources
        for chunk_id in source.logical_chunk_ids
    } == set(case.relevant_logical_chunk_ids)


def test_deployment_case_scores_all_direct_es_client_parent_evidence() -> None:
    _, cases = load_cases()
    case = cases["reader_deployment_env_parent_expansion"]

    assert case.retrieval_relevance_unit == "logical_parent"
    assert case.top_k == 5
    assert case.relevant_logical_chunk_ids == [
        "chunk_ac5579214b6a604d",
        "chunk_c4c06a13c5280044",
        "chunk_e44caff2a0b48c44",
        "chunk_00ecace9d8c29128",
    ]
    assert case.relevant_logical_parent_ids == [
        "parent_8203549515f66e1b",
        "parent_1a0572e425043fdf",
        "parent_948c596391bdf5cb",
    ]
    assert case.authoritative_logical_chunk_ids == []
    assert case.authoritative_logical_parent_ids == [
        "parent_8203549515f66e1b"
    ]
    assert [
        (source.logical_parent_id, source.logical_chunk_ids)
        for source in case.expected_sources
    ] == [
        (
            "parent_8203549515f66e1b",
            ["chunk_ac5579214b6a604d", "chunk_c4c06a13c5280044"],
        ),
        ("parent_1a0572e425043fdf", ["chunk_e44caff2a0b48c44"]),
        ("parent_948c596391bdf5cb", ["chunk_00ecace9d8c29128"]),
    ]


def test_candidate_identity_and_semantic_change_boundary() -> None:
    previous = load_eval_dataset(V215_PATH)
    dataset, cases = load_cases()

    assert previous.dataset_version == "2.1.5"
    assert previous.lifecycle == "candidate"
    assert previous.content_sha256 == V215_HASH
    assert dataset.dataset_version == "2.1.6"
    assert dataset.lifecycle == "candidate"
    assert len(cases) == 16
    assert dataset.source_revision == previous.source_revision
    assert {case.dataset_version for case in cases.values()} == {"2.1.6"}
    assert {case.knowledge_version for case in cases.values()} == {0}
    assert {case.review_status for case in cases.values()} == {"pending_review"}
    assert all(case.reviewed_by is None for case in cases.values())
    assert all(case.reviewed_at is None for case in cases.values())

    ignored = {
        "dataset_version",
        "annotation_method",
        "annotated_by",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "note",
    }
    previous_cases = {case.case_id: case for case in previous.cases}
    changed = {
        case_id
        for case_id, case in cases.items()
        if case.model_dump(mode="json", exclude=ignored)
        != previous_cases[case_id].model_dump(mode="json", exclude=ignored)
    }
    assert changed == {
        "reader_pdf_nne_training_runtime",
        "reader_pdf_mover_migration",
        "reader_deployment_env_parent_expansion",
    }

    for case in dataset.cases:
        if case.answerable:
            relevant_count = (
                len(case.relevant_logical_parent_ids)
                if case.retrieval_relevance_unit == "logical_parent"
                else len(case.relevant_logical_chunk_ids)
            )
            assert relevant_count <= case.top_k, case.case_id
