"""验证黄金评测集 V2、legacy 迁移、审核门禁和内容完整性。"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from fast_app.evaluation.cases.loader import (
    DatasetIntegrityError,
    DatasetReviewRequiredError,
    calculate_dataset_content_sha256,
    load_eval_dataset,
    load_golden_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import (
    REQUIRED_GOLDEN_SCENARIOS,
    RagEvalCase,
    RagEvalDataset,
)


ROOT = Path(__file__).resolve().parents[3]
LEGACY_DATASET = (
    ROOT / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json"
)
V2_CANDIDATE_DATASET = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.candidate.json"
)
V2_GOLDEN_DATASET = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.0.0.json"
)


def assert_raises(error_type: type[Exception], action: Callable[[], object]) -> None:
    try:
        action()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_promoted_golden_payload() -> dict[str, object]:
    candidate = json.loads(V2_CANDIDATE_DATASET.read_text(encoding="utf-8"))
    candidate["dataset_version"] = "2.0.0"
    candidate["lifecycle"] = "golden"
    candidate["name"] = "stage11_acl_rag_eval_v2"
    for case in candidate["cases"]:
        case["dataset_version"] = "2.0.0"
        case["review_status"] = "approved"
        case["reviewed_by"] = "human:test-reviewer"
        case["reviewed_at"] = "2026-08-10T09:00:00+08:00"
        case["review_note"] = "已对照原始文档、逻辑 ID、事实权重和身份场景复核。"
    return seal_eval_dataset_payload(candidate)


def run_v2_candidate_checks() -> None:
    raw = json.loads(V2_CANDIDATE_DATASET.read_text(encoding="utf-8"))
    assert raw["content_sha256"] == calculate_dataset_content_sha256(raw)

    dataset = load_eval_dataset(
        V2_CANDIDATE_DATASET,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    assert dataset.schema_version == "2.0"
    assert dataset.lifecycle == "candidate"
    assert len(dataset.cases) == 7
    assert dataset.source_revision == "knowledge-version:6"
    assert all(case.knowledge_version == 6 for case in dataset.cases)
    assert all(case.review_status == "pending_review" for case in dataset.cases)
    covered = {tag for case in dataset.cases for tag in case.scenario_tags}
    assert REQUIRED_GOLDEN_SCENARIOS <= covered

    parent_case = next(
        case
        for case in dataset.cases
        if case.case_id == "public_acl_model_parent_expansion"
    )
    parent_source = parent_case.expected_sources[0]
    assert parent_source.logical_parent_id == "parent_ee80071ebf6cd988"
    assert parent_source.matched_logical_child_ids == [
        "chunk_87fff9e4db81f40d"
    ]
    assert parent_source.source_revision == "1a8a7b29380a74132dddd63819757fb05e281ca5"
    assert parent_source.chunk_ids == parent_case.relevant_logical_chunk_ids
    assert parent_case.id == parent_case.case_id
    assert parent_case.case_type == "answerable"

    denied_case = next(
        case
        for case in dataset.cases
        if case.case_id == "development_cannot_read_art_internal_terms"
    )
    assert denied_case.answerable is False
    assert denied_case.relevant_logical_chunk_ids == []
    assert denied_case.forbidden_logical_chunk_ids == [
        "chunk_0aa1bbea341cfb4d"
    ]
    assert "acl_no_leak" in denied_case.hard_gate_labels

    assert_raises(
        DatasetReviewRequiredError,
        lambda: load_golden_eval_dataset(
            V2_CANDIDATE_DATASET,
            repository_root=ROOT,
        ),
    )


def run_legacy_migration_checks() -> None:
    dataset = load_eval_dataset(LEGACY_DATASET)
    assert dataset.schema_version == "2.0"
    assert dataset.dataset_version == "1.0.0-legacy"
    assert dataset.lifecycle == "candidate"
    assert len(dataset.cases) == 6
    assert all(case.review_status == "pending_review" for case in dataset.cases)
    assert all(case.knowledge_version == 0 for case in dataset.cases)
    assert dataset.cases[0].id == "phase9_hybrid_retrieval_basic"
    assert dataset.cases[0].relevant_logical_chunk_ids
    assert dataset.cases[0].required_key_facts
    assert_raises(
        DatasetReviewRequiredError,
        lambda: load_golden_eval_dataset(
            LEGACY_DATASET,
            verify_source_revision=False,
        ),
    )


def run_golden_promotion_checks() -> None:
    production_golden = load_golden_eval_dataset(
        V2_GOLDEN_DATASET,
        repository_root=ROOT,
    )
    assert production_golden.dataset_version == "2.0.0"
    assert production_golden.lifecycle == "golden"
    assert len(production_golden.cases) == 7
    assert {case.reviewed_by for case in production_golden.cases} == {"human:TGG"}

    golden_payload = build_promoted_golden_payload()
    golden = RagEvalDataset.model_validate(golden_payload)
    assert golden.lifecycle == "golden"
    assert all(case.review_status == "approved" for case in golden.cases)

    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "stage11_rag_eval_cases.v2.0.0.json"
        write_json(path, golden_payload)
        loaded = load_golden_eval_dataset(
            path,
            repository_root=ROOT,
        )
        assert loaded.dataset_version == "2.0.0"
        assert len(loaded.cases) == 7

        tampered = deepcopy(golden_payload)
        tampered["cases"][0]["question"] = "被原地修改但未提升版本的问题"
        write_json(path, tampered)
        assert_raises(
            DatasetIntegrityError,
            lambda: load_eval_dataset(path),
        )


def run_invalid_contract_checks() -> None:
    raw = json.loads(V2_CANDIDATE_DATASET.read_text(encoding="utf-8"))

    bad_weight = deepcopy(raw["cases"][0])
    bad_weight["required_key_facts"][0]["weight"] = 0
    assert_raises(ValueError, lambda: RagEvalCase.model_validate(bad_weight))

    missing_principal = deepcopy(raw["cases"][0])
    missing_principal["eval_principal_id"] = " "
    assert_raises(ValueError, lambda: RagEvalCase.model_validate(missing_principal))

    missing_source_revision = deepcopy(raw["cases"][0])
    del missing_source_revision["expected_sources"][0]["source_revision"]
    assert_raises(
        ValueError,
        lambda: RagEvalCase.model_validate(missing_source_revision),
    )

    forged_acl = deepcopy(raw["cases"][0])
    forged_acl["filters"] = {"department_codes": ["development"]}
    assert_raises(ValueError, lambda: RagEvalCase.model_validate(forged_acl))

    wrong_version = deepcopy(raw)
    wrong_version["cases"][0]["dataset_version"] = "2.0.1"
    wrong_version = seal_eval_dataset_payload(wrong_version)
    assert_raises(
        ValueError,
        lambda: RagEvalDataset.model_validate(wrong_version),
    )

    malformed_version = deepcopy(raw)
    malformed_version["dataset_version"] = "candidate-latest"
    for case in malformed_version["cases"]:
        case["dataset_version"] = malformed_version["dataset_version"]
    malformed_version = seal_eval_dataset_payload(malformed_version)
    assert_raises(
        ValueError,
        lambda: RagEvalDataset.model_validate(malformed_version),
    )

    unsupported_schema = deepcopy(raw)
    unsupported_schema["schema_version"] = "3.0"
    unsupported_schema = seal_eval_dataset_payload(unsupported_schema)
    with TemporaryDirectory() as temp_dir:
        unsupported_path = Path(temp_dir) / "unsupported-schema.json"
        write_json(unsupported_path, unsupported_schema)
        assert_raises(
            ValueError,
            lambda: load_eval_dataset(unsupported_path),
        )

    same_reviewer = deepcopy(raw["cases"][0])
    same_reviewer["review_status"] = "approved"
    same_reviewer["reviewed_by"] = same_reviewer["annotated_by"]
    same_reviewer["reviewed_at"] = "2026-08-10T09:00:00+08:00"
    same_reviewer["review_note"] = "伪造的自审结论"
    assert_raises(ValueError, lambda: RagEvalCase.model_validate(same_reviewer))

    missing_parent_trace = deepcopy(raw["cases"][0])
    missing_parent_trace["expected_sources"][0]["matched_logical_child_ids"] = []
    assert_raises(
        ValueError,
        lambda: RagEvalCase.model_validate(missing_parent_trace),
    )

    incomplete_golden = build_promoted_golden_payload()
    incomplete_golden["cases"][0]["scenario_tags"].remove("parent_expansion")
    incomplete_golden = seal_eval_dataset_payload(incomplete_golden)
    assert_raises(
        ValueError,
        lambda: RagEvalDataset.model_validate(incomplete_golden),
    )

    wrong_revision = deepcopy(raw)
    wrong_revision["source_revision"] = "sha256:" + "0" * 64
    for case in wrong_revision["cases"]:
        case["source_revision"] = wrong_revision["source_revision"]
    wrong_revision = seal_eval_dataset_payload(wrong_revision)
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "wrong-revision.json"
        write_json(path, wrong_revision)
        assert_raises(
            DatasetIntegrityError,
            lambda: load_eval_dataset(
                path,
                verify_source_revision=True,
                repository_root=ROOT,
            ),
        )


def run_checks() -> None:
    run_v2_candidate_checks()
    run_legacy_migration_checks()
    run_golden_promotion_checks()
    run_invalid_contract_checks()
    print("Eval dataset V2 checks passed.")


if __name__ == "__main__":
    run_checks()
