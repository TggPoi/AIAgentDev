"""从不可变 V2.1.4 派生修复语义标注的 V2.1.5 candidate。"""

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
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.4.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.5.json"
)
DATASET_VERSION = "2.1.5"
CREATED_AT = "2026-08-28T20:00:00+08:00"
ANNOTATED_BY = "codex:v2.1.5-semantic-authority-corrector"


def _case_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["case_id"]: case for case in payload["cases"]}


def _reset_candidate_identity(payload: dict[str, Any]) -> None:
    payload.update(
        {
            "dataset_version": DATASET_VERSION,
            "lifecycle": "candidate",
            "content_sha256": "",
            "name": "stage11_acl_rag_eval_v2_1_5_candidate",
            "description": (
                "V2.1.5 candidate：从不可变 V2.1.4 派生，补齐明确漏标的"
                "语义相关 Chunk，并将语义相关全集与必须命中的权威来源分离。"
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
                "review_note": "等待 human:TGG 对 V2.1.5 修正内容进行人工审核。",
            }
        )


def _fix_toon_semantic_qrels(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_longdocs_toon_production_multi_source"]
    word_source, pdf_source = deepcopy(case["expected_sources"])
    word_source.update(
        {
            "logical_chunk_ids": [
                "chunk_f6b5cbc02b515961",
                "chunk_6f31fe460a4ff15b",
            ],
            "section_keywords": [
                "5.1 UE5.8 Substrate Toon Shading",
                "NPR 光照底座",
            ],
        }
    )
    pdf_source.update(
        {
            "logical_chunk_ids": [
                "chunk_519c11634c2ef350",
                "chunk_835a2d68531e3688",
                "chunk_6fb6c9494ea6327d",
            ],
            "section_keywords": [
                "Page 10 Toon Shader 基础能力",
                "Page 10 Toon Profile 分段曲线",
                "Page 11 不是完整 Anime Pipeline",
            ],
        }
    )
    relevant = [
        *word_source["logical_chunk_ids"],
        *pdf_source["logical_chunk_ids"],
    ]
    case.update(
        {
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": [
                "chunk_f6b5cbc02b515961",
                "chunk_519c11634c2ef350",
            ],
            "expected_sources": [word_source, pdf_source],
            "note": (
                "V2.1.5 补入 Word 官方能力主块与 PDF Toon Profile 续块，"
                "移除只作全书背景总结、不能直接回答能力边界的 Chunk；"
                "权威集合各保留一份长文档的主证据。"
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
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 22: 8.1 Mover",
                "Page 26: 旧技术迁移矩阵",
                "Page 27: 10.1 最容易误判的三件事",
            ],
        }
    )
    case.update(
        {
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": [
                "chunk_00499a8f184e0ffd",
                "chunk_0c20779a4e397e0d",
            ],
            "expected_sources": [source],
            "note": (
                "V2.1.5 将第 10 章迁移矩阵纳入语义相关全集；"
                "权威来源仍限定为问题点名的 8.1 与 10.1 主证据。"
            ),
        }
    )


def _fix_nne_authoritative_subset(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_nne_training_runtime"]
    case.update(
        {
            "authoritative_logical_chunk_ids": [
                "chunk_fa9d79af16538c98",
                "chunk_dfec29f8331e1bd6",
                "chunk_c80e0436eac5de05",
            ],
            "note": (
                "V2.1.5 保留 5 个语义相关 qrels；权威集合只要求命中"
                "Learning Agents 状态、训练/ONNX 主流程和 NNE Runtime 主说明，"
                "不再强制同时命中两个重复图文续块。"
            ),
        }
    )


def _fix_underfilled_authoritative_subset(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_public_acl_underfilled"]
    facts = deepcopy(case["required_key_facts"])
    facts.insert(
        2,
        {
            "fact_id": "test_directory_mapping",
            "text": (
                "测试目录包含 art、product_planning、development 和 public；"
                "前三者写入对应 allowed_departments，public 写入 visibility=public。"
            ),
            "weight": 1.0,
            "critical": True,
        },
    )
    case.update(
        {
            "authoritative_logical_chunk_ids": [
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
            ],
            "required_key_facts": facts,
            "note": (
                "V2.1.5 继续把限定 public 文档的 16 个子块作为全文语义"
                "相关全集；权威集合只保留问题逐项要求的 12 个章节证据，"
                "并补充测试目录映射这一缺失的完整性事实。"
            ),
        }
    )


def build_payload() -> dict[str, Any]:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    payload = deepcopy(source)
    _reset_candidate_identity(payload)
    cases = _case_map(payload)
    _fix_toon_semantic_qrels(cases)
    _fix_mover_semantic_qrels(cases)
    _fix_nne_authoritative_subset(cases)
    _fix_underfilled_authoritative_subset(cases)
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
    print(f"V2.1.5 candidate 已写入：{OUTPUT_PATH}")
    print(f"cases={len(dataset.cases)} lifecycle={dataset.lifecycle}")
    print(f"content_sha256={dataset.content_sha256}")


if __name__ == "__main__":
    main()
