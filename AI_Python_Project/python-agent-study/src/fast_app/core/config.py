from functools import lru_cache

from pydantic import Field, field_validator
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

    # 开发使用的debug接口配置
    debug: bool = Field(default=True, alias="DEBUG")
    debug_trace_enabled: bool = Field(default=False, alias="DEBUG_TRACE_ENABLED")
    debug_trace_token: str = Field(default="", alias="DEBUG_TRACE_TOKEN")
    debug_trace_max_sources: int = Field(default=5, alias="DEBUG_TRACE_MAX_SOURCES")
    slow_http_request_threshold_ms: float = Field(
        default=3000.0,
        alias="SLOW_HTTP_REQUEST_THRESHOLD_MS",
    )
    slow_rag_pipeline_threshold_ms: float = Field(
        default=5000.0,
        alias="SLOW_RAG_PIPELINE_THRESHOLD_MS",
    )
    slow_retrieval_threshold_ms: float = Field(
        default=2000.0,
        alias="SLOW_RETRIEVAL_THRESHOLD_MS",
    )
    slow_rerank_threshold_ms: float = Field(
        default=2000.0,
        alias="SLOW_RERANK_THRESHOLD_MS",
    )
    slow_llm_threshold_ms: float = Field(
        default=5000.0,
        alias="SLOW_LLM_THRESHOLD_MS",
    )

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

    # LangSmith tracing 配置。默认关闭，避免本地开发或测试时意外向远端写入 trace。
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        alias="LANGSMITH_ENDPOINT",
    )
    langsmith_project: str = Field(
        default="python-agent-study",
        alias="LANGSMITH_PROJECT",
    )
    langsmith_tags: str = Field(default="", alias="LANGSMITH_TAGS")

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

    # Agent Loop 循环次数配置
    agent_max_steps: int = Field(default=6, ge=1, le=50, alias="AGENT_MAX_STEPS")
    agent_max_tool_calls: int = Field(
        default=4,
        ge=0,
        le=50,
        alias="AGENT_MAX_TOOL_CALLS",
    )

    # 多轮对话短期记忆配置。默认仍使用内存实现，避免本地开发强依赖 Redis。
    memory_store_provider: str = Field(
        default="in_memory",
        alias="MEMORY_STORE_PROVIDER",
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        alias="REDIS_URL",
    )
    memory_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        alias="MEMORY_TTL_SECONDS",
    )
    memory_max_messages: int = Field(
        default=20,
        ge=1,
        le=200,
        alias="MEMORY_MAX_MESSAGES",
    )
    # 历史窗口配置：控制后续多轮逻辑最多参考最近几轮对话。
    # 它和 MEMORY_MAX_MESSAGES 不同，后者是 Redis list 的存储上限。
    memory_history_max_turns: int = Field(
        default=3,
        ge=0,
        le=20,
        alias="MEMORY_HISTORY_MAX_TURNS",
    )
    query_rewrite_enabled: bool = Field(
        default=True,
        alias="QUERY_REWRITE_ENABLED",
    )
    query_rewrite_model_name: str = Field(
        default="",
        alias="QUERY_REWRITE_MODEL_NAME",
    )
    query_rewrite_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        alias="QUERY_REWRITE_TEMPERATURE",
    )
    # Summary memory 是窗口外旧消息的摘要派生视图，默认关闭，避免影响已跑通的多轮主链路。
    summary_memory_enabled: bool = Field(
        default=False,
        alias="SUMMARY_MEMORY_ENABLED",
    )
    summary_memory_trigger_messages: int = Field(
        default=12,
        ge=4,
        alias="SUMMARY_MEMORY_TRIGGER_MESSAGES",
    )
    summary_memory_model_name: str = Field(
        default="",
        alias="SUMMARY_MEMORY_MODEL_NAME",
    )
    summary_memory_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        alias="SUMMARY_MEMORY_TEMPERATURE",
    )

    # PostgreSQL 持久化配置。这里默认只创建异步 Engine，不会在应用启动时立刻发起连接。
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/python_agent_study",
        alias="DATABASE_URL",
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")
    database_pool_size: int = Field(
        default=5,
        ge=1,
        alias="DATABASE_POOL_SIZE",
    )
    database_max_overflow: int = Field(
        default=10,
        ge=0,
        alias="DATABASE_MAX_OVERFLOW",
    )

    # 博查 网络搜索api
    bocha_api_key: str = Field(default="", alias="BOCHA_API_KEY")
    bocha_web_search_url: str = Field(
        default="https://api.bochaai.com/v1/web-search",
        alias="BOCHA_WEB_SEARCH_URL",
    )
    bocha_web_search_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        alias="BOCHA_WEB_SEARCH_TIMEOUT_SECONDS",
    )

    # 计算工具配置：可选 CALCULATOR_MODE-简单四则运算  CALCULATOR_MAX_EXPRESSION_LENGTH-解析表达式
    calculator_mode: str = Field(
        default="safe_expression",
        alias="CALCULATOR_MODE",
    )
    calculator_max_expression_length: int = Field(
        default=120,
        ge=1,
        le=1000,
        alias="CALCULATOR_MAX_EXPRESSION_LENGTH",
    )
    calculator_max_abs_value: float = Field(
        default=1_000_000_000,
        gt=0,
        alias="CALCULATOR_MAX_ABS_VALUE",
    )

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

    @field_validator("calculator_mode", mode="before")
    @classmethod
    def normalize_calculator_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"basic_ops", "safe_expression"}:
            raise ValueError("CALCULATOR_MODE 只支持 basic_ops 或 safe_expression")

        return normalized

    @field_validator("memory_store_provider", mode="before")
    @classmethod
    def normalize_memory_store_provider(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"in_memory", "redis"}:
            raise ValueError("MEMORY_STORE_PROVIDER 只支持 in_memory 或 redis")

        return normalized


    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_mode(cls, value: object) -> object:
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {
                "true",
                "1",
                "yes",
                "on",
                "debug",
                "dev",
                "development",
            }:
                return True

            if normalized in {
                "false",
                "0",
                "no",
                "off",
                "release",
                "prod",
                "production",
            }:
                return False

        return value

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

    @property
    def langsmith_tag_list(self) -> list[str]:
        return [
            tag.strip()
            for tag in self.langsmith_tags.split(",")
            if tag.strip()
        ]
    


# @lru_cache 第一次调用 get_settings() 时创建 Settings。后续再次调用，直接返回第一次创建好的对象。
# Settings 在应用运行期间通常是稳定的。没有必要每个请求都重新读取 .env。
@lru_cache
def get_settings() -> Settings:
    return Settings()
