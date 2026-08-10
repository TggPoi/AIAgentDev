"""验证 EvaluationSnapshot 安全模式、完整性和三条 RAG 采集 seam。"""

import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import os
from tempfile import TemporaryDirectory


os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from fast_app.agents.tools.rag_agent_tools import retrieve_knowledge_docs
from fast_app.core.config import Settings
from fast_app.domain.knowledge_permissions import RetrievalPermissionScope
from fast_app.domain.rag_models import (
    RagContext,
    RetrievalFilters,
    RetrievedDoc,
    ScoreBreakdown,
)
from fast_app.evaluation.cases.models import (
    ExpectedSource,
    RagEvalCase,
    RagEvalDataset,
    RequiredKeyFact,
)
from fast_app.evaluation.pipeline.runner import run_offline_rag_eval
from fast_app.evaluation.pipeline.models import EvaluationError
from fast_app.evaluation.reports.writer import write_offline_eval_report
from fast_app.evaluation.reports.serialization import to_jsonable
from fast_app.evaluation.pipeline.snapshot_capture import (
    SnapshotContentUnavailableError,
    SnapshotIntegrityError,
    build_retrieved_docs_from_snapshot,
    capture_evaluation_snapshot,
    read_snapshot_mapping,
    read_snapshot_value,
    record_snapshot_final_context,
    record_snapshot_retrieval_stage,
    verify_snapshot_integrity,
)
from fast_app.graph.rag.rag_graph_nodes import create_rerank_node
from fast_app.graph.rag.rag_graph_state import build_graph_initial_state
from fast_app.graph.rag_agent.rag_agent_nodes import (
    create_agent_build_context_node,
    create_agent_rerank_node,
    create_call_knowledge_retrieval_node,
)
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.rag.langgraph_rag_pipeline_service import (
    LangGraphRagPipeline,
)
from fast_app.services.rag.rag_pipeline_service import RagPipeline


def assert_raises(error_type: type[Exception], action) -> None:
    try:
        action()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def encoded_key(fill: int) -> str:
    return base64.urlsafe_b64encode(bytes([fill]) * 32).decode("ascii")


def build_settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="dev",
        LANGSMITH_TRACING=False,
        RAG_PARENT_EXPANSION_ENABLED=False,
        RAG_PARENT_CONTEXT_MAX_TOKENS=3000,
        MARKDOWN_PARENT_MAX_TOKENS=1200,
        **values,
    )


def build_doc(doc_id: str, content: str, source: str) -> RetrievedDoc:
    return RetrievedDoc(
        id=doc_id,
        content=content,
        score=0.9,
        source=source,
        title=f"title-{doc_id}",
        metadata={
            "doc_id": f"logical-doc-{doc_id}",
            "logical_chunk_id": f"logical-{doc_id}",
            "source_revision": "commit-123",
            "source_path": f"private/{doc_id}.md",
            "section_path": ["评测", doc_id],
        },
        retrieval_sources=[source],
        scores=ScoreBreakdown(
            vector_score=0.9 if source == "milvus" else None,
            keyword_score=0.9 if source == "elasticsearch" else None,
        ),
    )


def build_request() -> RagChatRequest:
    req = RagChatRequest(
        query="原始问题",
        mode="hybrid",
        top_k=2,
        candidate_k=4,
        filters={"source_path": "private"},
    )
    req._current_user_id = "eval-user"
    req._knowledge_version = 7
    req._retrieval_permission_scope = RetrievalPermissionScope(
        user_id="eval-user",
        department_codes=["development"],
        allow_public=False,
    )
    return req


def capture_complete_snapshot(settings: Settings):
    req = build_request()
    vector_docs = [build_doc("vector-1", "vector full content", "milvus")]
    keyword_docs = [
        build_doc("keyword-1", "keyword full content", "elasticsearch")
    ]
    rrf_docs = [*vector_docs, *keyword_docs]
    context = RagContext(
        query="改写后的问题",
        docs=rrf_docs,
        context_text="vector full content\n\nkeyword full content",
    )
    with capture_evaluation_snapshot(
        req=req,
        settings=settings,
        pipeline_provider="contract-test",
    ) as collector:
        record_snapshot_retrieval_stage("vector", vector_docs, query=context.query)
        record_snapshot_retrieval_stage("keyword", keyword_docs, query=context.query)
        record_snapshot_retrieval_stage("rrf", rrf_docs, query=context.query)
        record_snapshot_retrieval_stage("rerank", rrf_docs, query=context.query)
        record_snapshot_final_context(context)
        snapshot = collector.finalize(
            response=RagChatResponse(
                query=context.query,
                answer="最终答案",
                sources=[],
                knowledge_version=7,
            ),
            latency_ms=12.5,
        )
    return snapshot


