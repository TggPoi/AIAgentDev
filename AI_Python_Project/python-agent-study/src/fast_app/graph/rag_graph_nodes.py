import asyncio
from collections.abc import Callable

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.logging import get_logger
from fast_app.domain.rag_models import RagContext, RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.graph.rag_graph_state import GraphRagState
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag_pipeline_service import (
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

        try:
            reranked_docs = await reranker.rerank(
                query=state["query"],
                docs=docs,
                top_k=min(rerank_top_k, len(docs)),
            )
            return {"docs": reranked_docs}

        except ExternalServiceError as exc:
            logger.warning("LangGraph Rerank 失败，使用召回结果降级继续: %s", exc)
            return {"docs": docs[:rerank_top_k]}

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
            logger.info("LangGraph 开始向量检索: query=%s", query)

            docs = await vector_retriever.retrieve(query, options)
            filtered_docs = filter_docs_by_score(docs, min_score)

            logger.info(
                "LangGraph 向量检索完成: raw_count=%s, filtered_count=%s",
                len(docs),
                len(filtered_docs),
            )

            if len(filtered_docs) == 0:
                raise NoSearchResultError(
                    f"没有找到满足 min_score={min_score} 的向量检索结果"
                )

            return {"docs": filtered_docs[:top_k]}

        if mode == "keyword":
            logger.info("LangGraph 开始关键词检索: query=%s", query)

            docs = await keyword_retriever.retrieve(query, options)
            filtered_docs = filter_docs_by_mode(docs, mode, min_score)

            logger.info(
                "LangGraph 关键词检索完成: raw_count=%s, filtered_count=%s",
                len(docs),
                len(filtered_docs),
            )

            if len(filtered_docs) == 0:
                raise NoSearchResultError(
                    f"没有找到满足 min_score={min_score} 的关键词检索结果"
                )

            return {"docs": filtered_docs[:top_k]}

        # 开始混合检索
        logger.info("LangGraph 开始混合检索: query=%s", query)

        results = await asyncio.gather(
            vector_retriever.retrieve(query, options),
            keyword_retriever.retrieve(query, options),
            return_exceptions=True,
        )

        successful_doc_lists: list[list[RetrievedDoc]] = []

        for result in results:
            if isinstance(result, Exception):
                logger.warning("LangGraph 召回源失败: %s", result)
                continue

            filtered_docs = filter_docs_by_mode(
                docs=result,
                mode=mode,
                min_score=min_score,
            )
            successful_doc_lists.append(filtered_docs)

        if len(successful_doc_lists) == 0:
            raise ExternalServiceError("所有召回源都失败")

        # merged_docs = merge_docs_by_id(
        #     doc_lists=successful_doc_lists,
        #     top_k=top_k,
        # )

        # 使用RRF的方案
        merged_docs = reciprocal_rank_fusion(
            doc_lists=successful_doc_lists,
            top_k=top_k,
        )

        logger.info(
            "LangGraph 混合检索合并完成: source_count=%s, merged_count=%s",
            len(successful_doc_lists),
            len(merged_docs),
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
