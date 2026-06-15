from typing import Protocol

from fast_app.domain.rag_models import RetrievedDoc, ScoreBreakdown
from fast_app.evaluation.cases.models import RagEvalDataset, RagEvalCase
from fast_app.evaluation.generation.metrics import evaluate_generation_dataset
from fast_app.evaluation.pipeline.models import (
    OfflineRagEvalCaseOutput,
    OfflineRagEvalReport,
)
from fast_app.evaluation.retrieval.metrics import evaluate_retrieval_dataset
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse, RagSource


class RagPipelineLike(Protocol):
    """离线评测需要的最小 pipeline 协议。

    Classic RagPipeline 和 LangGraphRagPipeline 当前都有 run(req) 方法。
    因此这里不用强制它们继承同一个基类，只要求它们满足这个协议。
    """

    async def run(self, req: RagChatRequest) -> RagChatResponse:
        ...


def build_rag_request_from_eval_case(eval_case: RagEvalCase) -> RagChatRequest:
    """把评测样例转换成真实 RAG 请求模型。"""

    return RagChatRequest(
        query=eval_case.question,
        mode=eval_case.mode,
        top_k=eval_case.top_k,
        min_score=eval_case.min_score,
        candidate_k=eval_case.candidate_k,
        filters=eval_case.filters,
    )


def rag_source_to_retrieved_doc(source: RagSource) -> RetrievedDoc:
    """把 API response 里的 RagSource 还原成检索评测可用的 RetrievedDoc。

    注意：RagSource 只有 content_preview，不是完整 chunk content。
    所以这里还原出的 RetrievedDoc 主要用于离线 response 层面的轻量检索评测。
    """

    return RetrievedDoc(
        id=source.id,
        content=source.content_preview,
        score=source.score,
        source=source.source,
        title=source.title,
        metadata={
            **source.metadata,
            "section_path": source.section_path,
        },
        retrieval_sources=source.retrieval_sources,
        scores=ScoreBreakdown(
            vector_score=source.scores.vector_score,
            keyword_score=source.scores.keyword_score,
            rrf_score=source.scores.rrf_score,
            rerank_score=source.scores.rerank_score,
        ),
    )


async def run_pipeline_for_dataset(
    dataset: RagEvalDataset,
    pipeline: RagPipelineLike,
) -> dict[str, RagChatResponse]:
    """批量请求 pipeline，返回 case_id 到 response 的映射。

    这个函数只负责执行请求，不负责计算指标。
    """

    responses_by_case_id: dict[str, RagChatResponse] = {}

    for eval_case in dataset.cases:
        request = build_rag_request_from_eval_case(eval_case)
        response = await pipeline.run(request)
        responses_by_case_id[eval_case.id] = response

    return responses_by_case_id


def build_retrieved_docs_from_responses(
    responses_by_case_id: dict[str, RagChatResponse],
) -> dict[str, list[RetrievedDoc]]:
    """从 pipeline responses 中构造检索评测输入。"""

    return {
        case_id: [
            rag_source_to_retrieved_doc(source)
            for source in response.sources
        ]
        for case_id, response in responses_by_case_id.items()
    }


async def run_offline_rag_eval(
    dataset: RagEvalDataset,
    pipeline: RagPipelineLike,
) -> OfflineRagEvalReport:
    """运行一次完整离线 RAG 评测。

    执行顺序：
    1. 批量请求 pipeline.run。
    2. 从 response.sources 构造检索评测输入。
    3. 评测 sources 是否命中 expected_sources。
    4. 评测 answer 是否满足生成侧规则。
    5. 返回一个总报告对象。
    """

    responses_by_case_id = await run_pipeline_for_dataset(
        dataset=dataset,
        pipeline=pipeline,
    )
    retrieved_docs_by_case_id = build_retrieved_docs_from_responses(
        responses_by_case_id=responses_by_case_id,
    )

    retrieval_report = evaluate_retrieval_dataset(
        cases=dataset.cases,
        retrieved_docs_by_case_id=retrieved_docs_by_case_id,
    )
    generation_report = evaluate_generation_dataset(
        cases=dataset.cases,
        responses_by_case_id=responses_by_case_id,
    )

    return OfflineRagEvalReport(
        dataset_name=dataset.name,
        case_count=len(dataset.cases),
        response_count=len(responses_by_case_id),
        retrieval_report=retrieval_report,
        generation_report=generation_report,
        outputs=[
            OfflineRagEvalCaseOutput(
                case_id=case_id,
                response=response,
            )
            for case_id, response in responses_by_case_id.items()
        ],
    )

