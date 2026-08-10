from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fast_app.evaluation.cases.models import (
    EVAL_DATASET_SCHEMA_VERSION,
    ExpectedSource,
    RagEvalCase,
    RagEvalDataset,
    RequiredKeyFact,
)
from fast_app.schemas.rag_chat_schema import RagRetrievalFilters, RetrievalMode


class LegacyDatasetMigrationError(ValueError):
    """旧数据缺少逻辑身份或关键事实，无法无损迁移为 V2 candidate。"""


class DatasetIntegrityError(ValueError):
    """V2 数据集内容哈希或语料 revision 与声明不一致。"""


class DatasetReviewRequiredError(ValueError):
    """调用方要求黄金数据，但文件仍包含未审核 candidate。"""


class _LegacyExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str | None = Field(
        default=None,
        description="Legacy 期望来源路径；迁移后仅保留作人工追溯。",
    )
    section_keywords: list[str] = Field(
        default_factory=list,
        description="Legacy 章节关键词；迁移后仅保留作诊断线索。",
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Legacy chunk ID；只能迁移为待人工确认的逻辑 ID 候选。",
    )


class _LegacyRagEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Legacy case 唯一 ID。")
    case_type: Literal["answerable", "no_answer"] = Field(
        description="Legacy 可回答性分类。",
    )
    question: str = Field(min_length=1, description="Legacy 用户问题。")
    mode: RetrievalMode = Field(default="hybrid", description="Legacy 检索模式。")
    top_k: int = Field(default=5, ge=1, le=20, description="Legacy 指标 K。")
    candidate_k: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="Legacy 每路候选数。",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Legacy 最低检索分数。",
    )
    filters: RagRetrievalFilters = Field(
        default_factory=RagRetrievalFilters,
        description="Legacy 非安全性内容过滤条件。",
    )
    expected_sources: list[_LegacyExpectedSource] = Field(
        default_factory=list,
        description="Legacy 相关来源线索。",
    )
    expected_answer_keywords: list[str] = Field(
        default_factory=list,
        description="Legacy 回答关键词。",
    )
    forbidden_answer_keywords: list[str] = Field(
        default_factory=list,
        description="Legacy 回答禁止词。",
    )
    note: str = Field(default="", description="Legacy case 说明。")


