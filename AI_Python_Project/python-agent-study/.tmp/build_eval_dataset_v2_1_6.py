"""从不可变 V2.1.5 派生补全语义 qrels 的 V2.1.6 candidate。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from fast_app.evaluation.cases.loader import (
    load_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import RagEvalDataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.5.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.6.json"
)
DATASET_VERSION = "2.1.6"
CREATED_AT = "2026-08-29T18:00:00+08:00"
ANNOTATED_BY = "codex:v2.1.6-qrel-completeness-corrector"


def _case_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["case_id"]: case for case in payload["cases"]}


def _reset_candidate_identity(payload: dict[str, Any]) -> None:
    payload.update(
        {
            "dataset_version": DATASET_VERSION,
            "lifecycle": "candidate",
            "content_sha256": "",
            "name": "stage11_acl_rag_eval_v2_1_6_candidate",
            "description": (
                "V2.1.6 candidate：从不可变 V2.1.5 派生，补齐完整语义"
                "相关集合审核确认的三个遗漏，不改变权威来源语义。"
            ),
            "created_at": CREATED_AT,
        }
    )
    for case in payload["cases"]:
        case.update(
            {
                "dataset_version": DATASET_VERSION,
                "annotation_method": "model_assisted",
                "annotated_by": ANNOTATED_BY,
                "review_status": "pending_review",
                "reviewed_by": None,
                "reviewed_at": None,
                "review_note": "等待 human:TGG 对 V2.1.6 修正内容进行人工审核。",
            }
        )


def _fix_nne_semantic_qrels(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_nne_training_runtime"]
    relevant = [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
        "chunk_1aacfb4570bf0fbe",
        "chunk_d8f7f46961b5a99e",
        "chunk_7c483a7b9ca5fe63",
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 4: 自定义模型入口链",
                "Page 13: 训练闭环与 ONNX",
                "Page 14: NNE Runtime",
                "Page 28: 选型建议",
            ],
        }
    )
    case.update(
        {
            "top_k": 6,
            "relevant_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "note": (
                "V2.1.6 补入直接说明自定义模型需经过 PyTorch、ONNX、NNE "
                "的入口链 Chunk；该 Chunk 属于语义相关证据但不是必须命中的"
                "权威主证据。相关项增至 6 个，因此 top_k 同步调整为 6。"
            ),
        }
    )


def _fix_mover_semantic_qrels(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_mover_migration"]
    relevant = [
        "chunk_00499a8f184e0ffd",
        "chunk_50f5a64967ad9d11",
        "chunk_f67c617af929dfce",
        "chunk_0c20779a4e397e0d",
        "chunk_d3e9c4a77c432371",
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 4: Mover Experimental 与 CMC 保留",
                "Page 22: 8.1 Mover",
                "Page 26: 旧技术迁移矩阵",
                "Page 27: 10.1 最容易误判的三件事",
            ],
        }
    )
    case.update(
        {
            "relevant_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "note": (
                "V2.1.6 补入直接说明 Mover 仍为 Experimental、CMC 仍应"
                "保留的 Chunk；该 Chunk 属于语义相关证据，但不替代 8.1 与"
                "10.1 两处权威主证据。"
            ),
        }
    )


def _fix_deployment_parent_qrels(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_deployment_env_parent_expansion"]
    base_source = deepcopy(case["expected_sources"][0])
    environment_source = deepcopy(base_source)
    environment_source.update(
        {
            "logical_chunk_ids": [
                "chunk_ac5579214b6a604d",
                "chunk_c4c06a13c5280044",
            ],
            "logical_parent_id": "parent_8203549515f66e1b",
            "matched_logical_child_ids": [
                "chunk_ac5579214b6a604d",
                "chunk_c4c06a13c5280044",
            ],
            "section_keywords": ["4. 环境变量配置"],
        }
    )
    dependency_source = deepcopy(base_source)
    dependency_source.update(
        {
            "logical_chunk_ids": ["chunk_e44caff2a0b48c44"],
            "logical_parent_id": "parent_1a0572e425043fdf",
            "matched_logical_child_ids": ["chunk_e44caff2a0b48c44"],
            "section_keywords": ["6. Python 依赖安装"],
        }
    )
    troubleshooting_source = deepcopy(base_source)
    troubleshooting_source.update(
        {
            "logical_chunk_ids": ["chunk_00ecace9d8c29128"],
            "logical_parent_id": "parent_948c596391bdf5cb",
            "matched_logical_child_ids": ["chunk_00ecace9d8c29128"],
            "section_keywords": ["18.1 Elasticsearch 客户端版本不兼容"],
        }
    )
    case.update(
        {
            "relevant_logical_chunk_ids": [
                "chunk_ac5579214b6a604d",
                "chunk_c4c06a13c5280044",
                "chunk_e44caff2a0b48c44",
                "chunk_00ecace9d8c29128",
            ],
            "relevant_logical_parent_ids": [
                "parent_8203549515f66e1b",
                "parent_1a0572e425043fdf",
                "parent_948c596391bdf5cb",
            ],
            "expected_sources": [
                environment_source,
                dependency_source,
                troubleshooting_source,
            ],
            "note": (
                "V2.1.6 保留环境变量父块作为唯一权威来源，并补入 Python "
                "依赖安装与 Elasticsearch 客户端版本故障排查两个直接相关"
                "父块；检索按三个逻辑父块计分。"
            ),
        }
    )


def build_payload() -> dict[str, Any]:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    payload = deepcopy(source)
    _reset_candidate_identity(payload)
    cases = _case_map(payload)
    _fix_nne_semantic_qrels(cases)
    _fix_mover_semantic_qrels(cases)
    _fix_deployment_parent_qrels(cases)
    return seal_eval_dataset_payload(payload)


def main() -> None:
    payload = build_payload()
    RagEvalDataset.model_validate(payload)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    dataset = load_eval_dataset(
        OUTPUT_PATH,
        verify_source_revision=True,
        repository_root=PROJECT_ROOT,
    )
    print(f"V2.1.6 candidate 已写入：{OUTPUT_PATH}")
    print(f"cases={len(dataset.cases)} lifecycle={dataset.lifecycle}")
    print(f"content_sha256={dataset.content_sha256}")


if __name__ == "__main__":
    main()
