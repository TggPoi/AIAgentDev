"""验证 V2.1.3 当前语料 candidate 的设计和不可变版本边界。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_eval_dataset
from fast_app.evaluation.cases.models import REQUIRED_GOLDEN_SCENARIOS


ROOT = Path(__file__).resolve().parents[3]
V212_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.2.json"
)
V213_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.3.json"
)
V212_HASH = "71bb897a278b6501067d33e6e7aff933e56d4aa3ece8567d5f3343d0bb34ec7d"
SOURCE_REVISION = (
    "sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167"
)


def load_cases():
    previous = load_eval_dataset(V212_PATH)
    dataset = load_eval_dataset(
        V213_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return previous, dataset, {case.case_id: case for case in dataset.cases}


def test_candidate_version_and_review_boundary() -> None:
    previous, dataset, cases = load_cases()

    assert previous.dataset_version == "2.1.2"
    assert previous.lifecycle == "golden"
    assert previous.content_sha256 == V212_HASH

    assert dataset.dataset_version == "2.1.3"
    assert dataset.lifecycle == "candidate"
    assert dataset.source_revision == SOURCE_REVISION
    assert len(cases) == 16
    assert {case.dataset_version for case in cases.values()} == {"2.1.3"}
    assert {case.knowledge_version for case in cases.values()} == {0}
    assert {case.review_status for case in cases.values()} == {"pending_review"}
    assert all(case.reviewed_by is None for case in cases.values())
    assert all(case.reviewed_at is None for case in cases.values())


def test_current_corpus_replaces_all_old_qrels() -> None:
    previous, dataset, _ = load_cases()
    old_ids = {
        logical_id
        for case in previous.cases
        for logical_id in (
            case.relevant_logical_chunk_ids
            + case.relevant_logical_parent_ids
            + case.forbidden_logical_chunk_ids
        )
    }
    new_ids = {
        logical_id
        for case in dataset.cases
        for logical_id in (
            case.relevant_logical_chunk_ids
            + case.relevant_logical_parent_ids
            + case.forbidden_logical_chunk_ids
        )
    }
    assert old_ids.isdisjoint(new_ids)


def test_long_documents_are_the_core_evidence() -> None:
    _, _, cases = load_cases()
    long_document_case_ids = {
        "reader_word_face_outline_debugging",
        "reader_word_six_week_acceptance",
        "reader_pdf_companion_ai_guard",
        "reader_pdf_nne_training_runtime",
        "reader_pdf_mover_migration",
        "reader_pdf_performance_workflow",
        "reader_longdocs_toon_production_multi_source",
    }
    assert long_document_case_ids.issubset(cases)

    long_document_paths = {
        source.source_path
        for case_id in long_document_case_ids
        for source in cases[case_id].expected_sources
    }
    assert any(path.endswith(".docx") for path in long_document_paths)
    assert any(path.endswith(".pdf") for path in long_document_paths)


def test_all_nine_documents_and_supported_formats_are_covered() -> None:
    _, dataset, _ = load_cases()
    paths = {
        source.source_path
        for case in dataset.cases
        for source in case.expected_sources
    }
    assert len(paths) == 9
    assert {Path(path).suffix for path in paths} == {
        ".md",
        ".docx",
        ".pdf",
        ".xlsx",
        ".pptx",
    }


def test_parent_multi_source_underfilled_and_acl_contracts() -> None:
    _, _, cases = load_cases()

    parent = cases["reader_deployment_env_parent_expansion"]
    assert parent.retrieval_relevance_unit == "logical_parent"
    assert parent.relevant_logical_parent_ids == ["parent_8203549515f66e1b"]
    assert parent.authoritative_logical_parent_ids == [
        "parent_8203549515f66e1b"
    ]
    assert parent.relevant_logical_chunk_ids == [
        "chunk_ac5579214b6a604d",
        "chunk_c4c06a13c5280044",
    ]

    multi = cases["reader_longdocs_toon_production_multi_source"]
    assert len(multi.relevant_doc_ids) == 2
    assert "multiple_relevant_sources" in multi.scenario_tags

    underfilled = cases["reader_public_acl_underfilled"]
    assert underfilled.top_k == 20
    assert underfilled.candidate_k == 20
    assert underfilled.filters.source_path.endswith("public/project-overview.md")
    assert "underfilled_k" in underfilled.scenario_tags

    acl_negative = cases["reader_art_acl_negative"]
    assert not acl_negative.answerable
    assert acl_negative.forbidden_logical_chunk_ids == [
        "chunk_36c26dd9a52eeb3d"
    ]
    assert "permission_filter" in acl_negative.scenario_tags


def test_scenario_matrix_and_principal_split() -> None:
    _, dataset, cases = load_cases()
    scenarios = {
        scenario for case in dataset.cases for scenario in case.scenario_tags
    }
    assert REQUIRED_GOLDEN_SCENARIOS.issubset(scenarios)

    reader_cases = [
        case for case in dataset.cases if case.case_id.startswith("reader_")
    ]
    operator_cases = [
        case for case in dataset.cases if case.case_id.startswith("operator_")
    ]
    assert len(reader_cases) == 13
    assert len(operator_cases) == 3
    assert len({case.eval_principal_id for case in reader_cases}) == 1
    assert len({case.eval_principal_id for case in operator_cases}) == 1
    assert reader_cases[0].eval_principal_id != operator_cases[0].eval_principal_id
    assert set(cases) == {case.case_id for case in dataset.cases}


if __name__ == "__main__":
    test_candidate_version_and_review_boundary()
    test_current_corpus_replaces_all_old_qrels()
    test_long_documents_are_the_core_evidence()
    test_all_nine_documents_and_supported_formats_are_covered()
    test_parent_multi_source_underfilled_and_acl_contracts()
    test_scenario_matrix_and_principal_split()
    print("Eval dataset V2.1.3 candidate checks passed")
