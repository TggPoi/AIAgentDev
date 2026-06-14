from collections.abc import Mapping

from fast_app.domain.rag_models import RetrievedDoc
from fast_app.evaluation.eval_case_models import ExpectedSource, RagEvalCase
from fast_app.evaluation.retrieval_eval_models import (
    RetrievalCaseResult,
    RetrievalDatasetReport,
    RetrievalHit,
)


def extract_doc_section_path(doc: RetrievedDoc) -> list[str]:
    """从 RetrievedDoc.metadata 中安全提取 section_path。

    metadata 来自 ES / Milvus 等外部存储，理论上应该是 list[str]，
    但评测代码不能假设外部数据永远干净，所以这里做防御性转换。
    """

    section_path = doc.metadata.get("section_path")

    if isinstance(section_path, list):
        return [str(item) for item in section_path]

    return []


def build_retrieval_match_text(doc: RetrievedDoc) -> str:
    """构造用于关键词命中判断的文本。

    ExpectedSource.section_keywords 不是要求精确匹配某个字段，
    而是用来判断检索结果是否大概率命中了相关章节。

    所以这里把 title、section_path、content 拼在一起：
    - title 可能包含章节标题
    - section_path 可能包含上级标题路径
    - content 是 chunk 正文
    """

    section_path = extract_doc_section_path(doc)

    return "\n".join(
        [
            doc.title or "",
            " / ".join(section_path),
            doc.content,
        ]
    ).lower()


def match_expected_source(
    doc: RetrievedDoc,
    expected_source: ExpectedSource,
) -> list[str]:
    """判断一个 RetrievedDoc 是否命中一个 ExpectedSource。

    返回 list[str]，而不是 bool，是为了让报告能解释“为什么命中”。
    例如同一个 doc 可能同时通过 chunk_id 和 section_keywords 命中。
    """

    matched_by: list[str] = []

    # chunk_id 是最严格的命中方式。
    # 如果评测集已经明确写了 chunk_ids，就可以直接判断 doc.id。
    if expected_source.chunk_ids and doc.id in expected_source.chunk_ids:
        matched_by.append("chunk_id")

    # source_path 用来判断是否命中了预期原始文档。
    # 它比 chunk_id 宽松，但比只看关键词更稳定。
    doc_source_path = doc.metadata.get("source_path")
    if expected_source.source_path and doc_source_path == expected_source.source_path:
        matched_by.append("source_path")

    # section_keywords 是当前阶段最常用的宽松命中方式。
    # 因为阶段 11-2 的评测集还没有为每条问题绑定精确 chunk_id。
    if expected_source.section_keywords:
        match_text = build_retrieval_match_text(doc)
        matched_keywords = [
            keyword
            for keyword in expected_source.section_keywords
            if keyword.lower() in match_text
        ]

        if matched_keywords:
            matched_by.append("section_keywords")

    return matched_by


