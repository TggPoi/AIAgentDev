import asyncio

from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.graph.rag_graph_builder import build_rag_graph
from fast_app.graph.rag_graph_state import GraphRagState


async def main() -> None:
    graph = build_rag_graph(
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(),
    )

    initial_state: GraphRagState = {
        "query": "什么是混合检索？",
        "mode": "hybrid",
        "top_k": 5,
        "min_score": 0.8,
        "docs": [],
        "context": None,
        "answer": None,
    }

# stream_mode
# The mode to stream output, defaults to self.stream_mode.

# Options are:

# "values": Emit all values in the state after each step, including interrupts. When used with functional API, values are emitted once at the end of the workflow.
# "updates": Emit only the node or task names and updates returned by the nodes or tasks after each step. If multiple updates are made in the same step (e.g. multiple nodes are run) then those updates are emitted separately.
# "custom": Emit custom data from inside nodes or tasks using StreamWriter.
# "messages": Emit LLM messages token-by-token together with metadata for any LLM invocations inside nodes or tasks.
# Will be emitted as 2-tuples (LLM token, metadata).
# "checkpoints": Emit an event when a checkpoint is created, in the same format as returned by get_state().
# "tasks": Emit events when tasks start and finish, including their results and errors.
# "debug": Emit debug events with as much information as possible for each step.

    async for chunk in graph.astream(
        initial_state,
        stream_mode="updates",
    ):
        print("Graph update:")
        print(chunk)


if __name__ == "__main__":
    asyncio.run(main())


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/langgraph_stream_updates_demo.py
# Graph update:
# {'retrieve': {'docs': [RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')]}}
# Graph update:
# {'build_context': {'context': RagContext(text='[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。', docs=[RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')])}}
# Graph update:
# {'generate': {'answer': '根据检索到的上下文，回答问题：什么是混合检索？\n核心结论：混合检索会同时利用向量检索和关键词检索，再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n参考上下文：\n[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。'}}