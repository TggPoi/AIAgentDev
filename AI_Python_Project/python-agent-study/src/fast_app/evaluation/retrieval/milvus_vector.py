from fast_app.components.retrievers.milvus_vector_retriever import MilvusVectorRetriever
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.evaluation.cases.models import RagEvalCase, RagEvalDataset
from fast_app.evaluation.retrieval.models import (
    RetrievalCaseResult,
    RetrievalDatasetReport,
)
from fast_app.evaluation.retrieval.metrics import (
    evaluate_retrieval_case,
    evaluate_retrieval_dataset,
)


def build_retrieval_options_from_eval_case(
    eval_case: RagEvalCase,
) -> RetrievalOptions:
    """把评测样例转换成 retriever 能理解的 RetrievalOptions。

    RagEvalCase 是“评测数据模型”，RetrievalOptions 是“检索组件入参模型”。
    单独做一层转换，可以避免 Milvus 评测代码直接依赖 API request。
    """

    candidate_k = max(eval_case.candidate_k or eval_case.top_k, eval_case.top_k)

    return RetrievalOptions(
        top_k=eval_case.top_k,
        candidate_k=candidate_k,
        filters=RetrievalFilters(
            source_path=eval_case.filters.source_path,
            section_path=eval_case.filters.section_path,
        ),
    )


async def retrieve_milvus_docs_for_case(
    eval_case: RagEvalCase,
    retriever: MilvusVectorRetriever,
) -> list[RetrievedDoc]:
    """为单条评测样例执行 Milvus 向量召回。

    MilvusVectorRetriever 内部会按 candidate_k 查询 Milvus。
    这里再截取 top_k，是为了让 Recall@K / MRR 中的 K 和 eval_case.top_k 一致。
    """

    options = build_retrieval_options_from_eval_case(eval_case)
    docs = await retriever.retrieve(eval_case.question, options)

    return docs[: eval_case.top_k]


async def evaluate_milvus_vector_case(
    eval_case: RagEvalCase,
    retriever: MilvusVectorRetriever,
) -> RetrievalCaseResult:
    """评测单条 case 的 Milvus 向量召回质量。

    这个函数只负责把 Milvus 召回结果接到通用指标函数上。
    指标计算仍然由 evaluate_retrieval_case 负责。
    """

    docs = await retrieve_milvus_docs_for_case(
        eval_case=eval_case,
        retriever=retriever,
    )

    return evaluate_retrieval_case(
        eval_case=eval_case,
        docs=docs,
    )


async def evaluate_milvus_vector_dataset(
    dataset: RagEvalDataset,
    retriever: MilvusVectorRetriever,
) -> RetrievalDatasetReport:
    """评测整个数据集的 Milvus 单路向量召回质量。

    no_answer 样例当前主要服务于后续生成评测，所以这里不请求 Milvus。
    只把 answerable 样例的 RetrievedDoc 列表交给 evaluate_retrieval_dataset。
    """

    retrieved_docs_by_case_id: dict[str, list[RetrievedDoc]] = {}

    for eval_case in dataset.cases:
        if eval_case.case_type != "answerable":
            continue

        docs = await retrieve_milvus_docs_for_case(
            eval_case=eval_case,
            retriever=retriever,
        )
        retrieved_docs_by_case_id[eval_case.id] = docs

    return evaluate_retrieval_dataset(
        cases=dataset.cases,
        retrieved_docs_by_case_id=retrieved_docs_by_case_id,
    )