def evaluate_retrieval_case(
    eval_case: RagEvalCase,
    docs: list[RetrievedDoc],
) -> RetrievalCaseResult:
    """评测单条 case 的检索结果。

    docs 应该是某条 RAG 请求已经检索出来的结果列表。
    本函数只计算指标，不负责调用 Milvus / ES / Pipeline。
    """

    if eval_case.case_type != "answerable":
        # no_answer 样例主要用于后续生成评测。
        # 检索阶段先标记为跳过语义：不计算 expected source 命中。
        return RetrievalCaseResult(
            case_id=eval_case.id,
            question=eval_case.question,
            case_type=eval_case.case_type,
            retrieved_count=len(docs),
            expected_source_count=0,
            hit_count=0,
            recall_at_k=0.0,
            reciprocal_rank=0.0,
            first_hit_rank=None,
            passed=True,
            hits=[],
        )
    # 所有“命中了 expected_sources 的检索doc结果”
    hits: list[RetrievalHit] = []
    # 已经被命中的 expected_source 的编号集合
    matched_expected_indexes: set[int] = set()

    # rank 从 1 开始，标记当前命中的doc 在命中文档列表中排第几
    for rank, doc in enumerate(docs, start=1):
        # 当前这个 doc 是通过哪些规则命中的
        doc_matched_by: list[str] = []

        for expected_index, expected_source in enumerate(eval_case.expected_sources):
            # 当前 doc 对当前 expected_source”的结果，expected_source中包含source_path，section_keywords；表示这个文档具体通过哪个来源命中的
            matched_by = match_expected_source(
                doc=doc,
                expected_source=expected_source,
            )

            if matched_by:
                matched_expected_indexes.add(expected_index)
                doc_matched_by.extend(matched_by)

        if doc_matched_by:
            hits.append(
                RetrievalHit(
                    doc_id=doc.id,
                    rank=rank,
                    matched_by=sorted(set(doc_matched_by)),
                    score=doc.score,
                    source_path=_safe_str(doc.metadata.get("source_path")),
                    section_path=extract_doc_section_path(doc),
                )
            )
    # 这条 case 一共有多少个预期来源
    expected_count = len(eval_case.expected_sources)
    # 有多少个 expected_source 被命中过
    hit_count = len(matched_expected_indexes)

    # Recall@K 关注“预期来源找回了多少”。
    # 当前 K 等于传入 docs 的长度，通常来自 eval_case.top_k。
    recall_at_k = hit_count / expected_count if expected_count > 0 else 0.0

    # Reciprocal Rank 关注“第一个正确结果排得靠不靠前”。
    # 排名越靠前，分数越高；没有命中则为 0。
    first_hit_rank = hits[0].rank if hits else None # first_hit_rank 表示第一个命中的文档在原始文档中排第几
    
    # `reciprocal_rank` 是单条 case 的 第一个正确结果排名的 倒数(将排名转化为可计算的分数)
    # 例如 第一个正确命中的结果 在原始文档列表中 排第 2 名 => reciprocal_rank = 1 / 2 = 0.5
    reciprocal_rank = 1 / first_hit_rank if first_hit_rank else 0.0

    return RetrievalCaseResult(
        case_id=eval_case.id,
        question=eval_case.question,
        case_type=eval_case.case_type,
        retrieved_count=len(docs),
        expected_source_count=expected_count,
        hit_count=hit_count,
        recall_at_k=recall_at_k,
        reciprocal_rank=reciprocal_rank,
        first_hit_rank=first_hit_rank,
        passed=recall_at_k > 0,
        hits=hits,
    )


def evaluate_retrieval_dataset(
    cases: list[RagEvalCase],
    retrieved_docs_by_case_id: Mapping[str, list[RetrievedDoc]],
) -> RetrievalDatasetReport:
    """聚合多条 case 的检索评测结果。

    retrieved_docs_by_case_id 由外层提供：
    - key 是 eval case id
    - value 是这条 case 对应的 RetrievedDoc 列表

    这样指标模块不依赖具体召回来源，后续可以复用到 Milvus、ES、
    Hybrid、Rerank 前后对比等不同实验中。
    """

    results: list[RetrievalCaseResult] = []
    skipped_case_count = 0

    for eval_case in cases:
        if eval_case.case_type != "answerable":
            skipped_case_count += 1
            continue

        docs = retrieved_docs_by_case_id.get(eval_case.id, [])
        results.append(
            evaluate_retrieval_case(
                eval_case=eval_case,
                docs=docs,
            )
        )

    evaluated_case_count = len(results)
    passed_case_count = sum(1 for result in results if result.passed)
    failed_case_count = evaluated_case_count - passed_case_count

    mean_recall_at_k = (
        sum(result.recall_at_k for result in results) / evaluated_case_count
        if evaluated_case_count
        else 0.0
    )
    mean_mrr = (
        sum(result.reciprocal_rank for result in results) / evaluated_case_count
        if evaluated_case_count
        else 0.0
    )

    return RetrievalDatasetReport(
        case_count=len(cases),
        evaluated_case_count=evaluated_case_count,
        skipped_case_count=skipped_case_count,
        passed_case_count=passed_case_count,
        failed_case_count=failed_case_count,
        mean_recall_at_k=mean_recall_at_k,
        mean_mrr=mean_mrr,
        results=results,
    )


def _safe_str(value: object) -> str | None:
    if value is None:
        return None

    return str(value)