class FakeRetriever:
    def __init__(self, docs: list[RetrievedDoc]):
        self.docs = docs

    async def retrieve(self, query: str, options: object) -> list[RetrievedDoc]:
        return deepcopy(self.docs)


class FakeReranker:
    async def rerank(
        self,
        query: str,
        docs: list[RetrievedDoc],
        top_k: int,
    ) -> list[RetrievedDoc]:
        return list(reversed(docs))[:top_k]


class FakeLLM:
    async def generate(
        self,
        query: str,
        context: RagContext,
        langchain_config: object | None = None,
    ) -> str:
        return f"answer:{query}:{context.context_text}"


def run_settings_and_security_checks() -> None:
    assert all("snapshot" not in name for name in RagChatRequest.model_fields)
    assert all("snapshot" not in name for name in RagChatResponse.model_fields)

    assert_raises(
        ValueError,
        lambda: Settings(
            _env_file=None,
            APP_ENV="prod",
            EVAL_SNAPSHOT_SECURITY_MODE="plain",
        ),
    )
    redacted_shared = Settings(
        _env_file=None,
        APP_ENV="prod",
        EVAL_SNAPSHOT_SECURITY_MODE="redacted",
    )
    assert redacted_shared.eval_snapshot_security_mode == "redacted"
    assert_raises(
        ValueError,
        lambda: build_settings(EVAL_SNAPSHOT_SECURITY_MODE="encrypted"),
    )

    plain_snapshot = capture_complete_snapshot(build_settings())
    verify_snapshot_integrity(plain_snapshot)
    assert plain_snapshot.security_mode == "plain"
    assert plain_snapshot.content_replayable is True
    assert read_snapshot_value(plain_snapshot.payload.answer) == "最终答案"
    assert plain_snapshot.payload.knowledge_version == 7
    assert plain_snapshot.payload.source_revisions == ["commit-123"]
    assert (
        read_snapshot_value(
            plain_snapshot.payload.principal.eval_principal_id
        )
        == "eval-user"
    )
    assert read_snapshot_mapping(
        plain_snapshot.payload.principal.permission_scope
    )["department_codes"] == ["development"]
    assert (
        read_snapshot_value(plain_snapshot.payload.final_context.context_text)
        == "vector full content\n\nkeyword full content"
    )
    rebuilt = build_retrieved_docs_from_snapshot(plain_snapshot)
    assert [doc.id for doc in rebuilt] == ["vector-1", "keyword-1"]
    assert rebuilt[0].content == "vector full content"

    tampered_answer = replace(
        plain_snapshot.payload.answer,
        plaintext="被篡改的答案",
    )
    tampered_payload = replace(plain_snapshot.payload, answer=tampered_answer)
    tampered_snapshot = replace(plain_snapshot, payload=tampered_payload)
    assert_raises(
        SnapshotIntegrityError,
        lambda: verify_snapshot_integrity(tampered_snapshot),
    )

    redacted_snapshot = capture_complete_snapshot(
        build_settings(EVAL_SNAPSHOT_SECURITY_MODE="redacted")
    )
    assert redacted_snapshot.payload.answer.plaintext is None
    assert redacted_snapshot.content_replayable is False
    assert redacted_snapshot.payload.answer.ciphertext is None
    assert_raises(
        SnapshotContentUnavailableError,
        lambda: read_snapshot_value(redacted_snapshot.payload.answer),
    )
    verify_snapshot_integrity(redacted_snapshot)
    redacted_docs = build_retrieved_docs_from_snapshot(redacted_snapshot)
    assert [doc.id for doc in redacted_docs] == ["vector-1", "keyword-1"]
    assert redacted_docs[0].content == ""
    redacted_json = json.dumps(
        to_jsonable(redacted_snapshot),
        ensure_ascii=False,
    )
    assert "原始问题" not in redacted_json
    assert "vector full content" not in redacted_json
    assert "最终答案" not in redacted_json

    old_key_settings = build_settings(
        EVAL_SNAPSHOT_SECURITY_MODE="encrypted",
        EVAL_SNAPSHOT_ENCRYPTION_ACTIVE_KEY_ID="key-old",
        EVAL_SNAPSHOT_ENCRYPTION_KEYS_JSON=(
            '{"key-old":"' + encoded_key(1) + '"}'
        ),
    )

    failed_req = build_request()
    with capture_evaluation_snapshot(
        req=failed_req,
        settings=build_settings(),
        pipeline_provider="failure-test",
    ) as collector:
        failed_snapshot = collector.finalize(
            response=None,
            latency_ms=8.0,
            error=EvaluationError(
                code="EVAL_TARGET_TIMEOUT",
                message="被测目标调用超时。",
                retryable=True,
            ),
        )
    assert failed_snapshot.payload.error is not None
    assert failed_snapshot.payload.error.code == "EVAL_TARGET_TIMEOUT"
    encrypted_snapshot = capture_complete_snapshot(old_key_settings)
    assert encrypted_snapshot.payload.answer.plaintext is None
    assert encrypted_snapshot.payload.answer.key_id == "key-old"
    verify_snapshot_integrity(encrypted_snapshot, old_key_settings)
    assert (
        read_snapshot_value(encrypted_snapshot.payload.answer, old_key_settings)
        == "最终答案"
    )
    encrypted_json = json.dumps(
        to_jsonable(encrypted_snapshot),
        ensure_ascii=False,
    )
    assert "原始问题" not in encrypted_json
    assert "vector full content" not in encrypted_json
    assert "最终答案" not in encrypted_json

    rotated_settings = build_settings(
        EVAL_SNAPSHOT_SECURITY_MODE="encrypted",
        EVAL_SNAPSHOT_ENCRYPTION_ACTIVE_KEY_ID="key-new",
        EVAL_SNAPSHOT_ENCRYPTION_KEYS_JSON=(
            '{"key-old":"'
            + encoded_key(1)
            + '","key-new":"'
            + encoded_key(2)
            + '"}'
        ),
    )
    assert (
        read_snapshot_value(encrypted_snapshot.payload.answer, rotated_settings)
        == "最终答案"
    )
    new_snapshot = capture_complete_snapshot(rotated_settings)
    assert new_snapshot.payload.answer.key_id == "key-new"

    missing_old_key_settings = build_settings(
        EVAL_SNAPSHOT_SECURITY_MODE="encrypted",
        EVAL_SNAPSHOT_ENCRYPTION_ACTIVE_KEY_ID="key-new",
        EVAL_SNAPSHOT_ENCRYPTION_KEYS_JSON=(
            '{"key-new":"' + encoded_key(2) + '"}'
        ),
    )
    assert_raises(
        SnapshotContentUnavailableError,
        lambda: read_snapshot_value(
            encrypted_snapshot.payload.answer,
            missing_old_key_settings,
        ),
    )


