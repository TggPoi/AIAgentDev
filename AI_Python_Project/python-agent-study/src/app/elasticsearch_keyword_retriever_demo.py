import asyncio

from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.core.config import get_settings


async def main() -> None:
    settings = get_settings()

    retriever = ElasticsearchKeywordRetriever(settings=settings)

    try:
        query = "什么是混合检索？"

        docs = await retriever.retrieve(query)

        print(f"query: {query}")
        print(f"docs_count: {len(docs)}")

        for doc in docs:
            print("-" * 80)
            print(f"id: {doc.id}")
            print(f"source: {doc.source}")
            print(f"score: {doc.score}")
            print(f"content: {doc.content}")

    finally:
        await retriever.close()


if __name__ == "__main__":
    asyncio.run(main())

# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/elasticsearch_keyword_retriever_demo.py
# query: 什么是混合检索？
# docs_count: 5
# --------------------------------------------------------------------------------
# id: rag_hybrid_001
# source: elasticsearch
# score: 2.7117786
# content: 混合检索会同时结合向量检索和关键词检索。向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。
# --------------------------------------------------------------------------------
# id: rag_basic_001
# source: elasticsearch
# score: 0.7979634
# content: RAG 是 Retrieval-Augmented Generation 的缩写，中文通常称为检索增强生成。它的核心思想是在大模型生成回答之前，先从外部知识库中检索相关内容，再把检索结果作为上下文提供给大模型，从而提升回答的准确性和可追溯性。
# --------------------------------------------------------------------------------
# id: rag_keyword_001
# source: elasticsearch
# score: 0.6869241
# content: 关键词检索通常基于倒排索引和 BM25 等相关性算法。它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。ElasticSearch 是常见的关键词检索引擎。
# --------------------------------------------------------------------------------
# id: es_basic_001
# source: elasticsearch
# score: 0.66702056
# content: ElasticSearch 是一个分布式搜索引擎，擅长全文检索、关键词匹配、过滤、排序和聚合。在 RAG 系统中，ElasticSearch 常用于关键词检索，尤其适合匹配错误日志、函数名、类名、配置项和专业术语。
# --------------------------------------------------------------------------------
# id: milvus_basic_001
# source: elasticsearch
# score: 0.5701978
# content: Milvus 是一个向量数据库，常用于存储文本、图片、音频等数据的向量表示。在 RAG 系统中，Milvus 通常负责根据 query embedding 检索相似的文档 chunk。使用 Milvus 时，需要保证 collection 的向量维度和 embedding 模型输出维度一致。