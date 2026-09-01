"""验证 V2.1.4 candidate 修复后的标注质量契约。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_eval_dataset
from fast_app.evaluation.cases.models import REQUIRED_GOLDEN_SCENARIOS


ROOT = Path(__file__).resolve().parents[3]
V213_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.3.json"
)
V214_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.4.json"
)
V213_HASH = "d691fc54c33899ad9d2cda3bda31f5bee0a5746c35787ff04ccc4fd97fbf4f93"


def load_cases():
    previous = load_eval_dataset(V213_PATH)
    dataset = load_eval_dataset(
        V214_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return previous, dataset, {case.case_id: case for case in dataset.cases}


def test_candidate_version_review_and_coverage_boundary() -> None:
    previous, dataset, cases = load_cases()

    assert previous.content_sha256 == V213_HASH
    assert previous.dataset_version == "2.1.3"
    assert previous.lifecycle == "candidate"

    assert dataset.dataset_version == "2.1.4"
    assert dataset.lifecycle == "candidate"
    assert len(cases) == 16
    assert {case.dataset_version for case in cases.values()} == {"2.1.4"}
    assert {case.knowledge_version for case in cases.values()} == {0}
    assert {case.review_status for case in cases.values()} == {"pending_review"}
    assert all(case.reviewed_by is None for case in cases.values())
    assert all(case.reviewed_at is None for case in cases.values())

    scenarios = {
        scenario for case in dataset.cases for scenario in case.scenario_tags
    }
    assert REQUIRED_GOLDEN_SCENARIOS.issubset(scenarios)

    reader_cases = [case for case in dataset.cases if case.case_id.startswith("reader_")]
    operator_cases = [
        case for case in dataset.cases if case.case_id.startswith("operator_")
    ]
    assert len(reader_cases) == 13
    assert len(operator_cases) == 3

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


def test_every_answerable_case_can_reach_full_recall_at_k() -> None:
    previous, dataset, _ = load_cases()
    assert previous.content_sha256 == V213_HASH
    assert previous.dataset_version == "2.1.3"
    assert previous.lifecycle == "candidate"
    assert dataset.dataset_version == "2.1.4"

    for case in dataset.cases:
        if not case.answerable:
            continue
        relevant_count = (
            len(case.relevant_logical_parent_ids)
            if case.retrieval_relevance_unit == "logical_parent"
            else len(case.relevant_logical_chunk_ids)
        )
        assert relevant_count <= case.top_k, case.case_id


def test_underfilled_case_treats_the_bounded_public_document_as_relevant() -> None:
    _, _, cases = load_cases()
    case = cases["reader_public_acl_underfilled"]
    assert case.top_k == 20
    assert case.candidate_k == 20
    assert set(case.relevant_logical_chunk_ids) == {
        "chunk_a96818cd638bdf5e",
        "chunk_0d712ae8b17bbe30",
        "chunk_5b810cc8195b5051",
        "chunk_1d4b9388b6b6a450",
        "chunk_9db8266b4400b809",
        "chunk_46184d5a7c6d3eb2",
        "chunk_ab6631bbb6b4315e",
        "chunk_30679008b2e6d98b",
        "chunk_f6a70fdc86583e29",
        "chunk_34746fe25e2b2d22",
        "chunk_308b696cf3ecd8cd",
        "chunk_0d557c0bdaaed986",
        "chunk_9306991da46132c3",
        "chunk_aa8db320ce8941f2",
        "chunk_f9fff42f4d54189d",
        "chunk_013212d0fb835c38",
    }
    assert "underfilled_k" in case.scenario_tags
    assert "全文" in case.question


def test_acl_negative_asks_a_fact_the_forbidden_chunk_actually_contains() -> None:
    _, _, cases = load_cases()
    case = cases["reader_art_acl_negative"]
    assert not case.answerable
    assert case.expected_route == "rag_no_answer"
    assert case.forbidden_logical_chunk_ids == ["chunk_36c26dd9a52eeb3d"]
    assert "是否同时包含" in case.question
    assert "分别是什么" not in case.question


def test_ppt_case_uses_one_unambiguous_source_section() -> None:
    _, _, cases = load_cases()
    assert "operator_pptx_input_buffer" not in cases
    case = cases["operator_pptx_network_strategy"]
    assert case.relevant_logical_chunk_ids == ["chunk_074e7c6fc05a33ef"]
    assert case.authoritative_logical_chunk_ids == ["chunk_074e7c6fc05a33ef"]
    assert case.filters.source_path.endswith("UE5战斗系统设计方案_RAG测试用PPT.pptx")
    serialized_facts = " ".join(fact.text for fact in case.required_key_facts)
    assert "0.15-0.25" not in serialized_facts
    assert "0.18~0.28" not in serialized_facts
    assert "PktLag" in serialized_facts
    assert "PacketLoss" in serialized_facts


def test_companion_case_is_scoped_to_section_7_5_chain_and_fallback() -> None:
    _, _, cases = load_cases()
    case = cases["reader_pdf_companion_ai_guard"]
    assert "7.5" in case.question
    assert case.relevant_logical_chunk_ids == [
        "chunk_1aacfb4570bf0fbe",
        "chunk_5237f6b9758968d7",
    ]


def test_nne_case_covers_sections_7_3_to_7_4_and_runtime_diagram() -> None:
    _, _, cases = load_cases()
    case = cases["reader_pdf_nne_training_runtime"]
    assert "7.3" in case.question
    assert "7.4" in case.question
    assert case.top_k == 5
    assert case.relevant_logical_chunk_ids == [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
        "chunk_1aacfb4570bf0fbe",
        "chunk_d8f7f46961b5a99e",
    ]


def test_mover_case_is_scoped_to_sections_8_1_and_10_1() -> None:
    _, _, cases = load_cases()
    case = cases["reader_pdf_mover_migration"]
    assert "8.1" in case.question
    assert "10.1" in case.question
    assert case.relevant_logical_chunk_ids == [
        "chunk_00499a8f184e0ffd",
        "chunk_50f5a64967ad9d11",
        "chunk_0c20779a4e397e0d",
    ]
