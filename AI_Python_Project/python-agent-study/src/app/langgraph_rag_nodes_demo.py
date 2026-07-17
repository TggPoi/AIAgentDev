import asyncio

from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.graph.rag.rag_graph_nodes import (
    create_build_context_node,
    create_generate_node,
    create_retrieve_node,
)
from fast_app.graph.rag.rag_graph_state import GraphRagState

# 测试rag_graph_nodes里面实现的node节点

async def main() -> None:
    state: GraphRagState = {
        "query": "什么是混合检索？",
        "mode": "hybrid",
        "top_k": 5,
        "min_score": 0.8,
        "docs": [],
        "context": None,
        "answer": None,
    }

    retrieve_node = create_retrieve_node(
        vector_retriever=MockVectorRetriever(),
        keyword_retriever=MockKeywordRetriever(),
    )
    build_context_node = create_build_context_node()
    generate_node = create_generate_node(
        llm_client=MockLLMClient(),
    )

    retrieve_update = await retrieve_node(state)
    state.update(retrieve_update)

    print("retrieve_node 更新后：")
    print(state)

    context_update = await build_context_node(state)
    state.update(context_update)

    print("\nbuild_context_node 更新后：")
    print(state)

    answer_update = await generate_node(state)
    state.update(answer_update)

    print("\ngenerate_node 更新后：")
    print(state)


if __name__ == "__main__":
    asyncio.run(main())


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/langgraph_rag_nodes_demo.py
# retrieve_node 更新后：
# {'query': '什么是混合检索？', 'mode': 'hybrid', 'top_k': 5, 'min_score': 0.8, 'docs': [RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')], 'context': None, 'answer': None}

# build_context_node 更新后：
# {'query': '什么是混合检索？', 'mode': 'hybrid', 'top_k': 5, 'min_score': 0.8, 'docs': [RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')], 'context': RagContext(text='[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。', docs=[RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')]), 'answer': None}

# generate_node 更新后：
# {'query': '什么是混合检索？', 'mode': 'hybrid', 'top_k': 5, 'min_score': 0.8, 'docs': [RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')], 'context': RagContext(text='[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。', docs=[RetrievedDoc(id='doc_milvus_001', content='Milvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。', score=0.91, source='milvus'), RetrievedDoc(id='doc_es_001', content='ElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。', score=0.88, source='elasticsearch'), RetrievedDoc(id='doc_shared_001', content='混合检索会结合语义召回和关键词召回。', score=0.86, source='milvus')]), 'answer': '根据检索到的上下文，回答问题：什么是混合检索？\n核心结论：混合检索会同时利用向量检索和关键词检索，再通过合并、去重、排序等步骤得到更可靠的上下文。\n\n参考上下文：\n[0] source=milvus, score=0.91\nMilvus 向量召回结果：什么是混合检索？ 通常需要向量相似度搜索。\n\n[1] source=elasticsearch, score=0.88\nElasticSearch 关键词召回结果：什么是混合检索？ 可以通过 BM25 匹配关键词。\n\n[2] source=milvus, score=0.86\n混合检索会结合语义召回和关键词召回。'}