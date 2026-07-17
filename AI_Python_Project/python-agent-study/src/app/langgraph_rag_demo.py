import asyncio

from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.graph.rag.rag_graph_builder import build_rag_graph
from fast_app.graph.rag.rag_graph_state import GraphRagState

from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.core.config import get_settings

# 使用mock数据测试已实现的build_rag_graph图表

async def main() -> None:
    graph = build_rag_graph(
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
        llm_client=MockLLMClient(),
    )

    # 接入qwen模型测试
    # settings = get_settings()
    # graph = build_rag_graph(
    #     vector_retriever=MockVectorRetriever(),
    #     keyword_retriever=MockKeywordRetriever(),
    #     llm_client=QwenLangChainLLMClient(settings=settings),
    # )

    initial_state: GraphRagState = {
        "query": "什么是混合检索？",
        "mode": "hybrid",
        "top_k": 5,
        "min_score": 0.8,
        "docs": [],
        "context": None,
        "answer": None,
    }

    final_state = await graph.ainvoke(initial_state)

    print("最终 State：")
    print(final_state)

    print("\n最终回答：")
    print(final_state["answer"])

    print("\n来源文档：")
    for doc in final_state["docs"]:
        print(f"- {doc.id} | {doc.source} | score={doc.score}")


if __name__ == "__main__":
    asyncio.run(main())


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/langgraph_rag_demo.py
# 最终 State：
# {'query': '什么是混合检索？', 'mode': 'hybrid', 'top_k': 5, 'min_score': 0.8, 'docs': [RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')], 'context': RagContext(text='[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。', docs=[RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')]), 'answer': '根据检索到的上下文，回答问题：什么是混合检索？\n核心结论：混合检索会同时利用向量检索和关键词检索，再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n参考上下文：\n[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。'}

# 最终回答：
# 根据检索到的上下文，回答问题：什么是混合检索？
# 核心结论：混合检索会同时利用向量检索和关键词检索，再通过合并、去重、排序等步骤得到更可靠的上下文。

# 参考上下文：
# [0] source=milvus, score=0.91
# Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。

# [1] source=elasticsearch, score=0.88
# ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。

# [2] source=milvus, score=0.86
# 混合检索会结合语义召回和关键词召回。

# 来源文档：
# - doc_milvus_001 | milvus | score=0.91
# - doc_es_001 | elasticsearch | score=0.88
# - doc_shared_001 | milvus | score=0.86