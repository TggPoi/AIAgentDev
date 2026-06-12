from langgraph.graph import END, START, StateGraph

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.components.rerankers.base import BaseReranker
from fast_app.graph.rag_graph_nodes import (
    create_build_context_node,
    create_generate_node,
    create_rerank_node,
    create_retrieve_node,
)
from fast_app.graph.rag_graph_state import GraphRagState

# 组装完整 graph 可运行对象结构
def build_rag_graph(
    vector_retriever: BaseRetriever,
    keyword_retriever: BaseRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
    rerank_top_k: int,
):
    builder = StateGraph(GraphRagState)

    builder.add_node(
        "retrieve",
        create_retrieve_node(
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
        ),
    )
    builder.add_node(
        "build_context",
        create_build_context_node(),
    )
    builder.add_node(
        "generate",
        create_generate_node(llm_client=llm_client),
    )
    builder.add_node(
        "rerank",
        create_rerank_node(
            reranker=reranker,
            rerank_top_k=rerank_top_k,
        ),
    )

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "rerank")
    builder.add_edge("rerank", "build_context")
    builder.add_edge("build_context", "generate")
    builder.add_edge("generate", END)

    return builder.compile()