class _LegacyRagEvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Legacy 数据集名称。")
    description: str = Field(default="", description="Legacy 数据集说明。")
    knowledge_base_dir: str = Field(
        min_length=1,
        description="Legacy 本地知识库目录。",
    )
    cases: list[_LegacyRagEvalCase] = Field(
        min_length=1,
        description="Legacy 评测 case 列表。",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def calculate_dataset_content_sha256(payload: dict[str, Any]) -> str:
    """计算排除 content_sha256 自身后的规范化 JSON 哈希。"""

    normalized = deepcopy(payload)
    normalized.pop("content_sha256", None)
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


def seal_eval_dataset_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """返回带有最新 content_sha256 的数据副本，不修改调用方对象。"""

    sealed = deepcopy(payload)
    sealed["content_sha256"] = calculate_dataset_content_sha256(sealed)
    return sealed


def compute_directory_source_revision(path: str | Path) -> str:
    """按相对路径和原始字节计算可重建的本地语料 revision。"""

    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"knowledge base directory 不存在: {root}")

    digest = hashlib.sha256()
    files = sorted(item for item in root.rglob("*") if item.is_file())
    if not files:
        raise ValueError(f"knowledge base directory 没有文件: {root}")
    for item in files:
        relative_path = item.relative_to(root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def verify_dataset_source_revision(
    dataset: RagEvalDataset,
    *,
    repository_root: str | Path | None = None,
) -> None:
    """对本地 SHA-256 revision 做显式校验；其他 revision 交给 Worker Adapter。"""

    if not dataset.source_revision.startswith("sha256:"):
        return
    knowledge_base_dir = Path(dataset.knowledge_base_dir)
    if not knowledge_base_dir.is_absolute() and repository_root is not None:
        knowledge_base_dir = Path(repository_root) / knowledge_base_dir
    actual = compute_directory_source_revision(knowledge_base_dir)
    if actual != dataset.source_revision:
        raise DatasetIntegrityError(
            "knowledge source_revision 不匹配: "
            f"expected={dataset.source_revision}, actual={actual}"
        )


def _validate_v2_integrity(raw_data: dict[str, Any]) -> None:
    expected = raw_data.get("content_sha256")
    if not isinstance(expected, str):
        raise DatasetIntegrityError("V2 数据集缺少 content_sha256")
    actual = calculate_dataset_content_sha256(raw_data)
    if expected != actual:
        raise DatasetIntegrityError(
            f"dataset content_sha256 不匹配: expected={expected}, actual={actual}"
        )


def _migrate_legacy_source(
    case: _LegacyRagEvalCase,
    source: _LegacyExpectedSource,
    index: int,
) -> ExpectedSource:
    logical_ids = list(dict.fromkeys(value.strip() for value in source.chunk_ids))
    if not logical_ids or any(not value for value in logical_ids):
        raise LegacyDatasetMigrationError(
            f"legacy case {case.id!r} 的 expected source 缺少可迁移 chunk_ids"
        )
    return ExpectedSource(
        logical_doc_id=f"legacy-unresolved:{case.id}:source-{index}",
        source_revision="legacy:unversioned",
        logical_chunk_ids=logical_ids,
        source_path=source.source_path or "legacy:unresolved",
        section_keywords=source.section_keywords,
    )


def migrate_legacy_eval_dataset(raw_data: dict[str, Any]) -> RagEvalDataset:
    """把 V1 JSON 显式转换为不可冒充黄金集的 V2 candidate。"""

    legacy = _LegacyRagEvalDataset.model_validate(raw_data)
    dataset_version = "1.0.0-legacy"
    source_revision = "legacy:unversioned"
    cases: list[RagEvalCase] = []

    for legacy_case in legacy.cases:
        answerable = legacy_case.case_type == "answerable"
        expected_sources = [
            _migrate_legacy_source(legacy_case, source, index)
            for index, source in enumerate(legacy_case.expected_sources, start=1)
        ]
        relevant_logical_ids = list(
            dict.fromkeys(
                logical_id
                for source in expected_sources
                for logical_id in source.logical_chunk_ids
            )
        )
        relevant_doc_ids = [source.logical_doc_id for source in expected_sources]
        if answerable and not legacy_case.expected_answer_keywords:
            raise LegacyDatasetMigrationError(
                f"legacy case {legacy_case.id!r} 缺少可迁移的答案关键事实"
            )

        scenario_tags: list[str] = [
            "answerable" if answerable else "unanswerable"
        ]
        if not answerable:
            scenario_tags.append("no_result")

        cases.append(
            RagEvalCase(
                case_id=legacy_case.id,
                dataset_version=dataset_version,
                metric_profile="rag",
                question=legacy_case.question,
                answerable=answerable,
                expected_route="rag_answer" if answerable else "rag_no_answer",
                eval_principal_id="eval:legacy-unscoped",
                knowledge_version=0,
                source_revision=source_revision,
                mode=legacy_case.mode,
                top_k=legacy_case.top_k,
                candidate_k=legacy_case.candidate_k,
                min_score=legacy_case.min_score,
                filters=legacy_case.filters.model_dump(),
                relevant_logical_chunk_ids=relevant_logical_ids,
                relevant_doc_ids=relevant_doc_ids,
                expected_sources=expected_sources,
                required_key_facts=[
                    RequiredKeyFact(
                        fact_id=f"legacy-keyword-{index}",
                        text=keyword,
                        weight=1.0,
                    )
                    for index, keyword in enumerate(
                        legacy_case.expected_answer_keywords,
                        start=1,
                    )
                ],
                question_intent=(
                    "legacy case 待人工补充问题意图" if answerable else None
                ),
                constraints=["仅使用当前身份可见的知识库证据"],
                hard_gate_labels=[],
                scenario_tags=scenario_tags,
                expected_answer_keywords=legacy_case.expected_answer_keywords,
                forbidden_answer_keywords=legacy_case.forbidden_answer_keywords,
                annotation_method="legacy_migration",
                annotated_by=f"legacy-dataset:{legacy.name}",
                review_status="pending_review",
                note=(
                    f"{legacy_case.note} "
                    "由 V1 自动迁移；逻辑文档身份、知识版本和关键事实均待人工复核。"
                ).strip(),
            )
        )

    payload = {
        "schema_version": EVAL_DATASET_SCHEMA_VERSION,
        "dataset_id": legacy.name,
        "dataset_version": dataset_version,
        "lifecycle": "candidate",
        "name": legacy.name,
        "description": (
            f"{legacy.description} 由 legacy V1 自动迁移，仅用于兼容读取。"
        ).strip(),
        "knowledge_base_dir": legacy.knowledge_base_dir,
        "source_revision": source_revision,
        "created_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(),
        "cases": [case.model_dump(mode="json") for case in cases],
    }
    return RagEvalDataset.model_validate(seal_eval_dataset_payload(payload))


def load_eval_dataset(
    path: str | Path,
    *,
    verify_source_revision: bool = False,
    repository_root: str | Path | None = None,
) -> RagEvalDataset:
    """读取 V2 或显式迁移 legacy 数据，统一返回 canonical V2 模型。"""

    dataset_path = Path(path)
    raw_data = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("评测数据集根节点必须是 JSON object")

    schema_version = raw_data.get("schema_version")
    if schema_version == EVAL_DATASET_SCHEMA_VERSION:
        _validate_v2_integrity(raw_data)
        dataset = RagEvalDataset.model_validate(raw_data)
    elif schema_version is not None:
        raise ValueError(
            f"不支持的 Eval dataset schema_version: {schema_version!r}"
        )
    else:
        dataset = migrate_legacy_eval_dataset(raw_data)

    if verify_source_revision:
        verify_dataset_source_revision(dataset, repository_root=repository_root)
    return dataset


def load_golden_eval_dataset(
    path: str | Path,
    *,
    verify_source_revision: bool = True,
    repository_root: str | Path | None = None,
) -> RagEvalDataset:
    """只允许已人工批准且满足完整场景矩阵的数据进入正式评测。"""

    dataset = load_eval_dataset(
        path,
        verify_source_revision=verify_source_revision,
        repository_root=repository_root,
    )
    if dataset.lifecycle != "golden":
        raise DatasetReviewRequiredError(
            f"dataset {dataset.dataset_id}@{dataset.dataset_version} 尚未转为 golden"
        )
    return dataset
