from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.evaluation.cases.models import RagEvalCase, RagEvalDataset
from fast_app.evaluation.retrieval.milvus_vector import build_retrieval_options_from_eval_case
from fast_app.evaluation.retrieval.models import (
    RetrievalCaseResult,
    RetrievalDatasetReport,
)
from fast_app.evaluation.retrieval.metrics import (
    evaluate_retrieval_case,
    evaluate_retrieval_dataset,
)


async def retrieve_elasticsearch_docs_for_case(
    eval_case: RagEvalCase,
    retriever: ElasticsearchKeywordRetriever,
) -> list[RetrievedDoc]:
    """为单条评测样例执行 ElasticSearch 关键词召回。

    ElasticsearchKeywordRetriever 内部会按 candidate_k 查询 ES。
    这里再截取 top_k，是为了让 Recall@K / MRR 中的 K 和 eval_case.top_k 一致。
    """

    options = build_retrieval_options_from_eval_case(eval_case)
    docs = await retriever.retrieve(eval_case.question, options)

    return docs[: eval_case.top_k]


async def evaluate_elasticsearch_keyword_case(
    eval_case: RagEvalCase,
    retriever: ElasticsearchKeywordRetriever,
) -> RetrievalCaseResult:
    """评测单条 case 的 ES 关键词召回质量。

    这个函数只负责把 ES 召回结果接到通用指标函数上。
    指标计算仍然由 evaluate_retrieval_case 负责。
    """

    docs = await retrieve_elasticsearch_docs_for_case(
        eval_case=eval_case,
        retriever=retriever,
    )

    return evaluate_retrieval_case(
        eval_case=eval_case,
        docs=docs,
    )


async def evaluate_elasticsearch_keyword_dataset(
    dataset: RagEvalDataset,
    retriever: ElasticsearchKeywordRetriever,
) -> RetrievalDatasetReport:
    """评测整个数据集的 ES 单路关键词召回质量。

    no_answer 样例当前主要服务于后续生成评测，所以这里不请求 ES。
    只把 answerable 样例的 RetrievedDoc 列表交给 evaluate_retrieval_dataset。
    """

    retrieved_docs_by_case_id: dict[str, list[RetrievedDoc]] = {}

    for eval_case in dataset.cases:
        if eval_case.case_type != "answerable":
            continue

        docs = await retrieve_elasticsearch_docs_for_case(
            eval_case=eval_case,
            retriever=retriever,
        )
        retrieved_docs_by_case_id[eval_case.id] = docs

    return evaluate_retrieval_dataset(
        cases=dataset.cases,
        retrieved_docs_by_case_id=retrieved_docs_by_case_id,
    )

