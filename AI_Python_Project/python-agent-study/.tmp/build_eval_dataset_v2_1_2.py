"""从不可变 Golden V2.1.1 构建已完成人工审核的 V2.1.2 Golden。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from fast_app.evaluation.cases.loader import (
    load_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import RagEvalDataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.2.json"
)
INVENTORY_PATH = Path(__file__).parent / "knowledge_inventory.json"
DATASET_VERSION = "2.1.2"
CREATED_AT = "2026-08-13T12:00:00+08:00"
ANNOTATED_BY = "codex:v2.1.2-relevance-authority-corrector"
REVIEWED_BY = "human:TGG"
REVIEWED_AT = "2026-08-13T01:10:36+08:00"


INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
BY_CHUNK = {item["logical_record_id"]: item for item in INVENTORY}


def inventory_chunk(logical_chunk_id: str) -> dict:
    try:
        return BY_CHUNK[logical_chunk_id]
    except KeyError as exc:
        raise SystemExit(
            f"知识版本 6 盘点中不存在 logical chunk: {logical_chunk_id}"
        ) from exc


def expected_sources(
    logical_chunk_ids: list[str],
    *,
    logical_parent_id: str | None = None,
) -> list[dict]:
    """按文档聚合已核对的语义相关 Chunk，并保留父块追溯信息。"""

    grouped: dict[str, list[dict]] = {}
    for logical_chunk_id in logical_chunk_ids:
        item = inventory_chunk(logical_chunk_id)
        grouped.setdefault(item["doc_id"], []).append(item)

    sources: list[dict] = []
    for doc_id, items in grouped.items():
        source = {
            "logical_doc_id": doc_id,
            "source_revision": items[0]["source_revision"],
            "logical_chunk_ids": [item["logical_record_id"] for item in items],
            "logical_parent_id": None,
            "matched_logical_child_ids": [],
            "source_path": items[0]["source_path"],
            "section_keywords": list(
                dict.fromkeys(str(item.get("title") or "") for item in items)
            ),
        }
        if logical_parent_id is not None:
            if any(item.get("logical_parent_id") != logical_parent_id for item in items):
                raise SystemExit("父块 case 的相关子块没有全部指向同一逻辑父块")
            source["logical_parent_id"] = logical_parent_id
            source["matched_logical_child_ids"] = list(source["logical_chunk_ids"])
        sources.append(source)
    return sources


def set_relevance(
    cases: dict[str, dict],
    case_id: str,
    *,
    relevant_chunks: list[str],
    authoritative_chunks: list[str],
    forbidden_chunks: list[str] | None = None,
    relevance_unit: str = "logical_chunk",
    relevant_parents: list[str] | None = None,
    authoritative_parents: list[str] | None = None,
) -> None:
    case = cases[case_id]
    parent_id = relevant_parents[0] if relevant_parents else None
    sources = expected_sources(relevant_chunks, logical_parent_id=parent_id)
    case.update(
        {
            "retrieval_relevance_unit": relevance_unit,
            "relevant_logical_chunk_ids": relevant_chunks,
            "relevant_logical_parent_ids": relevant_parents or [],
            "relevant_doc_ids": sorted(
                {source["logical_doc_id"] for source in sources}
            ),
            "authoritative_logical_chunk_ids": authoritative_chunks,
            "authoritative_logical_parent_ids": authoritative_parents or [],
            "forbidden_logical_chunk_ids": (
                forbidden_chunks
                if forbidden_chunks is not None
                else case["forbidden_logical_chunk_ids"]
            ),
            "expected_sources": sources,
        }
    )


def build_payload() -> dict:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    payload = deepcopy(source)
    payload.update(
        {
            "dataset_version": DATASET_VERSION,
            "lifecycle": "golden",
            "content_sha256": "",
            "name": "stage11_acl_rag_eval_v2_1_2_golden",
            "description": (
                "V2.1.2 Golden：按人工批准的 V2.1.1 派生，修正父块相关性身份，"
                "补充只读调查确认的语义相关 Chunk，并把语义相关性与权威/禁止来源"
                "判定拆开。全部语义变化已经 human:TGG 人工审核通过。"
            ),
            "created_at": CREATED_AT,
        }
    )

    cases = {case["case_id"]: case for case in payload["cases"]}
    for case in cases.values():
        original_relevant = list(case["relevant_logical_chunk_ids"])
        case.update(
            {
                "dataset_version": DATASET_VERSION,
                "retrieval_relevance_unit": "logical_chunk",
                "relevant_logical_parent_ids": [],
                "authoritative_logical_chunk_ids": original_relevant,
                "authoritative_logical_parent_ids": [],
                "annotation_method": "model_assisted",
                "annotated_by": ANNOTATED_BY,
                "review_status": "approved",
                "reviewed_by": REVIEWED_BY,
                "reviewed_at": REVIEWED_AT,
                "review_note": (
                    "人工确认 V2.1.2 的父块身份、语义相关全集、权威来源、"
                    "禁止来源及冲突知识替换方案；批准用于知识版本 6 的正式评测。"
                ),
            }
        )

    set_relevance(
        cases,
        "reader_es_milvus_parent_child_expansion",
        relevant_chunks=[
            "chunk_d26c5a41d92d12dd",
            "chunk_7f03bd18244ce719",
            "chunk_315425934f0cd8b4",
        ],
        authoritative_chunks=[],
        relevance_unit="logical_parent",
        relevant_parents=["parent_19d48d66c7b9141e"],
        authoritative_parents=["parent_19d48d66c7b9141e"],
    )
    set_relevance(
        cases,
        "reader_gitlab_rollback_authoritative",
        relevant_chunks=[
            "chunk_296a2380e2d87791",
            "chunk_bb13f7442fb8745c",
            "chunk_58906be3fa1f61ce",
        ],
        authoritative_chunks=["chunk_296a2380e2d87791"],
        forbidden_chunks=["chunk_bb13f7442fb8745c", "chunk_58906be3fa1f61ce"],
    )
    rollback = cases["reader_gitlab_rollback_authoritative"]
    rollback["constraints"] = list(
        dict.fromkeys(
            [
                *rollback["constraints"],
                "只能采用 GitLab Revert Commit 与 MR 的权威回滚流程，不得采用直接修改数据库版本指针的旧方案。",
            ]
        )
    )
    rollback["hard_gate_labels"] = list(
        dict.fromkeys(
            [
                *rollback["hard_gate_labels"],
                "authoritative_source_required",
                "forbidden_source_retrieved",
            ]
        )
    )
    set_relevance(
        cases,
        "reader_webhook_worker_multi_source",
        relevant_chunks=[
            "chunk_dea252b8024f71e1",
            "chunk_0452d406311e7d7b",
            "chunk_1bad0a3f3f2ac852",
            "chunk_cb80f57b1ca93ed4",
            "chunk_6a62985afb908b63",
        ],
        authoritative_chunks=[
            "chunk_dea252b8024f71e1",
            "chunk_0452d406311e7d7b",
        ],
    )
    set_relevance(
        cases,
        "reader_milvus_index_check",
        relevant_chunks=["chunk_4e797af9683c05c2", "chunk_550d5fb338ceb75a"],
        authoritative_chunks=["chunk_4e797af9683c05c2"],
    )
    set_relevance(
        cases,
        "reader_visibility_positive",
        relevant_chunks=[
            "chunk_f8a53eabbef5743c",
            "chunk_e61f024c79efd70d",
            "chunk_ef414e98d607ed62",
            "chunk_0516c4cb2db53ade",
        ],
        authoritative_chunks=[
            "chunk_f8a53eabbef5743c",
            "chunk_e61f024c79efd70d",
        ],
    )
    set_relevance(
        cases,
        "reader_worker_failure_recovery",
        relevant_chunks=["chunk_bf7e323eb34c4674", "chunk_31f6a030be67925c"],
        authoritative_chunks=["chunk_bf7e323eb34c4674"],
    )
    return payload


def main() -> None:
    payload = build_payload()
    sealed = seal_eval_dataset_payload(payload)
    RagEvalDataset.model_validate(sealed)
    OUTPUT_PATH.write_text(
        json.dumps(sealed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reloaded = load_eval_dataset(
        OUTPUT_PATH,
        verify_source_revision=True,
        repository_root=PROJECT_ROOT,
    )
    print(f"V2.1.2 Golden 已写入：{OUTPUT_PATH}")
    print(f"cases={len(reloaded.cases)} lifecycle={reloaded.lifecycle}")
    print(f"content_sha256={reloaded.content_sha256}")
    print(f"source_revision={reloaded.source_revision}")


if __name__ == "__main__":
    main()
