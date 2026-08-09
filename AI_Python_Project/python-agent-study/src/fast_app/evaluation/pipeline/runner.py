from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievedDoc, ScoreBreakdown
from fast_app.evaluation.cases.models import RagEvalCase, RagEvalDataset
from fast_app.evaluation.generation.metrics import evaluate_generation_dataset
from fast_app.evaluation.pipeline.models import (
    EvaluationSnapshot,
    OfflineRagEvalCaseOutput,
    OfflineRagEvalReport,
)
from fast_app.evaluation.pipeline.snapshot_capture import (
    build_retrieved_docs_from_snapshot,
    capture_evaluation_snapshot,
)
from fast_app.evaluation.retrieval.metrics import evaluate_retrieval_dataset
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse, RagSource


class RagPipelineLike(Protocol):
    """离线评测使用的最小被测 Pipeline 接口。"""

    settings: Settings
    pipeline_provider: str

    async def run(self, req: RagChatRequest) -> RagChatResponse:
        ...


@dataclass(frozen=True)
class PipelineDatasetExecution:
    """同一次被测执行产生的响应与不可变快照。"""

    responses_by_case_id: dict[str, RagChatResponse]
    snapshots_by_case_id: dict[str, EvaluationSnapshot]


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
    """兼容旧调用：从 response source 构造轻量 RetrievedDoc。

    新离线主线已经改用 EvaluationSnapshot.final_context；此 helper 仅保留给旧调用方，
    不能用于忠实度或需要完整正文的评测。
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


async def run_pipeline_with_snapshots_for_dataset(
    dataset: RagEvalDataset,
    pipeline: RagPipelineLike,
) -> PipelineDatasetExecution:
    """每条 case 只调用一次 Pipeline，并在同一调用中冻结完整快照。"""

    responses_by_case_id: dict[str, RagChatResponse] = {}
    snapshots_by_case_id: dict[str, EvaluationSnapshot] = {}

    for eval_case in dataset.cases:
        request = build_rag_request_from_eval_case(eval_case)
        start_time = perf_counter()
        with capture_evaluation_snapshot(
            req=request,
            settings=pipeline.settings,
            pipeline_provider=pipeline.pipeline_provider,
        ) as collector:
            response = await pipeline.run(request)
            snapshot = collector.finalize(
                response=response,
                latency_ms=(perf_counter() - start_time) * 1000,
            )
        responses_by_case_id[eval_case.id] = response
        snapshots_by_case_id[eval_case.id] = snapshot

    return PipelineDatasetExecution(
        responses_by_case_id=responses_by_case_id,
        snapshots_by_case_id=snapshots_by_case_id,
    )


async def run_pipeline_for_dataset(
    dataset: RagEvalDataset,
    pipeline: RagPipelineLike,
) -> dict[str, RagChatResponse]:
    """兼容旧调用：执行时仍采集快照，但只返回 response 映射。"""

    execution = await run_pipeline_with_snapshots_for_dataset(
        dataset=dataset,
        pipeline=pipeline,
    )
    return execution.responses_by_case_id


def build_retrieved_docs_from_responses(
    responses_by_case_id: dict[str, RagChatResponse],
) -> dict[str, list[RetrievedDoc]]:
    """兼容旧调用：从 content_preview 构造轻量检索输入。"""

    return {
        case_id: [
            rag_source_to_retrieved_doc(source)
            for source in response.sources
        ]
        for case_id, response in responses_by_case_id.items()
    }


def build_retrieved_docs_from_snapshots(
    snapshots_by_case_id: dict[str, EvaluationSnapshot],
    settings: Settings,
) -> dict[str, list[RetrievedDoc]]:
    """从冻结最终上下文构造输入，不依赖 RagSource.content_preview。"""

    return {
        case_id: build_retrieved_docs_from_snapshot(snapshot, settings)
        for case_id, snapshot in snapshots_by_case_id.items()
    }


async def run_offline_rag_eval(
    dataset: RagEvalDataset,
    pipeline: RagPipelineLike,
) -> OfflineRagEvalReport:
    """执行一次完整离线 RAG 评测，并把同次调用的快照写入报告。"""

    execution = await run_pipeline_with_snapshots_for_dataset(
        dataset=dataset,
        pipeline=pipeline,
    )
    responses_by_case_id = execution.responses_by_case_id
    retrieved_docs_by_case_id = build_retrieved_docs_from_snapshots(
        snapshots_by_case_id=execution.snapshots_by_case_id,
        settings=pipeline.settings,
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
                snapshot=execution.snapshots_by_case_id[case_id],
            )
            for case_id, response in responses_by_case_id.items()
        ],
    )