async def run_classic_capture_check() -> None:
    settings = build_settings(RERANK_TOP_K=2)
    vector_doc = build_doc("vector-1", "vector full content", "milvus")
    keyword_doc = build_doc("keyword-1", "keyword full content", "elasticsearch")
    pipeline = RagPipeline(
        settings=settings,
        vector_retriever=FakeRetriever([vector_doc]),
        keyword_retriever=FakeRetriever([keyword_doc]),
        llm_client=FakeLLM(),
        reranker=FakeReranker(),
    )
    req = build_request()
    with capture_evaluation_snapshot(
        req=req,
        settings=settings,
        pipeline_provider=pipeline.pipeline_provider,
    ) as collector:
        response = await pipeline.run(req)
        snapshot = collector.finalize(response=response, latency_ms=1.0)

    assert snapshot.payload.target.pipeline_provider == "classic"
    assert all(
        snapshot.payload.retrieval_stages[name].status == "captured"
        for name in ("vector", "keyword", "rrf", "rerank")
    )
    assert snapshot.payload.final_context is not None
    assert read_snapshot_value(snapshot.payload.final_context.context_text)

    report = await run_offline_rag_eval(
        dataset=RagEvalDataset(
            schema_version="2.0",
            dataset_id="snapshot-runner",
            dataset_version="2.0.0-test",
            lifecycle="candidate",
            content_sha256="0" * 64,
            name="snapshot-runner",
            description="验证 runner 使用完整快照而不是 content_preview。",
            knowledge_base_dir="unused",
            source_revision="test:snapshot-runner",
            created_at=datetime(2026, 8, 10, 0, 0, 0).astimezone(),
            cases=[
                RagEvalCase(
                    case_id="runner-case",
                    dataset_version="2.0.0-test",
                    metric_profile="rag",
                    question=req.query,
                    answerable=True,
                    expected_route="rag_answer",
                    eval_principal_id="eval:test-runner",
                    knowledge_version=1,
                    source_revision="test:snapshot-runner",
                    mode="hybrid",
                    top_k=2,
                    candidate_k=4,
                    relevant_logical_chunk_ids=["keyword-1"],
                    relevant_doc_ids=["doc-keyword-1"],
                    expected_sources=[
                        ExpectedSource(
                            logical_doc_id="doc-keyword-1",
                            source_revision="test:snapshot-runner",
                            logical_chunk_ids=["keyword-1"],
                            source_path="test/keyword.md",
                        ),
                    ],
                    required_key_facts=[
                        RequiredKeyFact(
                            fact_id="answer",
                            text="回答包含 answer。",
                            weight=1.0,
                        ),
                    ],
                    question_intent="验证离线 runner 使用完整上下文。",
                    scenario_tags=["answerable"],
                    expected_answer_keywords=["answer"],
                    annotation_method="human",
                    annotated_by="test-fixture",
                    review_status="pending_review",
                )
            ],
        ),
        pipeline=pipeline,
    )
    assert report.outputs[0].snapshot is not None
    assert report.retrieval_report.results[0].passed is True
    runner_docs = build_retrieved_docs_from_snapshot(report.outputs[0].snapshot)
    assert runner_docs[0].content == "keyword full content"
    with TemporaryDirectory() as temp_dir:
        paths = write_offline_eval_report(
            report,
            output_dir=temp_dir,
            timestamp=datetime(2026, 8, 10, 0, 0, 0),
        )
        json_report = paths.json_path.read_text(encoding="utf-8")
        assert paths.markdown_path.exists()
        assert '"retrieval_stages"' in json_report
        assert "keyword full content" in json_report


