from dataclasses import replace

from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RetrievedDoc

logger = get_logger(__name__)

def reciprocal_rank_fusion(
    doc_lists: list[list[RetrievedDoc]],
    top_k: int,
    k: int = 60,
) -> list[RetrievedDoc]:
    # 保存每个 doc.id 的 RRF 融合分数
    rrf_scores: dict[str, float] = {}
    # 保存每个 doc.id 最终要保留的 RetrievedDoc 对象
    doc_by_id: dict[str, RetrievedDoc] = {}
    # 保存每个 doc.id 目前见过的最高原始 score（保存的是 原始召回 score，不是 RRF 分数）
    best_original_score_by_id: dict[str, float] = {}
    # 记录每个 doc_id 来自哪些来源
    sources_by_id: dict[str, set[str]] = {}

    for docs in doc_lists:
        for rank, doc in enumerate(docs, start=1):

            sources = sources_by_id.setdefault(doc.id, set())

            if doc.retrieval_sources:
                sources.update(doc.retrieval_sources)
            else:
                sources.add(doc.source)

            # 取出这个文档之前已经累计过的 RRF 分数；如果还没有出现过，就从 0.0 开始。
            rrf_scores[doc.id] = rrf_scores.get(doc.id, 0.0) + 1.0 / (k + rank)

            if doc.id not in doc_by_id:
                doc_by_id[doc.id] = doc
                best_original_score_by_id[doc.id] = doc.score
                continue

            # 覆盖原始分数和doc文档对象
            if doc.score > best_original_score_by_id[doc.id]:
                doc_by_id[doc.id] = doc
                best_original_score_by_id[doc.id] = doc.score

    fused_docs: list[RetrievedDoc] = []

    for doc_id, rrf_score in rrf_scores.items():
        original_doc = doc_by_id[doc_id]
        # 从doc_by_id中取出原始doc文档对象，匹配对应的rrf分数
        fused_docs.append(
            replace(
                original_doc,
                score=rrf_score,
                retrieval_sources=sorted(sources_by_id.get(doc_id, {original_doc.source})),
                scores=replace(
                    original_doc.scores,
                    rrf_score=rrf_score,
                ),
            )
        )

    # 按照rrf分数从高到低排序，并且截断
    fused_docs.sort(key=lambda doc: doc.score, reverse=True)
    output_docs = fused_docs[:top_k]

    logger.info(
        "rag_retrieval %s",
        format_log_fields(
            event="rag.retrieval.rrf.score",
            input_doc_count=sum(len(docs) for docs in doc_lists),
            unique_doc_count=len(rrf_scores),
            output_doc_count=len(output_docs),
            top_k=top_k,
            rrf_k=k,
            top_doc_ids=[doc.id for doc in output_docs],
        ),
    )

    return output_docs
