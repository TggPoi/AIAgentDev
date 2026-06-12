from typing import Any
from pymilvus import DataType, MilvusClient

from fast_app.core.config import Settings


# 负责放 ES mapping 和 Milvus schema helper

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

# 构建Collection结构
def build_milvus_schema(settings: Settings):
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
    return schema

# 构建Index索引
def build_milvus_index_params(settings: Settings):
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=settings.milvus_vector_field,
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )
    return index_params