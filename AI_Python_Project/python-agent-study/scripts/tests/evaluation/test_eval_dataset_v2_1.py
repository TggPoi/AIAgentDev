"""验证 V2.1.1 Golden 中经过数据库和人工复核的 case 契约。"""

from pathlib import Path

from fast_app.evaluation.cases.loader import load_golden_eval_dataset


ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = (
    ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json"
)


def load_cases():
    dataset = load_golden_eval_dataset(
        DATASET_PATH,
        verify_source_revision=True,
        repository_root=ROOT,
    )
    return dataset, {case.case_id: case for case in dataset.cases}


def run_dataset_identity_checks() -> None:
    dataset, cases = load_cases()
    assert dataset.dataset_version == "2.1.1"
    assert dataset.lifecycle == "golden"
    assert len(cases) == 15
    assert {case.review_status for case in cases.values()} == {"approved"}
    assert {case.reviewed_by for case in cases.values()} == {"human:TGG"}
    assert all(case.reviewed_at is not None for case in cases.values())
    assert all(case.review_note.strip() for case in cases.values())
    corrected_ids = {
        "reader_es_milvus_parent_child_expansion",
        "reader_ue5_perfect_block",
        "reader_gitlab_rollback_authoritative",
        "reader_art_acl_negative",
        "reader_agent_tool_acceptance_underfilled",
        "operator_documented_art_scope_multi",
        "operator_global_reader_dev_positive",
    }
    assert {cases[case_id].annotated_by for case_id in corrected_ids} == {
        "codex:v2.1.1-case-corrector"
    }


def run_parent_expansion_checks() -> None:
    _, cases = load_cases()
    case = cases["reader_es_milvus_parent_child_expansion"]
    assert case.question == (
        "部署验收文档中的“ES 父子块与 Milvus 子块校验”章节规定了哪些检查要求？"
    )
    assert case.scenario_tags == ["answerable", "parent_expansion"]
    assert case.relevant_logical_chunk_ids == ["chunk_d26c5a41d92d12dd"]
    assert case.expected_sources[0].logical_parent_id == "parent_19d48d66c7b9141e"
    assert case.expected_sources[0].matched_logical_child_ids == [
        "chunk_d26c5a41d92d12dd"
    ]

    perfect_block = cases["reader_ue5_perfect_block"]
    assert perfect_block.scenario_tags == ["answerable"]
    assert perfect_block.expected_sources[0].logical_parent_id is None


def run_authoritative_rollback_checks() -> None:
    _, cases = load_cases()
    assert "reader_gitlab_rollback_multi_source" not in cases
    case = cases["reader_gitlab_rollback_authoritative"]
    assert case.relevant_logical_chunk_ids == ["chunk_296a2380e2d87791"]
    assert case.scenario_tags == ["answerable"]
    facts = {fact.fact_id: fact.text for fact in case.required_key_facts}
    assert "manual_sql" not in facts
    assert all("publication_version" not in text for text in facts.values())


def run_reader_acl_negative_checks() -> None:
    _, cases = load_cases()
    case = cases["reader_art_acl_negative"]
    assert case.question == (
        "角色美术规范是否包含“月光披风规则”和“女巫帽轮廓标准”这两个内部测试关键词？"
    )
    assert case.answerable is False
    assert case.forbidden_logical_chunk_ids == ["chunk_0aa1bbea341cfb4d"]
    assert case.scenario_tags == ["unanswerable", "permission_filter"]


def run_underfilled_filter_checks() -> None:
    _, cases = load_cases()
    assert "reader_checklist_env_single_gold" not in cases
    case = cases["reader_agent_tool_acceptance_underfilled"]
    assert case.scenario_tags == ["answerable", "underfilled_k"]
    assert case.top_k == 8
    assert case.filters.source_path == "development/agent-tool-acceptance.md"
    assert case.relevant_logical_chunk_ids == ["chunk_321a5c310d96c5a9"]
    assert [fact.text for fact in case.required_key_facts] == [
        "Agent Tool Acceptance 文档用于阶段 15-7 的 HTTP 验收。"
    ]


def run_operator_global_reader_checks() -> None:
    _, cases = load_cases()
    assert "operator_art_visible_scope_multi" not in cases
    documented_scope = cases["operator_documented_art_scope_multi"]
    assert documented_scope.scenario_tags == [
        "answerable",
        "multiple_relevant_sources",
    ]
    assert "permission_filter" not in documented_scope.scenario_tags

    assert "operator_dev_acl_negative" not in cases
    global_reader = cases["operator_global_reader_dev_positive"]
    assert global_reader.answerable is True
    assert global_reader.scenario_tags == ["answerable", "permission_filter"]
    assert global_reader.relevant_logical_chunk_ids == [
        "chunk_bf5a29d90fe09980",
        "chunk_4280ef8844cf5af5",
    ]
    assert global_reader.forbidden_logical_chunk_ids == []


def run_checks() -> None:
    run_dataset_identity_checks()
    run_parent_expansion_checks()
    run_authoritative_rollback_checks()
    run_reader_acl_negative_checks()
    run_underfilled_filter_checks()
    run_operator_global_reader_checks()
    print("Eval dataset V2.1 corrected case checks passed.")


if __name__ == "__main__":
    run_checks()
