import asyncio
from collections.abc import Callable
from time import perf_counter

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.graph.rag_graph_state import GraphRagState
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag_pipeline_service import (
    build_top_doc_ids,
    build_rag_context,
    filter_docs_by_mode,
    filter_docs_by_score,
)
from fast_app.services.retrieval_fusion import reciprocal_rank_fusion

from fast_app.components.rerankers.base import BaseReranker


logger = get_logger(__name__)


GraphNode = Callable[[GraphRagState], dict]

# 重排序节点 只处理 rerank 只接收和返回 docs
def create_rerank_node(
    reranker: BaseReranker,
    rerank_top_k: int,
) -> Callable[[GraphRagState], object]:

    async def rerank_node(state: GraphRagState) -> dict[str, list[RetrievedDoc]]:
        docs = state["docs"]

        if not docs:
            return {"docs": []}

        start_time = perf_counter()
        top_k = min(rerank_top_k, len(docs))
        logger.info(
            "rag_rerank %s",
            format_log_fields(
                event="rag.rerank.start",
                pipeline_provider="langgraph",
                candidate_count=len(docs),
                top_k=top_k,
                top_doc_ids=build_top_doc_ids(docs),
            ),
        )

        try:
            reranked_docs = await reranker.rerank(
                query=state["query"],
                docs=docs,
                top_k=top_k,
            )
            latency_ms = (perf_counter() - start_time) * 1000
            logger.info(
                "rag_rerank %s",
                format_log_fields(
                    event="rag.rerank.finish",
                    pipeline_provider="langgraph",
                    candidate_count=len(docs),
                    result_count=len(reranked_docs),
                    top_k=top_k,
                    latency_ms=round(latency_ms, 2),
                    fallback=False,
                    top_doc_ids=build_top_doc_ids(reranked_docs),
                ),
            )
            return {"docs": reranked_docs}

        except ExternalServiceError as exc:
            fallback_docs = docs[:rerank_top_k]
            latency_ms = (perf_counter() - start_time) * 1000
            logger.warning(
                "rag_rerank %s",
                format_log_fields(
                    event="rag.rerank.fallback",
                    pipeline_provider="langgraph",
                    candidate_count=len(docs),
                    result_count=len(fallback_docs),
                    top_k=top_k,
                    latency_ms=round(latency_ms, 2),
                    fallback=True,
                    error_type=type(exc).__name__,
                    top_doc_ids=build_top_doc_ids(fallback_docs),
                ),
            )
            return {"docs": fallback_docs}

    return rerank_node

# 构造检索过滤条件
def build_graph_retrieval_options(state: GraphRagState) -> RetrievalOptions:
    raw_filters = state.get("filters", {})
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    # 提取过滤器中的参数
    raw_section_path = filters.get("section_path") or []
    section_path = (
        [str(item) for item in raw_section_path]
        if isinstance(raw_section_path, list)
        else []
    )

    source_path = filters.get("source_path")
    top_k = state["top_k"]
    candidate_k = max(state.get("candidate_k") or top_k, top_k)

    return RetrievalOptions(
        top_k=top_k,
        candidate_k=candidate_k,
        filters=RetrievalFilters(
            source_path=str(source_path) if source_path else None,
            section_path=section_path,
        ),
    )

# Node Factory **如果直接在 node 里 new，vector_retriever = MockVectorRetriever() **就破坏了阶段 4-7 的可替换组件设计。
# 外层函数接收组件依赖。内层函数才是真正的 LangGraph node。内层 node 通过闭包使用外层传入的组件。

