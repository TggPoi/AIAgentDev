from contextlib import nullcontext

import fast_app.core.langsmith as langsmith_module
from fast_app.core.config import Settings
from fast_app.core.langsmith import (
    build_langsmith_metadata,
    build_rag_langsmith_inputs,
    langsmith_trace,
    rag_langsmith_pipeline_trace,
    rag_langsmith_state_step_trace,
    sanitize_langsmith_payload,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagRetrievalFilters


def build_settings(*, include_sensitive_data: bool = False) -> Settings:
    return Settings(
        LANGSMITH_TRACING=True,
        LANGSMITH_API_KEY="test-key",
        LANGSMITH_TAGS="team:rag",
        LANGSMITH_INCLUDE_SENSITIVE_DATA=include_sensitive_data,
    )


def run_checks() -> None:
    req = RagChatRequest(
        query="内部问题",
        mode="hybrid",
        top_k=3,
        filters=RagRetrievalFilters(source_path="private.md"),
    )

    safe_settings = build_settings()
    safe_inputs = build_rag_langsmith_inputs(safe_settings, req)
    assert safe_inputs["query"] == "[REDACTED]"
    assert safe_inputs["filters"] == {}
    assert safe_inputs["query_length"] == len(req.query)

    sensitive_settings = build_settings(include_sensitive_data=True)
    sensitive_inputs = build_rag_langsmith_inputs(sensitive_settings, req)
    assert sensitive_inputs["query"] == req.query
    assert sensitive_inputs["filters"]["source_path"] == "private.md"
    assert build_langsmith_metadata(
        safe_settings,
        sensitive_metadata={"user_id": "user-1"},
    ).get("user_id") is None
    assert build_langsmith_metadata(
        sensitive_settings,
        sensitive_metadata={"user_id": "user-1"},
    )["user_id"] == "user-1"
    assert sanitize_langsmith_payload(
        safe_settings,
        {"nested": {"effective_query": req.query}},
    )["nested"]["effective_query"] == "[REDACTED]"

    captured: dict[str, object] = {}
    original_trace = langsmith_module.trace

    def capture_trace(**kwargs: object):
        captured.clear()
        captured.update(kwargs)
        return nullcontext()

    langsmith_module.trace = capture_trace
    try:
        rag_langsmith_pipeline_trace(safe_settings, req, "classic", "stream_events")
        assert captured["name"] == "classic_rag_pipeline.stream_events"
        assert captured["inputs"] == safe_inputs
        assert "operation:stream_events" in captured["tags"]
        assert "team:rag" in captured["tags"]

        rag_langsmith_state_step_trace(
            safe_settings,
            {"mode": "hybrid", "top_k": 3},
            "rag_agent",
            "run",
            "retrieve",
            2,
            "retriever",
            {"query": req.query, "query_length": len(req.query)},
        )
        assert captured["name"] == "rag_agent_pipeline.run.retrieve"
        assert captured["inputs"]["query"] == "[REDACTED]"
        assert captured["metadata"]["step_index"] == 2
        assert "step:retrieve" in captured["tags"]
    finally:
        langsmith_module.trace = original_trace

    disabled_settings = Settings(
        LANGSMITH_TRACING=False,
        LANGSMITH_API_KEY="",
    )
    with langsmith_trace(
        disabled_settings,
        "disabled",
        "chain",
        {},
        {},
        [],
    ) as trace_run:
        assert trace_run is None


if __name__ == "__main__":
    run_checks()
    print("LangSmith tracing checks passed.")
