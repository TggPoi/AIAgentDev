import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from pymilvus import DataType, MilvusClient

from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.core.config import Settings, get_settings
from fast_app.domain.knowledge_models import KnowledgeChunk


@dataclass(frozen=True)
class DemoChunk:
    id: str
    title: str
    source: str
    content: str
    section_path: list[str]
    heading_level: int
    section_index: int
    chunk_index: int
    source_path: str = "demo_docs/rag_intro.md"

    def to_knowledge_chunk(self) -> KnowledgeChunk:
        return KnowledgeChunk(
            id=self.id,
            title=self.title,
            source=self.source,
            content=self.content,
            metadata={
                "section_path": self.section_path,
                "heading_level": self.heading_level,
                "section_index": self.section_index,
                "chunk_index": self.chunk_index,
                "source_path": self.source_path,
            },
        )


def build_demo_chunks() -> list[KnowledgeChunk]:
    demo_chunks = [
        DemoChunk(
            id="rag_basic_001",
            title="RAG 基础",
            source="demo",
            section_path=["RAG 基础教程"],
            heading_level=1,
            section_index=1,
            chunk_index=1,
            content=(
                "RAG 是 Retrieval-Augmented Generation 的缩写，中文通常称为检索增强生成。"
                "它的核心思想是在大模型生成回答之前，先从外部知识库中检索相关内容，"
                "再把检索结果作为上下文提供给大模型，从而提升回答的准确性和可追溯性。"
            ),
        ),
        DemoChunk(
            id="rag_vector_001",
            title="向量检索",
            source="demo",
            section_path=["RAG 基础教程", "向量检索"],
            heading_level=2,
            section_index=2,
            chunk_index=1,
            content=(
                "向量检索会先把文本转换成 embedding 向量，然后通过向量相似度查找语义接近的内容。"
                "它适合处理表达方式不同但语义相似的问题，例如用户没有使用原文关键词，"
                "但问题含义和某段知识非常接近。"
            ),
        ),
        DemoChunk(
            id="rag_keyword_001",
            title="关键词检索",
            source="demo",
            section_path=["RAG 基础教程", "关键词检索"],
            heading_level=2,
            section_index=3,
            chunk_index=1,
            content=(
                "关键词检索通常基于倒排索引和 BM25 等相关性算法。"
                "它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。"
                "ElasticSearch 是常见的关键词检索引擎。"
            ),
        ),
        DemoChunk(
            id="rag_hybrid_001",
            title="混合检索",
            source="demo",
            section_path=["RAG 基础教程", "混合检索"],
            heading_level=2,
            section_index=4,
            chunk_index=1,
            content=(
                "混合检索会同时结合向量检索和关键词检索。"
                "向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。"
                "在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。"
            ),
        ),
        DemoChunk(
            id="milvus_basic_001",
            title="Milvus 基础",
            source="demo",
            section_path=["RAG 基础教程", "向量数据库", "Milvus 基础"],
            heading_level=3,
            section_index=5,
            chunk_index=1,
            content=(
                "Milvus 是一个向量数据库，常用于存储文本、图片、音频等数据的向量表示。"
                "在 RAG 系统中，Milvus 通常负责根据 query embedding 检索相似的文档 chunk。"
                "使用 Milvus 时，需要保证 collection 的向量维度和 embedding 模型输出维度一致。"
            ),
        ),
        DemoChunk(
            id="es_basic_001",
            title="ElasticSearch 基础",
            source="demo",
            section_path=["RAG 基础教程", "搜索引擎", "ElasticSearch 基础"],
            heading_level=3,
            section_index=6,
            chunk_index=1,
            content=(
                "ElasticSearch 是一个分布式搜索引擎，擅长全文检索、关键词匹配、过滤、排序和聚合。"
                "在 RAG 系统中，ElasticSearch 常用于关键词检索，尤其适合匹配错误日志、函数名、"
                "类名、配置项和专业术语。"
            ),
        ),
        DemoChunk(
            id="langgraph_basic_001",
            title="LangGraph 基础",
            source="demo",
            section_path=["Agent 工程", "LangGraph 基础"],
            heading_level=2,
            section_index=7,
            chunk_index=1,
            content=(
                "LangGraph 是用于构建状态化 AI 工作流的框架。"
                "它通过 State 保存流程中的共享数据，通过 Node 执行业务步骤，"
                "通过 Edge 控制节点之间的执行顺序。"
            ),
        ),
    ]

    return [chunk.to_knowledge_chunk() for chunk in demo_chunks]


def build_milvus_uri(settings: Settings) -> str:
    return f"http://{settings.milvus_host}:{settings.milvus_port}"


def build_es_mapping() -> dict[str, Any]:
    return {
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "content": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart",
                },
                "title": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "source": {"type": "keyword"},
                "metadata": {
                    "properties": {
                        "section_path": {"type": "keyword"},
                        "heading_level": {"type": "integer"},
                        "section_index": {"type": "integer"},
                        "chunk_index": {"type": "integer"},
                        "source_path": {"type": "keyword"},
                    }
                },
                "created_at": {"type": "date"},
            }
        }
    }


def build_es_client(settings: Settings) -> AsyncElasticsearch:
    return AsyncElasticsearch(hosts=[settings.elasticsearch_url])


