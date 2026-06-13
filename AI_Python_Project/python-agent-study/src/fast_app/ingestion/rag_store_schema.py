from typing import Any
from pymilvus import DataType, MilvusClient

from fast_app.core.config import Settings


# 负责放 ES mapping 和 Milvus schema helper
MILVUS_SOURCE_FIELD = "source"
MILVUS_TITLE_FIELD = "title"
MILVUS_METADATA_FIELD = "metadata"
MILVUS_DOC_ID_FIELD = "doc_id"
MILVUS_SOURCE_PATH_FIELD = "source_path"
MILVUS_DOCUMENT_TYPE_FIELD = "document_type"
MILVUS_CHUNK_INDEX_FIELD = "chunk_index"


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
                        "doc_id": {"type": "keyword"},
                        "chunk_id": {"type": "keyword"},
                        "title": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "search_analyzer": "ik_smart",
                            "fields": {"keyword": {"type": "keyword"}},
                        },
                        "source_path": {"type": "keyword"},
                        "section_path": {"type": "keyword"},
                        "document_type": {"type": "keyword"},
                        "file_name": {"type": "keyword"},
                        "file_extension": {"type": "keyword"},
                        "heading_level": {"type": "integer"},
                        "section_index": {"type": "integer"},
                        "chunk_index": {"type": "integer"},
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
        field_name=MILVUS_SOURCE_FIELD,
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name=MILVUS_TITLE_FIELD,
        datatype=DataType.VARCHAR,
        max_length=512,
    )
    schema.add_field(
        field_name=MILVUS_DOC_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name=MILVUS_SOURCE_PATH_FIELD,
        datatype=DataType.VARCHAR,
        max_length=1024,
    )
    schema.add_field(
        field_name=MILVUS_DOCUMENT_TYPE_FIELD,
        datatype=DataType.VARCHAR,
        max_length=32,
    )
    schema.add_field(
        field_name=MILVUS_CHUNK_INDEX_FIELD,
        datatype=DataType.INT64,
    )
    schema.add_field(
        field_name=MILVUS_METADATA_FIELD,
        datatype=DataType.JSON,
    )
    return schema


def build_milvus_output_fields(settings: Settings) -> list[str]:
    return [
        settings.milvus_id_field,
        settings.milvus_content_field,
        MILVUS_SOURCE_FIELD,
        MILVUS_TITLE_FIELD,
        MILVUS_DOC_ID_FIELD,
        MILVUS_SOURCE_PATH_FIELD,
        MILVUS_DOCUMENT_TYPE_FIELD,
        MILVUS_CHUNK_INDEX_FIELD,
        MILVUS_METADATA_FIELD,
    ]

# 构建Index索引
def build_milvus_index_params(settings: Settings):
    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=settings.milvus_vector_field,
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )
    return index_params
