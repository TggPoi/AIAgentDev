from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.components.retrievers.milvus_vector_retriever import MilvusVectorRetriever
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.evaluation.retrieval.elasticsearch_keyword import (
    evaluate_elasticsearch_keyword_dataset,
    retrieve_elasticsearch_docs_for_case,
)
from fast_app.evaluation.cases.models import RagEvalCase, RagEvalDataset
from fast_app.evaluation.retrieval.milvus_vector import (
    evaluate_milvus_vector_dataset,
    retrieve_milvus_docs_for_case,
)
from fast_app.evaluation.retrieval.comparison_models import (
    HybridRetrievalComparisonReport,
    RetrievalVariantReport,
)
from fast_app.evaluation.retrieval.models import RetrievalDatasetReport
from fast_app.evaluation.retrieval.metrics import evaluate_retrieval_dataset
from fast_app.services.rag.retrieval_fusion import reciprocal_rank_fusion


async def retrieve_rrf_hybrid_docs_for_case(
    eval_case: RagEvalCase,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
) -> list[RetrievedDoc]:
    """获取单条 case 的 RRF 融合结果。

    这里先分别执行 vector / keyword 两路召回，再把两路结果交给 RRF。
    它对应的是 hybrid 检索里“融合但还没 rerank”的版本。
    """

    vector_docs = await retrieve_milvus_docs_for_case(
        eval_case=eval_case,
        retriever=vector_retriever,
    )
    keyword_docs = await retrieve_elasticsearch_docs_for_case(
        eval_case=eval_case,
        retriever=keyword_retriever,
    )
    # 计算RRF分数
    return reciprocal_rank_fusion(
        doc_lists=[vector_docs, keyword_docs],
        top_k=eval_case.top_k,
    )


async def retrieve_reranked_hybrid_docs_for_case(
    eval_case: RagEvalCase,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
    reranker: BaseReranker,
) -> list[RetrievedDoc]:
    """获取单条 case 的 RRF + rerank 结果。

    rerank 的输入不是原始 vector / keyword 结果，而是 RRF 已经融合后的结果。
    所以这个版本用于观察 reranker 是否把正确结果排得更靠前。
    """

    rrf_docs = await retrieve_rrf_hybrid_docs_for_case(
        eval_case=eval_case,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
    )
    # 获取rerank模型排序后的文档顺序 和分数
    return await reranker.rerank(
        query=eval_case.question,
        docs=rrf_docs,
        top_k=eval_case.top_k,
    )


async def evaluate_rrf_hybrid_dataset(
    dataset: RagEvalDataset,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
) -> RetrievalDatasetReport:
    """评测整个数据集的 RRF 融合检索质量。"""

    # 评测案例id 和 检索文档集合 映射
    retrieved_docs_by_case_id: dict[str, list[RetrievedDoc]] = {}

    for eval_case in dataset.cases:
        if eval_case.case_type != "answerable":
            continue
        
        docs = await retrieve_rrf_hybrid_docs_for_case(
            eval_case=eval_case,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        )
        retrieved_docs_by_case_id[eval_case.id] = docs

    return evaluate_retrieval_dataset(
        cases=dataset.cases,
        retrieved_docs_by_case_id=retrieved_docs_by_case_id,
    )


async def evaluate_reranked_hybrid_dataset(
    dataset: RagEvalDataset,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
    reranker: BaseReranker,
) -> RetrievalDatasetReport:
    """评测整个数据集的 RRF + rerank 检索质量。"""

    retrieved_docs_by_case_id: dict[str, list[RetrievedDoc]] = {}

    for eval_case in dataset.cases:
        if eval_case.case_type != "answerable":
            continue

        docs = await retrieve_reranked_hybrid_docs_for_case(
            eval_case=eval_case,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            reranker=reranker,
        )
        retrieved_docs_by_case_id[eval_case.id] = docs

    return evaluate_retrieval_dataset(
        cases=dataset.cases,
        retrieved_docs_by_case_id=retrieved_docs_by_case_id,
    )

# 对比四条检索链路的评测结果入口
async def compare_hybrid_retrieval_dataset(
    dataset: RagEvalDataset,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
    reranker: BaseReranker,
) -> HybridRetrievalComparisonReport:
    """对同一批评测集执行 vector / keyword / RRF / rerank 横向对比。

    这个函数是阶段 11-6 的核心。
    它不新增新的指标，而是复用阶段 11-3 的 RetrievalDatasetReport，
    让四种检索策略在同一批 case 下可以公平比较。
    """
    # milvus检索评测报告
    vector_report = await evaluate_milvus_vector_dataset(
        dataset=dataset,
        retriever=vector_retriever,
    )
    # es检索评测报告
    keyword_report = await evaluate_elasticsearch_keyword_dataset(
        dataset=dataset,
        retriever=keyword_retriever,
    )
    # milvus + es + rrf 检索评测报告
    rrf_report = await evaluate_rrf_hybrid_dataset(
        dataset=dataset,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
    )
    # milvus + es + rrf + rerank 检索评测报告
    rerank_report = await evaluate_reranked_hybrid_dataset(
        dataset=dataset,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        reranker=reranker,
    )

    return HybridRetrievalComparisonReport(
        dataset_name=dataset.name,
        variants=[
            RetrievalVariantReport(
                name="vector",
                description="Milvus 单路向量召回",
                report=vector_report,
            ),
            RetrievalVariantReport(
                name="keyword",
                description="ElasticSearch 单路关键词召回",
                report=keyword_report,
            ),
            RetrievalVariantReport(
                name="rrf",
                description="Milvus + ElasticSearch 的 RRF 融合结果",
                report=rrf_report,
            ),
            RetrievalVariantReport(
                name="rerank",
                description="RRF 融合后再经过 reranker 的结果",
                report=rerank_report,
            ),
        ],
    )

