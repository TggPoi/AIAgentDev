import asyncio
from datetime import UTC, datetime
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from app.build_demo_chunks import build_demo_chunks
from fast_app.core.config import get_settings


def build_index_mapping() -> dict[str, Any]:
    return {
        "mappings": {
            "properties": {
                "id": {
                    "type": "keyword",
                },
                "content": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart",
                },
                "title": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                        }
                    },
                },
                "source": {
                    "type": "keyword",
                },
                "created_at": {
                    "type": "date",
                },
            }
        }
    }


async def create_index_if_needed(
    client: AsyncElasticsearch,
    index_name: str,
) -> None:
    exists = await client.indices.exists(index=index_name)

    if exists:
        print(f"Index 已存在: {index_name}")
        return

    await client.indices.create(
        index=index_name,
        **build_index_mapping(),
    )

    print(f"Index 创建完成: {index_name}")


def build_bulk_actions(index_name: str) -> list[dict[str, Any]]:
    chunks = build_demo_chunks()
    now = datetime.now(UTC).isoformat()

    actions: list[dict[str, Any]] = []

    for chunk in chunks:
        actions.append(
            {
                "_op_type": "index",
                "_index": index_name,
                "_id": chunk.id,
                "_source": {
                    "id": chunk.id,
                    "content": chunk.content,
                    "title": chunk.title,
                    "source": chunk.source,
                    "created_at": now,
                },
            }
        )

    return actions


async def search_smoke_test(
    client: AsyncElasticsearch,
    index_name: str,
) -> None:
    query = "什么是混合检索？"

    response = await client.search(
        index=index_name,
        query={
            "match": {
                "content": query,
            }
        },
        size=3,
    )

    hits = response["hits"]["hits"]

    print("\nSearch smoke test:")
    print(f"query: {query}")
    print(f"hits_count: {len(hits)}")

    for hit in hits:
        source = hit["_source"]

        print("-" * 80)
        print(f"id: {source['id']}")
        print(f"score: {hit['_score']}")
        print(f"title: {source['title']}")
        print(f"source: {source['source']}")
        print(f"content: {source['content']}")


async def main() -> None:
    settings = get_settings()

    client = AsyncElasticsearch(
        hosts=[settings.elasticsearch_url],
    )

    try:
        print(f"ElasticSearch URL: {settings.elasticsearch_url}")
        print(f"Index: {settings.elasticsearch_index_name}")

        await create_index_if_needed(
            client=client,
            index_name=settings.elasticsearch_index_name,
        )

        actions = build_bulk_actions(
            index_name=settings.elasticsearch_index_name,
        )

        success_count, errors = await async_bulk(
            client=client,
            actions=actions,
            refresh=True,
        )

        print(f"Bulk 写入成功数量: {success_count}")

        if errors:
            print("Bulk 写入存在错误:")
            print(errors)

        await search_smoke_test(
            client=client,
            index_name=settings.elasticsearch_index_name,
        )

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/ingest_elasticsearch_docs.py
# ElasticSearch URL: http://127.0.0.1:9200
# Index: python_agent_demo_chunks
# Index 创建完成: python_agent_demo_chunks
# Bulk 写入成功数量: 7

# Search smoke test:
# query: 什么是混合检索？
# hits_count: 3
# --------------------------------------------------------------------------------
# id: rag_hybrid_001
# score: 2.7117786
# title: 混合检索
# source: demo
# content: 混合检索会同时结合向量检索和关键词检索。向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。
# --------------------------------------------------------------------------------
# id: rag_basic_001
# score: 0.7979634
# title: RAG 基础
# source: demo
# content: RAG 是 Retrieval-Augmented Generation 的缩写，中文通常称为检索增强生成。它的核心思想是在大模型生成回答之前，先从外部知识库中检索相关内容，再把检索结果作为上下文提供给大模型，从而提升回答的准确性和可追溯性。
# --------------------------------------------------------------------------------
# id: rag_keyword_001
# score: 0.6869241
# title: 关键词检索
# source: demo
# content: 关键词检索通常基于倒排索引和 BM25 等相关性算法。它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。ElasticSearch 是常见的关键词检索引擎。