async def recreate_es_index(
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> None:
    client = build_es_client(settings)
    index_name = settings.elasticsearch_index_name

    try:
        if await client.indices.exists(index=index_name):
            await client.indices.delete(index=index_name)
            print(f"ES index 已删除: {index_name}")

        await client.indices.create(index=index_name, **build_es_mapping())
        print(f"ES index 已创建: {index_name}")

        now = datetime.now(UTC).isoformat()
        actions = [
            {
                "_op_type": "index",
                "_index": index_name,
                "_id": chunk.id,
                "_source": {
                    "id": chunk.id,
                    "content": chunk.content,
                    "title": chunk.title,
                    "source": chunk.source,
                    "metadata": chunk.metadata,
                    "created_at": now,
                },
            }
            for chunk in chunks
        ]

        success_count, errors = await async_bulk(
            client=client,
            actions=actions,
            refresh=True,
        )

        print(f"ES bulk 写入成功数量: {success_count}")

        if errors:
            raise RuntimeError(f"ES bulk 写入存在错误: {errors}")

        await es_smoke_test(client, index_name)

    finally:
        await client.close()


async def es_smoke_test(client: AsyncElasticsearch, index_name: str) -> None:
    response = await client.search(
        index=index_name,
        query={"match": {"content": "什么是混合检索？"}},
        size=3,
    )

    hits = response["hits"]["hits"]
    print("\nES smoke test:")
    print(f"hits_count: {len(hits)}")

    for hit in hits:
        source = hit["_source"]
        print("-" * 80)
        print(f"id: {source['id']}")
        print(f"score: {hit['_score']}")
        print(f"title: {source['title']}")
        print(f"section_path: {source['metadata'].get('section_path')}")


def recreate_milvus_collection(
    settings: Settings,
    chunks: list[KnowledgeChunk],
    vectors: list[list[float]],
) -> None:
    uri = build_milvus_uri(settings)
    client = MilvusClient(uri=uri)
    collection_name = settings.milvus_collection_name

    if client.has_collection(collection_name):
        client.drop_collection(collection_name)
        print(f"Milvus collection 已删除: {collection_name}")

    schema = MilvusClient.create_schema(
        auto_id=False,
        enable_dynamic_field=False,
    )
    schema.add_field(
        field_name=settings.milvus_id_field,
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=128,
    )
    schema.add_field(
        field_name=settings.milvus_vector_field,
        datatype=DataType.FLOAT_VECTOR,
        dim=settings.embedding_dim,
    )
    schema.add_field(
        field_name=settings.milvus_content_field,
        datatype=DataType.VARCHAR,
        max_length=4096,
    )
    schema.add_field(
        field_name="source",
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name="title",
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name="metadata",
        datatype=DataType.JSON,
    )

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=settings.milvus_vector_field,
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )
    print(f"Milvus collection 已创建: {collection_name}")

    rows = [
        {
            settings.milvus_id_field: chunk.id,
            settings.milvus_vector_field: vector,
            settings.milvus_content_field: chunk.content,
            "source": chunk.source,
            "title": chunk.title,
            "metadata": chunk.metadata,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    result = client.insert(
        collection_name=collection_name,
        data=rows,
    )
    print(f"Milvus insert 结果: {result}")

    client.flush(collection_name=collection_name)
    client.load_collection(collection_name=collection_name)

    milvus_smoke_test(client, settings, vectors[3])


def milvus_smoke_test(
    client: MilvusClient,
    settings: Settings,
    query_vector: list[float],
) -> None:
    results = client.search(
        collection_name=settings.milvus_collection_name,
        data=[query_vector],
        anns_field=settings.milvus_vector_field,
        limit=3,
        output_fields=[
            settings.milvus_id_field,
            settings.milvus_content_field,
            "source",
            "title",
            "metadata",
        ],
        search_params={"metric_type": "COSINE", "params": {}},
    )

    print("\nMilvus smoke test:")
    print(f"hits_count: {len(results[0])}")

    for hit in results[0]:
        entity = hit["entity"]
        print("-" * 80)
        print(f"id: {entity[settings.milvus_id_field]}")
        print(f"distance: {hit['distance']}")
        print(f"title: {entity['title']}")
        print(f"section_path: {entity['metadata'].get('section_path')}")


async def build_vectors(
    settings: Settings,
    chunks: list[KnowledgeChunk],
) -> list[list[float]]:
    embedding_client = QwenEmbeddingClient(settings)
    vectors = await embedding_client.embed_documents([chunk.content for chunk in chunks])

    if not vectors:
        raise RuntimeError("embedding 结果为空")

    actual_dim = len(vectors[0])
    if actual_dim != settings.embedding_dim:
        raise RuntimeError(
            f"embedding 维度不匹配: actual={actual_dim}, settings={settings.embedding_dim}"
        )

    return vectors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild Milvus collection and ES index with metadata demo chunks.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认删除并重建当前配置中的 Milvus collection 和 ES index。",
    )
    parser.add_argument(
        "--skip-es",
        action="store_true",
        help="跳过 ElasticSearch index 重建。",
    )
    parser.add_argument(
        "--skip-milvus",
        action="store_true",
        help="跳过 Milvus collection 重建。",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    chunks = build_demo_chunks()

    if not args.yes:
        print("这个脚本会删除并重建当前配置中的 ES index 和 Milvus collection。")
        print("确认执行请加参数: --yes")
        return 1

    print(f"准备写入 chunk 数量: {len(chunks)}")
    print(f"ES URL: {settings.elasticsearch_url}")
    print(f"ES index: {settings.elasticsearch_index_name}")
    print(f"Milvus URI: {build_milvus_uri(settings)}")
    print(f"Milvus collection: {settings.milvus_collection_name}")
    print(f"Embedding model: {settings.embedding_model_name}")
    print(f"Embedding dim: {settings.embedding_dim}")

    vectors: list[list[float]] = []
    if not args.skip_milvus:
        vectors = await build_vectors(settings, chunks)

    if not args.skip_es:
        await recreate_es_index(settings, chunks)

    if not args.skip_milvus:
        recreate_milvus_collection(settings, chunks, vectors)

    print("\n重建完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
