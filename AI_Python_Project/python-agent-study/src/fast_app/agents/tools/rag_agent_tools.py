import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.core.latency import log_slow_operation
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import (
    RetrievalFilters,
    RetrievalOptions,
    RetrievedDoc,
)
from fast_app.evaluation.pipeline.snapshot_capture import (
    record_snapshot_retrieval_error,
    record_snapshot_retrieval_stage,
)
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag.rag_pipeline_service import (
    build_content_preview,
    build_top_doc_ids,
    filter_docs_by_mode,
    filter_docs_by_score,
)
from fast_app.services.rag.retrieval_fusion import reciprocal_rank_fusion


logger = get_logger(__name__)

KnowledgeRetrievalMode = Literal["vector", "keyword", "hybrid"]
RetrievalProgressCallback = Callable[
    [str, Literal["started", "finished", "failed"]],
    Awaitable[None],
]
# Agent调用的工具名称
KNOWLEDGE_RETRIEVAL_TOOL_NAME = "knowledge_retrieval"


async def _notify_retrieval_progress(
    callback: RetrievalProgressCallback | None,
    operation: str,
    status: Literal["started", "finished", "failed"],
) -> None:
    if callback is not None:
        await callback(operation, status)

# 文档检索tool调用的结构化 输入对象格式
class KnowledgeRetrievalToolInput(BaseModel):
    query: str = Field(description="用户问题或改写后的检索 query")
    mode: KnowledgeRetrievalMode = Field(
        default="hybrid",
        description="检索模式：vector / keyword / hybrid",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="最终返回的文档数量")
    candidate_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="每个召回源的候选数量；为空时使用 top_k",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最小相关性分数",
    )
    source_path: str | None = Field(
        default=None,
        description="可选文档来源路径过滤条件",
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="可选章节路径过滤条件",
    )

# 构建检索参数
def build_knowledge_retrieval_options(
    *,
    top_k: int,
    candidate_k: int | None,
    filters: RetrievalFilters,
) -> RetrievalOptions:
    return RetrievalOptions(
        top_k=top_k,
        candidate_k=max(candidate_k or top_k, top_k),
        filters=filters,
    )

