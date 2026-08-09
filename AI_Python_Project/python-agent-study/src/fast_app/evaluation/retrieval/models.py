from dataclasses import dataclass, field
from typing import Literal

from fast_app.evaluation.contracts import MetricResult


RetrievalStage = Literal["vector", "keyword", "rrf", "rerank"]


@dataclass(frozen=True)
class RetrievalMetricInput:
    """检索层四项指标共用的单 case 输入快照。

    身份统一使用可跨重建保持稳定的逻辑子块 ID。返回列表保留原始顺序和重复项，
    由指标实现按契约去重；黄金相关 ID 则必须在数据集入口完成去重。
    """

    case_id: str
    retrieval_stage: RetrievalStage
    requested_k: int
    retrieved_logical_chunk_ids: list[str]
    relevant_logical_chunk_ids: list[str]
    unique_retrieved_count: int = field(init=False)
    underfilled: bool = field(init=False)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("retrieval metric case_id 不能为空")
        if self.requested_k < 1:
            raise ValueError("retrieval metric requested_k 必须大于等于 1")
        if len(self.retrieved_logical_chunk_ids) > self.requested_k:
            raise ValueError("retrieved logical chunk 数量不能超过 requested_k")
        if any(not item.strip() for item in self.retrieved_logical_chunk_ids):
            raise ValueError("retrieved logical chunk ID 不能为空")
        if any(not item.strip() for item in self.relevant_logical_chunk_ids):
            raise ValueError("relevant logical chunk ID 不能为空")
        if len(set(self.relevant_logical_chunk_ids)) != len(
            self.relevant_logical_chunk_ids
        ):
            raise ValueError("relevant logical chunk ID 不能重复")

        unique_count = len(dict.fromkeys(self.retrieved_logical_chunk_ids))
        object.__setattr__(self, "unique_retrieved_count", unique_count)
        object.__setattr__(self, "underfilled", unique_count < self.requested_k)


@dataclass(frozen=True)
class RetrievalHit:
    """单个命中的检索结果。

    这个模型不是原始 RetrievedDoc，而是“评测视角下的命中记录”：
    - RetrievedDoc 关心检索结果本身。
    - RetrievalHit 关心这个结果为什么算命中、排第几名。
    """

    doc_id: str
    # 命中结果在原始检索结果 docs 中排第几
    rank: int
    matched_by: list[str] = field(default_factory=list)
    score: float | None = None
    source_path: str | None = None
    section_path: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalCaseResult:
    """单条评测样例的检索评测结果。

    一条 RagEvalCase 会得到一个 RetrievalCaseResult。
    这里不保存 answer，因为阶段 11-3 只评测“有没有找回正确材料”。
    """

    case_id: str
    question: str
    case_type: str
    retrieved_count: int
    expected_source_count: int
    hit_count: int
    recall_at_k: float
    reciprocal_rank: float
    first_hit_rank: int | None
    passed: bool
    hits: list[RetrievalHit] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalDatasetReport:
    """一批评测样例的检索评测汇总。

    后续阶段会把多条 case 的结果输出成 Markdown / JSON 报告。
    当前先用 dataclass 保存聚合指标。
    """

    case_count: int
    evaluated_case_count: int
    skipped_case_count: int
    passed_case_count: int
    failed_case_count: int
    mean_recall_at_k: float
    mean_mrr: float
    results: list[RetrievalCaseResult] = field(default_factory=list)
    metric_results: list[MetricResult] = field(default_factory=list)
