from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# BaseSettings 读取环境变量
# 读取 .env 文件
# 把字符串配置转换成 Python 类型
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Python Agent Study", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")

    rag_default_top_k: int = Field(default=5, alias="RAG_DEFAULT_TOP_K")
    rag_default_min_score: float = Field(default=0.0, alias="RAG_DEFAULT_MIN_SCORE")
    rag_use_mock: bool = Field(default=True, alias="RAG_USE_MOCK")

    milvus_host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")

    # 配置milvus collection和字段信息，方便后续使用
    milvus_collection_name: str = Field(
        default="python_agent_demo_chunks",
        alias="MILVUS_COLLECTION_NAME",
    )
    milvus_vector_field: str = Field(default="embedding", alias="MILVUS_VECTOR_FIELD")
    milvus_id_field: str = Field(default="id", alias="MILVUS_ID_FIELD")
    milvus_content_field: str = Field(default="content", alias="MILVUS_CONTENT_FIELD")


    # 配置elasticsearch相关参数
    elasticsearch_url: str = Field(
    default="http://127.0.0.1:9200",
    alias="ELASTICSEARCH_URL",
    )
    elasticsearch_index_name: str = Field(
        default="python_agent_demo_chunks",
        alias="ELASTICSEARCH_INDEX_NAME",
    )
    elasticsearch_username: str = Field(default="", alias="ELASTICSEARCH_USERNAME")
    elasticsearch_password: str = Field(default="", alias="ELASTICSEARCH_PASSWORD")


    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ALLOW_ORIGINS",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    openai_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="OPENAI_BASE_URL",
    )
    
    llm_model_name: str = Field(default="qwen-plus", alias="LLM_MODEL_NAME")
    llm_provider: str = Field(default="mock", alias="LLM_PROVIDER")

    rag_pipeline_provider: str = Field(default="classic", alias="RAG_PIPELINE_PROVIDER")

    #嵌入模型配置
    embedding_provider: str = Field(default="qwen", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(
        default="text-embedding-v4",
        alias="EMBEDDING_MODEL_NAME",
    )
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")

    # rerank模型配置
    reranker_provider: str = Field(default="none", alias="RERANKER_PROVIDER")
    rerank_model_name: str = Field(default="qwen3-rerank", alias="RERANK_MODEL_NAME")
    rerank_top_k: int = Field(default=5, alias="RERANK_TOP_K")

    # 检索提供者配置，支持mock（使用mock数据进行测试）或者实际的检索服务提供者（如milvus、elasticsearch等）
    vector_retriever_provider: str = Field(
        default="mock",
        alias="VECTOR_RETRIEVER_PROVIDER",
    )
    keyword_retriever_provider: str = Field(
        default="mock",
        alias="KEYWORD_RETRIEVER_PROVIDER",
    )

    # 容错，超时相关配置 start
    external_call_max_retries: int = Field(default=2, alias="EXTERNAL_CALL_MAX_RETRIES")
    external_call_retry_base_delay: float = Field(
        default=0.2,
        alias="EXTERNAL_CALL_RETRY_BASE_DELAY",
    )

    rerank_timeout_seconds: float = Field(default=10.0, alias="RERANK_TIMEOUT_SECONDS")
    elasticsearch_request_timeout: float = Field(
        default=10.0,
        alias="ELASTICSEARCH_REQUEST_TIMEOUT",
    )
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    embedding_timeout_seconds: float = Field(default=30.0, alias="EMBEDDING_TIMEOUT_SECONDS")
    # 容错，超时相关配置 end


    # ingestion 的基础配置 start
    # 本地 Markdown 知识库目录
    knowledge_base_dir: str = Field(
        default="knowledge-base",
        alias="KNOWLEDGE_BASE_DIR",
    )
    # 写入 KnowledgeChunk.source 的来源标识
    ingestion_source_name: str = Field(
        default="local_markdown",
        alias="INGESTION_SOURCE_NAME",
    )
    # ingestion 写入模式：recreate 删除重建，upsert 按 chunk_id 覆盖或新增，replace_docs 按 doc_id 先删旧 chunks 再写入
    ingestion_write_mode: str = Field(
        default="recreate",
        alias="INGESTION_WRITE_MODE",
    )
    # 单个 chunk 的最大字符数
    markdown_chunk_max_chars: int = Field(
        default=1200,
        alias="MARKDOWN_CHUNK_MAX_CHARS",
    )
    # 相邻 chunk 之间保留多少重叠字符
    markdown_chunk_overlap_chars: int = Field(
        default=120,
        alias="MARKDOWN_CHUNK_OVERLAP_CHARS",
    )
    # 单个 chunk 估算最大 token 数
    markdown_chunk_max_tokens: int = Field(
        default=500,
        alias="MARKDOWN_CHUNK_MAX_TOKENS",
    )
    # 太短的 chunk 不单独写入
    markdown_chunk_min_chars: int = Field(
        default=20,
        alias="MARKDOWN_CHUNK_MIN_CHARS",
    )
    # ingestion 的基础配置 end


    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]
    


# @lru_cache 第一次调用 get_settings() 时创建 Settings。后续再次调用，直接返回第一次创建好的对象。
# Settings 在应用运行期间通常是稳定的。没有必要每个请求都重新读取 .env。
@lru_cache
def get_settings() -> Settings:
    return Settings()
