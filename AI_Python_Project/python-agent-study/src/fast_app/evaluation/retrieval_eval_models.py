from dataclasses import dataclass, field


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
