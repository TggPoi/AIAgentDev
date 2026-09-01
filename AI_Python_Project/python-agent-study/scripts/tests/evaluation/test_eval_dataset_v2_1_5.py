"""验证 V2.1.5 candidate 的语义相关与权威来源契约。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_eval_dataset


ROOT = Path(__file__).resolve().parents[3]
V214_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.4.json"
)
V215_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.5.json"
)
V214_HASH = "b3b59273d57baaa5afae6219c1590041ec2d1a49c95f2fcb4b190f84ecea6618"


def load_cases():
    previous = load_eval_dataset(V214_PATH)
    dataset = load_eval_dataset(
        V215_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return previous, dataset, {case.case_id: case for case in dataset.cases}


def test_toon_case_uses_complete_direct_evidence_without_background_summary() -> None:
    previous, _, cases = load_cases()
    assert previous.content_sha256 == V214_HASH

    case = cases["reader_longdocs_toon_production_multi_source"]
    assert case.top_k == 5
    assert case.relevant_logical_chunk_ids == [
        "chunk_f6b5cbc02b515961",
        "chunk_6f31fe460a4ff15b",
        "chunk_519c11634c2ef350",
        "chunk_835a2d68531e3688",
        "chunk_6fb6c9494ea6327d",
    ]
    assert case.authoritative_logical_chunk_ids == [
        "chunk_f6b5cbc02b515961",
        "chunk_519c11634c2ef350",
    ]
    assert "chunk_e6d54817043b7a3e" not in case.relevant_logical_chunk_ids


def test_mover_case_keeps_migration_matrix_semantic_but_not_authoritative() -> None:
    _, _, cases = load_cases()
    case = cases["reader_pdf_mover_migration"]

    assert case.relevant_logical_chunk_ids == [
        "chunk_00499a8f184e0ffd",
        "chunk_50f5a64967ad9d11",
        "chunk_f67c617af929dfce",
        "chunk_0c20779a4e397e0d",
    ]
    assert case.authoritative_logical_chunk_ids == [
        "chunk_00499a8f184e0ffd",
        "chunk_0c20779a4e397e0d",
    ]


def test_nne_case_does_not_require_duplicate_runtime_evidence() -> None:
    _, _, cases = load_cases()
    case = cases["reader_pdf_nne_training_runtime"]

    assert len(case.relevant_logical_chunk_ids) == 5
    assert case.authoritative_logical_chunk_ids == [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
    ]
    assert "chunk_1aacfb4570bf0fbe" in case.relevant_logical_chunk_ids
    assert "chunk_d8f7f46961b5a99e" in case.relevant_logical_chunk_ids


def test_underfilled_case_separates_full_document_relevance_from_required_sections() -> None:
    _, _, cases = load_cases()
    case = cases["reader_public_acl_underfilled"]

    assert len(case.relevant_logical_chunk_ids) == 16
    assert case.authoritative_logical_chunk_ids == [
        "chunk_5b810cc8195b5051",
        "chunk_1d4b9388b6b6a450",
        "chunk_9db8266b4400b809",
        "chunk_ab6631bbb6b4315e",
        "chunk_30679008b2e6d98b",
        "chunk_f6a70fdc86583e29",
        "chunk_34746fe25e2b2d22",
        "chunk_308b696cf3ecd8cd",
        "chunk_0d557c0bdaaed986",
        "chunk_9306991da46132c3",
        "chunk_aa8db320ce8941f2",
        "chunk_f9fff42f4d54189d",
    ]
    facts = {fact.fact_id: fact for fact in case.required_key_facts}
    assert "test_directory_mapping" in facts
    assert facts["test_directory_mapping"].critical is True


def test_candidate_version_and_semantic_change_boundary() -> None:
    previous, dataset, cases = load_cases()

    assert previous.dataset_version == "2.1.4"
    assert previous.lifecycle == "candidate"
    assert previous.content_sha256 == V214_HASH
    assert dataset.dataset_version == "2.1.5"
    assert dataset.lifecycle == "candidate"
    assert len(cases) == 16
    assert {case.dataset_version for case in cases.values()} == {"2.1.5"}
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
        "reader_longdocs_toon_production_multi_source",
        "reader_public_acl_underfilled",
    }

    for case in dataset.cases:
        if case.answerable:
            relevant_count = (
                len(case.relevant_logical_parent_ids)
                if case.retrieval_relevance_unit == "logical_parent"
                else len(case.relevant_logical_chunk_ids)
            )
            assert relevant_count <= case.top_k, case.case_id
