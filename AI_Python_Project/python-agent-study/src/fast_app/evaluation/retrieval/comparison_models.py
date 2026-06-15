from dataclasses import dataclass, field

from fast_app.evaluation.retrieval.models import RetrievalDatasetReport


@dataclass(frozen=True)
class RetrievalVariantReport:
    """某一种检索策略的评测结果。

    例如：
    - vector：只看 Milvus 向量召回
    - keyword：只看 ElasticSearch 关键词召回
    - rrf：看 Milvus + ES 融合后的结果
    - rerank：看融合结果再精排后的结果
    """

    name: str
    description: str
    report: RetrievalDatasetReport


@dataclass(frozen=True)
class HybridRetrievalComparisonReport:
    """同一批评测集下，多种检索策略的横向对比报告。"""

    dataset_name: str
    variants: list[RetrievalVariantReport] = field(default_factory=list)