# 实际调用 Vector，ES，Hybrid检索
async def retrieve_knowledge_docs(
    *,
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    query: str,
    mode: KnowledgeRetrievalMode,
    top_k: int,
    candidate_k: int | None,
    min_score: float,
    filters: RetrievalFilters,
    pipeline_provider: str = "langgraph",
    on_progress: RetrievalProgressCallback | None = None,
) -> list[RetrievedDoc]:
    options = build_knowledge_retrieval_options(
        top_k=top_k,
        candidate_k=candidate_k,
        filters=filters,
    )

    if mode == "vector":
        logger.info(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.vector.start",
                pipeline_provider=pipeline_provider,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                retrieval_mode=mode,
                retriever="vector",
                query=query,
                top_k=top_k,
                candidate_k=options.candidate_k,
                min_score=min_score,
            ),
        )

        start_time = perf_counter()
        await _notify_retrieval_progress(on_progress, "vector_retrieval", "started")
        try:
            docs = await vector_retriever.retrieve(query, options)
            filtered_docs = filter_docs_by_score(docs, min_score)
            returned_docs = filtered_docs[:top_k]
            latency_ms = (perf_counter() - start_time) * 1000

            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.vector.finish",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever="vector",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    raw_count=len(docs),
                    filtered_count=len(filtered_docs),
                    returned_count=len(returned_docs),
                    latency_ms=round(latency_ms, 2),
                    top_doc_ids=build_top_doc_ids(returned_docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag.retrieval.slow",
                latency_ms=latency_ms,
                threshold_ms=settings.slow_retrieval_threshold_ms,
                slow_component="retrieval",
                pipeline_provider=pipeline_provider,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                retrieval_mode=mode,
                retriever="vector",
                top_k=top_k,
                candidate_k=options.candidate_k,
                returned_count=len(returned_docs),
            )

            if len(returned_docs) == 0:
                raise NoSearchResultError(
                    f"没有找到满足 min_score={min_score} 的向量检索结果"
                )

            record_snapshot_retrieval_stage(
                "vector",
                filtered_docs,
                query=query,
            )
            await _notify_retrieval_progress(
                on_progress,
                "vector_retrieval",
                "finished",
            )
            return returned_docs
        except Exception:
            record_snapshot_retrieval_error(
                "vector",
                "VECTOR_RETRIEVAL_FAILED",
                query=query,
            )
            await _notify_retrieval_progress(
                on_progress,
                "vector_retrieval",
                "failed",
            )
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.vector.failed",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever="vector",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise

    if mode == "keyword":
        logger.info(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.keyword.start",
                pipeline_provider=pipeline_provider,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                retrieval_mode=mode,
                retriever="keyword",
                query=query,
                top_k=top_k,
                candidate_k=options.candidate_k,
                min_score=min_score,
            ),
        )

        start_time = perf_counter()
        await _notify_retrieval_progress(on_progress, "keyword_retrieval", "started")
        try:
            docs = await keyword_retriever.retrieve(query, options)
            filtered_docs = filter_docs_by_mode(docs, mode, min_score)
            returned_docs = filtered_docs[:top_k]
            latency_ms = (perf_counter() - start_time) * 1000

            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.keyword.finish",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever="keyword",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    raw_count=len(docs),
                    filtered_count=len(filtered_docs),
                    returned_count=len(returned_docs),
                    latency_ms=round(latency_ms, 2),
                    top_doc_ids=build_top_doc_ids(returned_docs),
                ),
            )
            log_slow_operation(
                logger=logger,
                event="rag.retrieval.slow",
                latency_ms=latency_ms,
                threshold_ms=settings.slow_retrieval_threshold_ms,
                slow_component="retrieval",
                pipeline_provider=pipeline_provider,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                retrieval_mode=mode,
                retriever="keyword",
                top_k=top_k,
                candidate_k=options.candidate_k,
                returned_count=len(returned_docs),
            )

            if len(returned_docs) == 0:
                raise NoSearchResultError(
                    f"没有找到满足 min_score={min_score} 的关键词检索结果"
                )

            record_snapshot_retrieval_stage(
                "keyword",
                filtered_docs,
                query=query,
            )
            await _notify_retrieval_progress(
                on_progress,
                "keyword_retrieval",
                "finished",
            )
            return returned_docs
        except Exception:
            record_snapshot_retrieval_error(
                "keyword",
                "KEYWORD_RETRIEVAL_FAILED",
                query=query,
            )
            await _notify_retrieval_progress(
                on_progress,
                "keyword_retrieval",
                "failed",
            )
            latency_ms = (perf_counter() - start_time) * 1000
            logger.exception(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.keyword.failed",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever="keyword",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    latency_ms=round(latency_ms, 2),
                ),
            )
            raise

    logger.info(
        "rag_retrieval %s",
        format_log_fields(
            event="rag.retrieval.hybrid.start",
            pipeline_provider=pipeline_provider,
            tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
            retrieval_mode=mode,
            query=query,
            top_k=top_k,
            candidate_k=options.candidate_k,
            min_score=min_score,
        ),
    )

    async def retrieve_source(
        retriever_name: str,
        retriever: BaseRetriever,
    ) -> list[RetrievedDoc] | Exception:
        operation = f"{retriever_name}_retrieval"
        await _notify_retrieval_progress(on_progress, operation, "started")
        source_start_time = perf_counter()
        try:
            docs = await retriever.retrieve(query, options)
            filtered_docs = filter_docs_by_mode(
                docs=docs,
                mode=mode,
                min_score=min_score,
            )
            latency_ms = (perf_counter() - source_start_time) * 1000
            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.source.finish",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever=retriever_name,
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    raw_count=len(docs),
                    filtered_count=len(filtered_docs),
                    returned_count=len(filtered_docs),
                    latency_ms=round(latency_ms, 2),
                    top_doc_ids=build_top_doc_ids(filtered_docs),
                ),
            )
            record_snapshot_retrieval_stage(
                "vector" if retriever_name == "vector" else "keyword",
                filtered_docs,
                query=query,
            )
            await _notify_retrieval_progress(on_progress, operation, "finished")
            return filtered_docs
        except Exception as exc:
            record_snapshot_retrieval_error(
                "vector" if retriever_name == "vector" else "keyword",
                f"{retriever_name.upper()}_RETRIEVAL_FAILED",
                query=query,
            )
            await _notify_retrieval_progress(on_progress, operation, "failed")
            latency_ms = (perf_counter() - source_start_time) * 1000
            logger.warning(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.source.failed",
                    pipeline_provider=pipeline_provider,
                    tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                    retrieval_mode=mode,
                    retriever=retriever_name,
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                    latency_ms=round(latency_ms, 2),
                    error_type=type(exc).__name__,
                ),
            )
            return exc

    hybrid_start_time = perf_counter()
    results = await asyncio.gather(
        retrieve_source("vector", vector_retriever),
        retrieve_source("keyword", keyword_retriever),
    )

    successful_doc_lists: list[list[RetrievedDoc]] = []

    for result in results:
        if isinstance(result, Exception):
            continue

        successful_doc_lists.append(result)

    if len(successful_doc_lists) == 0:
        latency_ms = (perf_counter() - hybrid_start_time) * 1000
        logger.error(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.failed",
                pipeline_provider=pipeline_provider,
                tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
                retrieval_mode=mode,
                query=query,
                top_k=top_k,
                candidate_k=options.candidate_k,
                min_score=min_score,
                latency_ms=round(latency_ms, 2),
                source_count=0,
            ),
        )
        raise ExternalServiceError("所有召回源都失败")

    input_doc_count = sum(len(docs) for docs in successful_doc_lists)
    unique_doc_count = len({doc.id for docs in successful_doc_lists for doc in docs})
    merged_docs = reciprocal_rank_fusion(
        doc_lists=successful_doc_lists,
        top_k=top_k,
    )
    latency_ms = (perf_counter() - hybrid_start_time) * 1000

    logger.info(
        "rag_retrieval %s",
        format_log_fields(
            event="rag.retrieval.rrf.finish",
            pipeline_provider=pipeline_provider,
            tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
            retrieval_mode=mode,
            query=query,
            top_k=top_k,
            candidate_k=options.candidate_k,
            min_score=min_score,
            source_count=len(successful_doc_lists),
            input_doc_count=input_doc_count,
            unique_doc_count=unique_doc_count,
            output_doc_count=len(merged_docs),
            latency_ms=round(latency_ms, 2),
            top_doc_ids=build_top_doc_ids(merged_docs),
        ),
    )
    log_slow_operation(
        logger=logger,
        event="rag.retrieval.slow",
        latency_ms=latency_ms,
        threshold_ms=settings.slow_retrieval_threshold_ms,
        slow_component="retrieval",
        pipeline_provider=pipeline_provider,
        tool_name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
        retrieval_mode=mode,
        retriever="hybrid",
        top_k=top_k,
        candidate_k=options.candidate_k,
        source_count=len(successful_doc_lists),
        input_doc_count=input_doc_count,
        unique_doc_count=unique_doc_count,
        output_doc_count=len(merged_docs),
    )

    if len(merged_docs) == 0:
        raise NoSearchResultError(f"没有找到满足 min_score={min_score} 的混合检索结果")

    record_snapshot_retrieval_stage(
        "rrf",
        merged_docs,
        query=query,
    )
    return merged_docs

