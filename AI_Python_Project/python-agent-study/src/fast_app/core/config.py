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

    # 基础认证配置。默认关闭，保留本地学习和 mock 验证体验。
    # 开启后，RAG Chat 主接口需要 X-API-Key 或 Authorization: Bearer token。
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    auth_api_keys: str = Field(default="", alias="AUTH_API_KEYS")
    auth_bearer_tokens: str = Field(default="", alias="AUTH_BEARER_TOKENS")
    auth_allow_demo_user_header: bool = Field(
        default=False,
        alias="AUTH_ALLOW_DEMO_USER_HEADER",
    )
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field(default="python-agent-study", alias="JWT_ISSUER")
    jwt_audience: str = Field(default="python-agent-study-api", alias="JWT_AUDIENCE")
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        ge=1,
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    )
    jwt_refresh_token_expire_days: int = Field(
        default=14,
        ge=1,
        alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS",
    )
    api_key_pepper: str = Field(default="", alias="API_KEY_PEPPER")
    # HTTP 请求体大小上限。用于在进入 Pydantic / RAG Pipeline 前拒绝超大 body。
    max_request_body_bytes: int = Field(
        default=64 * 1024,
        ge=1024,
        alias="MAX_REQUEST_BODY_BYTES",
    )
    # Prompt Injection 分层防护配置。当前先落地规则检测和上下文隔离。
    prompt_guard_enabled: bool = Field(
        default=True,
        alias="PROMPT_GUARD_ENABLED",
    )
    prompt_guard_mode: str = Field(
        default="rule",
        alias="PROMPT_GUARD_MODE",
    )
    prompt_guard_block_threshold: str = Field(
        default="high",
        alias="PROMPT_GUARD_BLOCK_THRESHOLD",
    )
    prompt_guard_llm_model_name: str = Field(
        default="",
        alias="PROMPT_GUARD_LLM_MODEL_NAME",
    )
    prompt_guard_llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        alias="PROMPT_GUARD_LLM_TEMPERATURE",
    )
    # 部分模型支持 provider 级 structured output；Qwen 3.5 起需要关闭此项，
    # 继续使用普通 JSON prompt + Pydantic 校验兜底。
    prompt_guard_structured_output_enabled: bool = Field(
        default=False,
        alias="PROMPT_GUARD_STRUCTURED_OUTPUT_ENABLED",
    )
    prompt_guard_structured_output_method: str = Field(
        default="function_calling",
        alias="PROMPT_GUARD_STRUCTURED_OUTPUT_METHOD",
    )
    prompt_guard_stream_output_mode: str = Field(
        default="sentence_buffer",
        alias="PROMPT_GUARD_STREAM_OUTPUT_MODE",
    )
    prompt_guard_stream_chunk_max_chars: int = Field(
        default=300,
        ge=80,
        le=2000,
        alias="PROMPT_GUARD_STREAM_CHUNK_MAX_CHARS",
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
    # Agent 文档管理工具默认关闭，并且默认只允许 dry-run。
    # 真实写入需要后续 15-7 的工具权限网关和人工确认接入后再放开。
    agent_document_tools_enabled: bool = Field(
        default=False,
        alias="AGENT_DOCUMENT_TOOLS_ENABLED",
    )
    agent_document_tools_dry_run_only: bool = Field(
        default=True,
        alias="AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY",
    )
    agent_document_tools_allowed_extensions: str = Field(
        default=".md,.txt",
        alias="AGENT_DOCUMENT_TOOLS_ALLOWED_EXTENSIONS",
    )
    agent_document_tools_allow_permission_file_edit: bool = Field(
        default=False,
        alias="AGENT_DOCUMENT_TOOLS_ALLOW_PERMISSION_FILE_EDIT",
    )
    agent_document_tools_max_content_chars: int = Field(
        default=200_000,
        ge=1,
        alias="AGENT_DOCUMENT_TOOLS_MAX_CONTENT_CHARS",
    )
    agent_document_tools_require_confirmation: bool = Field(
        default=True,
        alias="AGENT_DOCUMENT_TOOLS_REQUIRE_CONFIRMATION",
    )
    agent_tool_approval_dir: str = Field(
        default="runtime/agent-tool-approvals",
        alias="AGENT_TOOL_APPROVAL_DIR",
    )
    agent_tool_approval_expire_minutes: int = Field(
        default=60,
        ge=1,
        alias="AGENT_TOOL_APPROVAL_EXPIRE_MINUTES",
    )
    agent_task_plan_dir: str = Field(
        default="runtime/agent-task-plans",
        alias="AGENT_TASK_PLAN_DIR",
    )
    agent_tool_execution_policy: str = Field(
        default="approval_required",
        alias="AGENT_TOOL_EXECUTION_POLICY",
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

    @field_validator("prompt_guard_mode", mode="before")
    @classmethod
    def normalize_prompt_guard_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"rule", "llm", "hybrid"}:
            raise ValueError("PROMPT_GUARD_MODE 只支持 rule、llm 或 hybrid")

        return normalized

    @field_validator("prompt_guard_block_threshold", mode="before")
    @classmethod
    def normalize_prompt_guard_block_threshold(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"low", "medium", "high", "critical"}:
            raise ValueError(
                "PROMPT_GUARD_BLOCK_THRESHOLD 只支持 low、medium、high 或 critical"
            )

        return normalized

    @field_validator("prompt_guard_stream_output_mode", mode="before")
    @classmethod
    def normalize_prompt_guard_stream_output_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"pre_guard_only", "buffer_then_emit", "sentence_buffer"}:
            raise ValueError(
                "PROMPT_GUARD_STREAM_OUTPUT_MODE 只支持 pre_guard_only、"
                "buffer_then_emit 或 sentence_buffer"
            )

        return normalized

    @field_validator("prompt_guard_structured_output_method", mode="before")
    @classmethod
    def normalize_prompt_guard_structured_output_method(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"function_calling", "json_mode", "json_schema"}:
            raise ValueError(
                "PROMPT_GUARD_STRUCTURED_OUTPUT_METHOD 只支持 "
                "function_calling、json_mode 或 json_schema"
            )

        return normalized

    @field_validator("agent_document_tools_allowed_extensions", mode="before")
    @classmethod
    def normalize_agent_document_tools_allowed_extensions(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        extensions = []
        for item in value.split(","):
            extension = item.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            extensions.append(extension)

        if not extensions:
            raise ValueError("AGENT_DOCUMENT_TOOLS_ALLOWED_EXTENSIONS 不能为空")

        return ",".join(sorted(set(extensions)))

    @field_validator("agent_tool_execution_policy", mode="before")
    @classmethod
    def normalize_agent_tool_execution_policy(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"approval_required", "risk_based", "dry_run_only"}:
            raise ValueError(
                "AGENT_TOOL_EXECUTION_POLICY 只支持 approval_required / risk_based / dry_run_only"
            )

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

    @property
    def auth_api_key_list(self) -> list[str]:
        return _split_csv_secret_values(self.auth_api_keys)

    @property
    def auth_bearer_token_list(self) -> list[str]:
        return _split_csv_secret_values(self.auth_bearer_tokens)

    @property
    def agent_document_tools_allowed_extension_list(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.agent_document_tools_allowed_extensions.split(",")
            if item.strip()
        ]
    


def _split_csv_secret_values(raw_value: str) -> list[str]:
    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


# @lru_cache 第一次调用 get_settings() 时创建 Settings。后续再次调用，直接返回第一次创建好的对象。
# Settings 在应用运行期间通常是稳定的。没有必要每个请求都重新读取 .env。
@lru_cache
def get_settings() -> Settings:
    return Settings()
