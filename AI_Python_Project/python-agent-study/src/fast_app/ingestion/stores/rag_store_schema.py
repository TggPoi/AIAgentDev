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
MILVUS_PHYSICAL_RECORD_ID_FIELD = "physical_record_id"
MILVUS_LOGICAL_RECORD_ID_FIELD = "logical_record_id"
MILVUS_RECORD_TYPE_FIELD = "record_type"
MILVUS_LOGICAL_PARENT_ID_FIELD = "logical_parent_id"
MILVUS_PHYSICAL_PARENT_ID_FIELD = "physical_parent_id"
MILVUS_SOURCE_ID_FIELD = "source_id"
MILVUS_SOURCE_REVISION_FIELD = "source_revision"
MILVUS_VALID_FROM_VERSION_FIELD = "valid_from_version"
MILVUS_VALID_TO_VERSION_FIELD = "valid_to_version"
#ES mapping字段常量
ES_ID_FIELD = "id"
ES_PHYSICAL_RECORD_ID_FIELD = "physical_record_id"
ES_DOC_ID_FIELD = "doc_id"
ES_CONTENT_FIELD = "content"
ES_SEARCH_TEXT_FIELD = "search_text"
ES_RECORD_TYPE_FIELD = "record_type"
ES_LOGICAL_PARENT_ID_FIELD = "logical_parent_id"
ES_PHYSICAL_PARENT_ID_FIELD = "physical_parent_id"
ES_TITLE_FIELD = "title"
ES_SOURCE_FIELD = "source"
ES_METADATA_FIELD = "metadata"
ES_CREATED_AT_FIELD = "created_at"
ES_LOGICAL_RECORD_ID_FIELD = "logical_record_id"
ES_SOURCE_ID_FIELD = "source_id"
ES_SOURCE_REVISION_FIELD = "source_revision"
ES_VALID_FROM_VERSION_FIELD = "valid_from_version"
ES_VALID_TO_VERSION_FIELD = "valid_to_version"

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
            ES_PHYSICAL_RECORD_ID_FIELD: {"type": "keyword"},
            ES_DOC_ID_FIELD: {"type": "keyword"},
            ES_CONTENT_FIELD: build_es_text_field_mapping(),
            ES_SEARCH_TEXT_FIELD: build_es_text_field_mapping(),
            ES_RECORD_TYPE_FIELD: {"type": "keyword"},
            ES_LOGICAL_PARENT_ID_FIELD: {"type": "keyword"},
            ES_PHYSICAL_PARENT_ID_FIELD: {"type": "keyword"},
            ES_TITLE_FIELD: build_es_text_field_mapping(with_keyword=True),
            ES_SOURCE_FIELD: {"type": "keyword"},
            ES_LOGICAL_RECORD_ID_FIELD: {"type": "keyword"},
            ES_SOURCE_ID_FIELD: {"type": "keyword"},
            ES_SOURCE_REVISION_FIELD: {"type": "keyword"},
            ES_VALID_FROM_VERSION_FIELD: {"type": "long"},
            ES_VALID_TO_VERSION_FIELD: {"type": "long"},
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
                    "record_type": {"type": "keyword"},
                    "parent_id": {"type": "keyword"},
                    "section_key": {"type": "keyword"},
                    "parent_index": {"type": "integer"},
                    "child_index": {"type": "integer"},
                    "token_count": {"type": "integer"},
                    "char_count": {"type": "integer"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "chunk_strategy_version": {"type": "keyword"},
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
        field_name=MILVUS_LOGICAL_RECORD_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name=MILVUS_PHYSICAL_RECORD_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name=MILVUS_RECORD_TYPE_FIELD,
        datatype=DataType.VARCHAR,
        max_length=32,
    )
    schema.add_field(
        field_name=MILVUS_LOGICAL_PARENT_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name=MILVUS_PHYSICAL_PARENT_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=128,
    )
    schema.add_field(
        field_name=MILVUS_SOURCE_ID_FIELD,
        datatype=DataType.VARCHAR,
        max_length=64,
    )
    schema.add_field(
        field_name=MILVUS_SOURCE_REVISION_FIELD,
        datatype=DataType.VARCHAR,
        max_length=64,
    )
    schema.add_field(
        field_name=MILVUS_VALID_FROM_VERSION_FIELD,
        datatype=DataType.INT64,
    )
    schema.add_field(
        field_name=MILVUS_VALID_TO_VERSION_FIELD,
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
        MILVUS_PHYSICAL_RECORD_ID_FIELD,
        MILVUS_LOGICAL_RECORD_ID_FIELD,
        MILVUS_RECORD_TYPE_FIELD,
        MILVUS_LOGICAL_PARENT_ID_FIELD,
        MILVUS_PHYSICAL_PARENT_ID_FIELD,
        MILVUS_SOURCE_ID_FIELD,
        MILVUS_SOURCE_REVISION_FIELD,
        MILVUS_VALID_FROM_VERSION_FIELD,
        MILVUS_VALID_TO_VERSION_FIELD,
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