async def run_shared_and_graph_capture_checks() -> None:
    settings = build_settings(RERANK_TOP_K=2)
    vector_doc = build_doc("vector-1", "vector full content", "milvus")
    keyword_doc = build_doc("keyword-1", "keyword full content", "elasticsearch")
    req = build_request()

    with capture_evaluation_snapshot(
        req=req,
        settings=settings,
        pipeline_provider="langgraph",
    ) as collector:
        docs = await retrieve_knowledge_docs(
            settings=settings,
            vector_retriever=FakeRetriever([vector_doc]),
            keyword_retriever=FakeRetriever([keyword_doc]),
            query=req.query,
            mode="hybrid",
            top_k=2,
            candidate_k=4,
            min_score=0.0,
            filters=RetrievalFilters(),
            pipeline_provider="langgraph",
        )
        graph_state = build_graph_initial_state(req, "run")
        graph_state["docs"] = docs
        rerank_result = await create_rerank_node(
            settings=settings,
            reranker=FakeReranker(),
            rerank_top_k=2,
        )(graph_state)
        graph_state.update(rerank_result)
        context = await assemble_rag_context(
            settings=settings,
            query=req.query,
            docs=graph_state["docs"],
            filters=graph_state["filters"],
            source="snapshot-test.langgraph",
        )
        snapshot = collector.finalize(
            response=RagChatResponse(
                query=req.query,
                answer="langgraph answer",
                sources=[],
            ),
            latency_ms=2.0,
        )

    assert snapshot.payload.retrieval_stages["rerank"].status == "captured"
    assert snapshot.payload.final_context is not None
    assert [doc.id for doc in context.docs] == ["keyword-1", "vector-1"]

    agent_req = build_request()
    agent_state = build_rag_agent_initial_state(agent_req, "run")
    with capture_evaluation_snapshot(
        req=agent_req,
        settings=settings,
        pipeline_provider="rag_agent",
    ) as collector:
        retrieval_result = await create_call_knowledge_retrieval_node(
            settings=settings,
            vector_retriever=FakeRetriever([vector_doc]),
            keyword_retriever=FakeRetriever([keyword_doc]),
        )(agent_state)
        agent_state.update(retrieval_result)
        rerank_result = await create_agent_rerank_node(
            settings=settings,
            reranker=FakeReranker(),
            rerank_top_k=2,
        )(agent_state)
        agent_state.update(rerank_result)
        context_result = await create_agent_build_context_node(
            settings=settings,
        )(agent_state)
        agent_state.update(context_result)
        agent_snapshot = collector.finalize(
            response=RagChatResponse(
                query=agent_state["query"],
                answer="agent answer",
                sources=[],
            ),
            latency_ms=3.0,
        )

    assert agent_snapshot.payload.target.pipeline_provider == "rag_agent"
    assert agent_snapshot.payload.retrieval_stages["rrf"].status == "captured"
    assert agent_snapshot.payload.retrieval_stages["rerank"].status == "captured"
    assert agent_snapshot.payload.final_context is not None