# 这里的返回值使用模糊的Object 因为 精确标注会涉及 Awaitable / Mapping / Partial State 等类型，目前先用 object 代替，后续可以根据实际情况细化类型标注
def create_retrieve_node(
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
) -> Callable[[GraphRagState], object]:
    
    # 构造node需要的 partial<State> update
    async def retrieve_node(state: GraphRagState) -> dict[str, list[RetrievedDoc]]:
        query = state["query"]
        mode = state["mode"]
        top_k = state["top_k"]
        min_score = state["min_score"]
        options = build_graph_retrieval_options(state)

        if mode == "vector":
            logger.info(
                "rag_retrieval %s",
                format_log_fields(
                    event="rag.retrieval.vector.start",
                    pipeline_provider="langgraph",
                    retrieval_mode=mode,
                    retriever="vector",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                ),
            )

            start_time = perf_counter()
            try:
                docs = await vector_retriever.retrieve(query, options)
                filtered_docs = filter_docs_by_score(docs, min_score)
                returned_docs = filtered_docs[:top_k]
                latency_ms = (perf_counter() - start_time) * 1000

                logger.info(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.vector.finish",
                        pipeline_provider="langgraph",
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

                if len(returned_docs) == 0:
                    raise NoSearchResultError(
                        f"没有找到满足 min_score={min_score} 的向量检索结果"
                    )

                return {"docs": returned_docs}
            except Exception:
                latency_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.vector.failed",
                        pipeline_provider="langgraph",
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
                    pipeline_provider="langgraph",
                    retrieval_mode=mode,
                    retriever="keyword",
                    query=query,
                    top_k=top_k,
                    candidate_k=options.candidate_k,
                    min_score=min_score,
                ),
            )

            start_time = perf_counter()
            try:
                docs = await keyword_retriever.retrieve(query, options)
                filtered_docs = filter_docs_by_mode(docs, mode, min_score)
                returned_docs = filtered_docs[:top_k]
                latency_ms = (perf_counter() - start_time) * 1000

                logger.info(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.keyword.finish",
                        pipeline_provider="langgraph",
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

                if len(returned_docs) == 0:
                    raise NoSearchResultError(
                        f"没有找到满足 min_score={min_score} 的关键词检索结果"
                    )

                return {"docs": returned_docs}
            except Exception:
                latency_ms = (perf_counter() - start_time) * 1000
                logger.exception(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.keyword.failed",
                        pipeline_provider="langgraph",
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
                pipeline_provider="langgraph",
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
                        pipeline_provider="langgraph",
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
                return filtered_docs
            except Exception as exc:
                latency_ms = (perf_counter() - source_start_time) * 1000
                logger.warning(
                    "rag_retrieval %s",
                    format_log_fields(
                        event="rag.retrieval.source.failed",
                        pipeline_provider="langgraph",
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
                    pipeline_provider="langgraph",
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
        unique_doc_count = len(
            {doc.id for docs in successful_doc_lists for doc in docs}
        )
        merged_docs = reciprocal_rank_fusion(
            doc_lists=successful_doc_lists,
            top_k=top_k,
        )
        latency_ms = (perf_counter() - hybrid_start_time) * 1000

        logger.info(
            "rag_retrieval %s",
            format_log_fields(
                event="rag.retrieval.rrf.finish",
                pipeline_provider="langgraph",
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

        if len(merged_docs) == 0:
            raise NoSearchResultError(
                f"没有找到满足 min_score={min_score} 的混合检索结果"
            )

        return {"docs": merged_docs}

    return retrieve_node


def create_build_context_node() -> Callable[[GraphRagState], dict[str, RagContext]]:

    async def build_context_node(state: GraphRagState) -> dict[str, RagContext]:
        docs = state["docs"]

        logger.info("LangGraph 开始构造上下文: docs_count=%s", len(docs))

        context = build_rag_context(state["query"], docs)

        logger.info(
            "LangGraph 上下文构造完成: context_docs_count=%s",
            len(context.docs),
        )

        return {"context": context}

    return build_context_node


def create_generate_node(
    llm_client: BaseLLMClient,
) -> Callable[[GraphRagState], object]:
    
    async def generate_node(state: GraphRagState) -> dict[str, str]:
        query = state["query"]
        context = state["context"]

        if context is None:
            raise ExternalServiceError("上下文为空，无法生成回答")

        logger.info("LangGraph 开始生成回答: query=%s", query)

        answer = await llm_client.generate(
            query=query,
            context=context,
        )

        logger.info("LangGraph 回答生成完成: answer_length=%s", len(answer))

        return {"answer": answer}

    return generate_node
