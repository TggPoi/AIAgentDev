from collections.abc import Mapping
from typing import Any

from fast_app.core.config import Settings
from fast_app.domain.rag_models import RagContext, RetrievedDoc
from fast_app.evaluation.pipeline.snapshot_capture import (
    record_snapshot_final_context,
)
from fast_app.services.knowledge.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
)
from fast_app.services.rag.markdown_parent_context import (
    MarkdownParentContextExpander,
)
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.rag.rag_context_builder import build_rag_context
from fast_app.services.rag.rag_context_builder import count_structured_context_tokens


async def assemble_rag_context(
    *,
    settings: Settings,
    query: str,
    docs: list[RetrievedDoc],
    filters: Mapping[str, Any] | None,
    source: str,
    parent_expander: MarkdownParentContextExpander | None = None,
    prompt_guard: PromptGuardService | None = None,
) -> RagContext:
    """按父块扩展、Prompt Guard、token 装箱的固定顺序构造上下文。"""

    if parent_expander is not None:
        docs = await parent_expander.expand(
            docs,
            build_retrieval_filters_from_mapping(filters),
        )
    if prompt_guard is not None:
        docs = await prompt_guard.filter_retrieved_docs(docs, source=source)
    context = build_rag_context(
        query,
        docs,
        max_context_tokens=settings.rag_parent_context_max_tokens,
    )
    record_snapshot_final_context(context)
    return context


def build_context_observation(context: RagContext) -> dict[str, object]:
    matched_child_ids = {
        str(child_id)
        for doc in context.docs
        for child_id in doc.metadata.get("matched_child_ids", [])
    }
    parent_latencies = [
        float(value)
        for doc in context.docs
        if (value := doc.metadata.get("parent_lookup_latency_ms")) is not None
    ]
    return {
        "child_hit_count": len(matched_child_ids),
        "unique_parent_count": sum(
            doc.metadata.get("chunk_level") == "parent" for doc in context.docs
        ),
        "parent_lookup_latency_ms": max(parent_latencies, default=0.0),
        "expanded_count": sum(
            doc.metadata.get("chunk_level") == "parent" for doc in context.docs
        ),
        "fallback_count": sum(
            doc.metadata.get("parent_expansion_degraded") is True
            for doc in context.docs
        ),
        "context_token_count": count_structured_context_tokens(context.docs),
        "chunk_strategy_version": sorted(
            {
                str(version)
                for doc in context.docs
                if (version := doc.metadata.get("chunk_strategy_version"))
            }
        ),
    }
