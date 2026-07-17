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
#ES mapping字段常量
ES_ID_FIELD = "id"
ES_CONTENT_FIELD = "content"
ES_TITLE_FIELD = "title"
ES_SOURCE_FIELD = "source"
ES_METADATA_FIELD = "metadata"
ES_CREATED_AT_FIELD = "created_at"

ES_IK_INDEX_ANALYZER = "ik_max_word"
ES_IK_SEARCH_ANALYZER = "ik_smart"

ES_METADATA_DOC_ID_FIELD = "metadata.doc_id"
ES_METADATA_CHUNK_ID_FIELD = "metadata.chunk_id"
ES_METADATA_SOURCE_PATH_FIELD = "metadata.source_path"
ES_METADATA_SECTION_PATH_FIELD = "metadata.section_path"
ES_METADATA_DOCUMENT_TYPE_FIELD = "metadata.document_type"
ES_METADATA_VISIBILITY_FIELD = "metadata.visibility"
ES_METADATA_ALLOWED_DEPARTMENTS_FIELD = "metadata.allowed_departments"
ES_METADATA_ALLOWED_USERS_FIELD = "metadata.allowed_users"
ES_METADATA_PERMISSION_SOURCE_FIELD = "metadata.permission_source"


def build_es_text_field_mapping(with_keyword: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "type": "text",
        "analyzer": ES_IK_INDEX_ANALYZER,
        "search_analyzer": ES_IK_SEARCH_ANALYZER,
    }

    if with_keyword:
        mapping["fields"] = {"keyword": {"type": "keyword"}}

    return mapping


def build_es_index_settings() -> dict[str, Any]:
    return {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    }


def build_es_mappings() -> dict[str, Any]:
    return {
        "properties": {
            ES_ID_FIELD: {"type": "keyword"},
            ES_CONTENT_FIELD: build_es_text_field_mapping(),
            ES_TITLE_FIELD: build_es_text_field_mapping(with_keyword=True),
            ES_SOURCE_FIELD: {"type": "keyword"},
            ES_METADATA_FIELD: {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "chunk_id": {"type": "keyword"},
                    "title": build_es_text_field_mapping(with_keyword=True),
                    "source_path": {"type": "keyword"},
                    "section_path": {"type": "keyword"},
                    "document_type": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "allowed_departments": {"type": "keyword"},
                    "allowed_users": {"type": "keyword"},
                    "permission_source": {"type": "keyword"},
                    # Office 增量同步直接读取这些字段比较版本，不依赖全文分析器。
                    "content_hash": {"type": "keyword"},
                    "index_hash": {"type": "keyword"},
                    "identity_key": {"type": "keyword"},
                    "builder_schema_version": {"type": "keyword"},
                    "embedding_fingerprint": {"type": "keyword"},
                    "file_name": {"type": "keyword"},
                    "file_extension": {"type": "keyword"},
                    "heading_level": {"type": "integer"},
                    "section_index": {"type": "integer"},
                    "chunk_index": {"type": "integer"},
                }
            },
            ES_CREATED_AT_FIELD: {"type": "date"},
        }
    }


def build_es_index_body() -> dict[str, Any]:
    return {
        "settings": build_es_index_settings(),
        "mappings": build_es_mappings(),
    }


def build_es_mapping() -> dict[str, Any]:
    return build_es_index_body()


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