# tool调用结果格式化处理
def summarize_retrieved_docs(docs: list[RetrievedDoc]) -> str:
    lines = [
        f"检索到 {len(docs)} 条知识库片段。",
    ]

    for index, doc in enumerate(docs, start=1):
        lines.append(
            (
                f"{index}. id={doc.id}, source={doc.source}, score={doc.score:.4f}, "
                f"title={doc.title or ''}, preview={build_content_preview(doc.content)}"
            )
        )

    return "\n".join(lines)

# 构建Agent可调用的tool格式
def build_knowledge_retrieval_tool(
    settings: Settings,
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
) -> BaseTool:
    async def knowledge_retrieval(
        query: str,
        mode: KnowledgeRetrievalMode = "hybrid",
        top_k: int = 5,
        candidate_k: int | None = None,
        min_score: float = 0.0,
        source_path: str | None = None,
        section_path: list[str] | None = None,
    ) -> str:
        docs = await retrieve_knowledge_docs(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            query=query,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            min_score=min_score,
            filters=RetrievalFilters(
                source_path=source_path,
                section_path=section_path or [],
            ),
            pipeline_provider="agent_tool",
        )
        return summarize_retrieved_docs(docs)

    return StructuredTool.from_function(
        coroutine=knowledge_retrieval,
        name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
        description=(
            "检索项目知识库，适合回答需要知识库上下文的问题。"
            "返回检索片段摘要；显式 Graph 会直接复用底层 helper 获取结构化 docs。"
        ),
        args_schema=KnowledgeRetrievalToolInput,
    )