async def run_langgraph_pipeline_capture_check() -> None:
    settings = build_settings(RERANK_TOP_K=2)
    pipeline = LangGraphRagPipeline(
        settings=settings,
        vector_retriever=FakeRetriever(
            [build_doc("vector-1", "vector full content", "milvus")]
        ),
        keyword_retriever=FakeRetriever(
            [
                build_doc(
                    "keyword-1",
                    "keyword full content",
                    "elasticsearch",
                )
            ]
        ),
        llm_client=FakeLLM(),
        reranker=FakeReranker(),
    )
    req = build_request()
    with capture_evaluation_snapshot(
        req=req,
        settings=settings,
        pipeline_provider=pipeline.pipeline_provider,
    ) as collector:
        response = await pipeline.run(req)
        snapshot = collector.finalize(response=response, latency_ms=4.0)

    assert snapshot.payload.target.pipeline_provider == "langgraph"
    assert all(
        snapshot.payload.retrieval_stages[name].status == "captured"
        for name in ("vector", "keyword", "rrf", "rerank")
    )
    assert snapshot.payload.final_context is not None


async def run_context_isolation_check() -> None:
    settings = build_settings()

    async def capture_one(name: str):
        req = RagChatRequest(query=f"query-{name}", mode="vector", top_k=1)
        doc = build_doc(name, f"content-{name}", "milvus")
        with capture_evaluation_snapshot(
            req=req,
            settings=settings,
            pipeline_provider="isolation-test",
        ) as collector:
            await asyncio.sleep(0)
            record_snapshot_retrieval_stage("vector", [doc], query=req.query)
            record_snapshot_final_context(
                RagContext(
                    query=req.query,
                    docs=[doc],
                    context_text=doc.content,
                )
            )
            return collector.finalize(
                response=RagChatResponse(
                    query=req.query,
                    answer=f"answer-{name}",
                    sources=[],
                ),
                latency_ms=1.0,
            )

    first, second = await asyncio.gather(
        capture_one("first"),
        capture_one("second"),
    )
    assert first.payload.retrieval_stages["vector"].documents[0].id == "first"
    assert second.payload.retrieval_stages["vector"].documents[0].id == "second"
    assert read_snapshot_value(first.payload.answer) == "answer-first"
    assert read_snapshot_value(second.payload.answer) == "answer-second"


async def run_checks() -> None:
    run_settings_and_security_checks()

    # Eval capture 未开启时是无状态 no-op，普通主链不需要了解 Snapshot 类型。
    record_snapshot_retrieval_stage(
        "vector",
        [build_doc("no-op", "not captured", "milvus")],
    )
    record_snapshot_final_context(
        RagContext(query="no-op", docs=[], context_text="")
    )

    await run_classic_capture_check()
    await run_shared_and_graph_capture_checks()
    await run_langgraph_pipeline_capture_check()
    await run_context_isolation_check()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("Evaluation snapshot checks passed.")
