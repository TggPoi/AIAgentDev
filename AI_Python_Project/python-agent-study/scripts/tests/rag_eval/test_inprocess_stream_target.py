"""进程内真实 ASGI 流式 EvalTarget 的集成契约测试。"""

import asyncio
import json
from tempfile import TemporaryDirectory

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse

from fast_app.core.config import Settings
from fast_app.domain.rag_models import RagContext, RetrievedDoc, ScoreBreakdown
from fast_app.evaluation.cases.loader import load_eval_dataset
from fast_app.evaluation.pipeline.snapshot_capture import (
    read_snapshot_value,
    record_snapshot_final_context,
    record_snapshot_retrieval_stage,
)
from fast_app.rag_eval.target import InProcessStructuredStreamTarget, RagEvalAuth
from fast_app.rag_eval.models import (
    GenerationEvaluationResponse,
    RagEvalMetricResult,
)
from fast_app.rag_eval.runner import ALL_METRIC_NAMES, LightweightRagEvalRunner
from fast_app.rag_eval.reporting import (
    apply_baseline,
    load_report,
    render_markdown,
    write_reports,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_test_app(logical_chunk_id: str, *, route_intent: str | None = None) -> FastAPI:
    app = FastAPI()

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(
        req: RagChatRequest,
        x_demo_user_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        assert x_demo_user_id == "eval-user:rbac_reader"
        doc = RetrievedDoc(
            id="physical-1",
            content="这是模型真正收到的完整上下文。",
            score=0.9,
            source="milvus",
            metadata={"logical_chunk_id": logical_chunk_id, "doc_id": "doc-1"},
            retrieval_sources=["vector", "keyword"],
            scores=ScoreBreakdown(rerank_score=0.9),
        )
        record_snapshot_retrieval_stage("rerank", [doc], query=req.query)
        record_snapshot_final_context(
            RagContext(query=req.query, docs=[doc], context_text=doc.content)
        )

        async def events():
            if route_intent:
                yield sse(
                    "agent_route_selected",
                    {"intent": route_intent, "source": "router"},
                )
            yield sse("sources", {"sources": []})
            yield sse("answer_delta", {"text": "最终回答"})
            yield sse(
                "done",
                {"status": "done", "knowledge_version": 6},
            )

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def build_parent_test_app(parent_id: str) -> FastAPI:
    app = FastAPI()

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(req: RagChatRequest) -> StreamingResponse:
        child = RetrievedDoc(
            id="physical-trigger-child",
            content="只有章节标题的触发子块",
            score=0.9,
            source="milvus",
            metadata={
                "logical_chunk_id": "trigger-child",
                "parent_id": parent_id,
                "doc_id": "doc-parent",
            },
            retrieval_sources=["vector"],
            scores=ScoreBreakdown(rerank_score=0.9),
        )
        parent = RetrievedDoc(
            id=parent_id,
            content="模型最终收到的完整父块正文",
            score=0.9,
            source="elasticsearch",
            metadata={
                "logical_parent_id": parent_id,
                "parent_id": parent_id,
                "doc_id": "doc-parent",
            },
            retrieval_sources=["vector", "keyword"],
            scores=ScoreBreakdown(rerank_score=0.9),
        )
        record_snapshot_retrieval_stage("rerank", [child], query=req.query)
        record_snapshot_final_context(
            RagContext(query=req.query, docs=[parent], context_text=parent.content)
        )

        async def events():
            yield sse(
                "agent_route_selected",
                {"intent": "simple_rag", "source": "router"},
            )
            yield sse("sources", {"sources": []})
            yield sse("answer_delta", {"text": "父块回答"})
            yield sse("done", {"status": "done", "knowledge_version": 6})

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def build_no_answer_app() -> FastAPI:
    app = FastAPI()

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(req: RagChatRequest) -> StreamingResponse:
        record_snapshot_retrieval_stage("rerank", [], query=req.query)

        async def events():
            yield sse(
                "error",
                {
                    "code": "NO_SEARCH_RESULT",
                    "message": "没有检索结果",
                    "request_id": "req-no-answer",
                },
            )

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def build_wrong_principal_app() -> FastAPI:
    app = FastAPI()

    @app.get("/auth/me")
    async def auth_me():
        return {"user_id": "different-user"}

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(req: RagChatRequest) -> StreamingResponse:
        del req
        raise AssertionError("身份不一致时不能执行 RAG stream")

    return app


def build_invalid_json_app() -> FastAPI:
    app = FastAPI()

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(req: RagChatRequest) -> StreamingResponse:
        del req

        async def events():
            yield "event: answer_delta\ndata: not-json\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def build_route_only_app(intent: str) -> FastAPI:
    app = FastAPI()

    @app.post("/rag/chat/stream/events")
    async def stream_endpoint(req: RagChatRequest) -> StreamingResponse:
        del req

        async def events():
            yield sse("agent_route_selected", {"intent": intent, "source": "router"})
            yield sse("answer_delta", {"text": "没有经过知识检索的回答"})
            yield sse("done", {"status": "done", "knowledge_version": 6})

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


class FakeGenerationEvaluator:
    async def evaluate(self, request):
        assert request.retrieval_context == ["这是模型真正收到的完整上下文。"]
        return GenerationEvaluationResponse(
            case_id=request.case_id,
            judge_model="fake-qwen",
            metrics={
                name: RagEvalMetricResult(
                    metric_name=name,
                    score=0.75,
                    threshold=0.5,
                    passed=True,
                    status="evaluated",
                    short_reason="fake Judge result",
                )
                for name in request.metrics
            },
        )


async def target_test() -> None:
    dataset = load_eval_dataset(
        "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.0.0.json"
    )
    case = dataset.cases[0]
    settings = Settings(_env_file=None, APP_ENV="test", DEBUG=True)
    secure_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DEBUG=True,
        AUTH_ENABLED=True,
        AUTH_ALLOW_DEMO_USER_HEADER=True,
    )
    try:
        RagEvalAuth.from_environment(secure_settings, {})
    except ValueError as exc:
        assert "必须配置" in str(exc)
    else:
        raise AssertionError("认证开启时不能使用 Demo 头")
    assert RagEvalAuth.from_environment(
        secure_settings,
        {"RAG_EVAL_API_KEY": "eval-key"},
    ).headers_for(case.eval_principal_id) == {"X-API-Key": "eval-key"}
    wrong_principal_target = InProcessStructuredStreamTarget(
        app=build_wrong_principal_app(),
        settings=settings,
        pipeline_provider="classic",
        auth=RagEvalAuth(mode="bearer", credential="test-token"),
    )
    wrong_principal_execution = await wrong_principal_target.execute(case)
    assert wrong_principal_execution.status == "failed"
    assert wrong_principal_execution.error is not None
    assert wrong_principal_execution.error.code == "stream_request_failed"
    invalid_json_target = InProcessStructuredStreamTarget(
        app=build_invalid_json_app(),
        settings=settings,
        pipeline_provider="classic",
        auth=RagEvalAuth(mode="demo"),
    )
    invalid_json_execution = await invalid_json_target.execute(case)
    assert invalid_json_execution.status == "failed"
    assert invalid_json_execution.error is not None
    assert invalid_json_execution.error.code == "sse_protocol_error"
    target = InProcessStructuredStreamTarget(
        app=build_test_app(case.relevant_logical_chunk_ids[0]),
        settings=settings,
        pipeline_provider="classic",
        auth=RagEvalAuth(mode="demo"),
    )

    execution = await target.execute(case)

    assert execution.status == "evaluated"
    assert execution.stream.answer == "最终回答"
    assert execution.knowledge_retrieval_performed is True
    assert execution.snapshot.payload.final_context is not None
    assert "真正收到的完整上下文" not in json.dumps(
        execution.stream.sources, ensure_ascii=False
    )
    assert (
        read_snapshot_value(
            execution.snapshot.payload.final_context.documents[0].content
        )
        == "这是模型真正收到的完整上下文。"
    )

    route_intents = [
        "simple_rag",
        "question_decomposition",
        "web_research",
        "structured_data_query",
        "knowledge_document_management",
        "clarification_required",
    ]
    for intent in route_intents:
        route_target = InProcessStructuredStreamTarget(
            app=build_route_only_app(intent),
            settings=settings,
            pipeline_provider="rag_agent",
            auth=RagEvalAuth(mode="demo"),
        )
        route_execution = await route_target.execute(case)
        assert route_execution.status == "failed", intent
        assert route_execution.error is not None
        assert route_execution.error.code == "route_mismatch", intent
        assert route_execution.knowledge_retrieval_performed is False

    mismatch_runner = LightweightRagEvalRunner(
        target=InProcessStructuredStreamTarget(
            app=build_route_only_app("simple_rag"),
            settings=settings,
            pipeline_provider="rag_agent",
            auth=RagEvalAuth(mode="demo"),
        ),
        settings=settings,
        pipeline_provider="rag_agent",
        mode="retrieval",
        selected_metrics=ALL_METRIC_NAMES[:4],
    )
    mismatch_report = await mismatch_runner.run(
        dataset.model_copy(update={"cases": [case]})
    )
    assert mismatch_report.status == "failed"
    assert mismatch_report.failed_case_count == 1
    assert mismatch_report.metric_summaries[
        "retrieval_recall_at_k"
    ].evaluated_count == 0

    rag_agent_target = InProcessStructuredStreamTarget(
        app=build_test_app(
            case.relevant_logical_chunk_ids[0], route_intent="simple_rag"
        ),
        settings=settings,
        pipeline_provider="rag_agent",
        auth=RagEvalAuth(mode="demo"),
    )
    rag_agent_execution = await rag_agent_target.execute(case)
    assert rag_agent_execution.status == "evaluated"
    assert rag_agent_execution.stream.route_intent == "simple_rag"

    no_answer_case = next(item for item in dataset.cases if not item.answerable)
    no_answer_target = InProcessStructuredStreamTarget(
        app=build_no_answer_app(),
        settings=settings,
        pipeline_provider="classic",
        auth=RagEvalAuth(mode="demo"),
    )
    no_answer_execution = await no_answer_target.execute(no_answer_case)
    assert no_answer_execution.status == "evaluated"
    assert no_answer_execution.stream.error is not None
    assert no_answer_execution.stream.error.code == "NO_SEARCH_RESULT"

    runner = LightweightRagEvalRunner(
        target=target,
        settings=settings,
        pipeline_provider="classic",
        mode="all",
        selected_metrics=ALL_METRIC_NAMES,
        generation_evaluator=FakeGenerationEvaluator(),
    )
    single_case_dataset = dataset.model_copy(update={"cases": [case]})
    report = await runner.run(single_case_dataset)
    assert report.status == "completed"
    assert report.case_count == 1
    assert report.judge_model == "fake-qwen"
    assert report.cases[0].actual_route == "knowledge_retrieval"
    assert len(report.cases[0].metrics) == 8
    assert report.metric_summaries["retrieval_recall_at_k"].mean_score == 1.0
    compared = apply_baseline(report, report, baseline_path="baseline.json")
    assert compared.metric_summaries["retrieval_recall_at_k"].baseline_delta == 0.0
    with TemporaryDirectory() as directory:
        json_path, markdown_path = write_reports(compared, directory)
        assert load_report(json_path).run_id == report.run_id
        assert "轻量流式 RAG Eval 报告" in markdown_path.read_text(encoding="utf-8")

    parent_case = case.model_copy(
        update={
            "case_id": "parent-expansion-contract",
            "retrieval_relevance_unit": "logical_parent",
            "relevant_logical_parent_ids": ["parent-expected"],
            "authoritative_logical_parent_ids": ["parent-expected"],
        }
    )
    parent_runner = LightweightRagEvalRunner(
        target=InProcessStructuredStreamTarget(
            app=build_parent_test_app("parent-expected"),
            settings=settings,
            pipeline_provider="rag_agent",
            auth=RagEvalAuth(mode="demo"),
        ),
        settings=settings,
        pipeline_provider="rag_agent",
        mode="retrieval",
        selected_metrics=ALL_METRIC_NAMES[:4],
    )
    parent_report = await parent_runner.run(
        dataset.model_copy(update={"cases": [parent_case]})
    )
    parent_result = parent_report.cases[0]
    assert parent_result.metrics["retrieval_mrr"].score == 1.0
    assert parent_result.retrieval_source_policy is not None
    assert parent_result.retrieval_source_policy.passed is True
    assert parent_result.retrieval_source_policy.matched_authoritative_logical_ids == [
        "parent-expected"
    ]
    parent_markdown = render_markdown(parent_report)
    assert "检索来源策略" in parent_markdown
    assert "parent-expected" in parent_markdown

    missing_authority_case = parent_case.model_copy(
        update={"authoritative_logical_parent_ids": ["parent-missing"]}
    )
    missing_authority_report = await parent_runner.run(
        dataset.model_copy(update={"cases": [missing_authority_case]})
    )
    assert missing_authority_report.status == "partial"
    assert missing_authority_report.cases[0].status == "evaluated"
    assert missing_authority_report.cases[0].retrieval_source_policy is not None
    assert missing_authority_report.cases[0].retrieval_source_policy.passed is False


if __name__ == "__main__":
    asyncio.run(target_test())
    print("rag_eval in-process stream target tests passed")
