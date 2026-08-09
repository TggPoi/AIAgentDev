import base64
import binascii
from functools import lru_cache
import json
import os
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_EVAL_SNAPSHOT_ENVS = {"dev", "development", "local", "test", "testing"}

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
    # 默认不向远端 trace 上传 query、filters、user_id 等业务敏感数据。
    langsmith_include_sensitive_data: bool = Field(
        default=False,
        alias="LANGSMITH_INCLUDE_SENSITIVE_DATA",
    )

    # Eval snapshot 默认只允许本地开发明文；共享环境必须显式选择脱敏或加密。
    eval_snapshot_security_mode: Literal["plain", "redacted", "encrypted"] = Field(
        default="plain",
        alias="EVAL_SNAPSHOT_SECURITY_MODE",
        description=(
            "评测快照的落盘安全模式：plain 保存完整明文，redacted 只保留哈希和非敏感身份，"
            "encrypted 使用独立 AES-256-GCM key ring 加密敏感值。"
        ),
    )
    eval_snapshot_retention_days: int = Field(
        default=30,
        ge=1,
        alias="EVAL_SNAPSHOT_RETENTION_DAYS",
        description="评测快照计划保留天数；阶段 11-24 的持久化清理任务使用该服务端配置。",
    )
    eval_snapshot_encryption_active_key_id: str = Field(
        default="",
        alias="EVAL_SNAPSHOT_ENCRYPTION_ACTIVE_KEY_ID",
        description="encrypted 模式新快照使用的 key ID；旧快照按自身 key ID 从 key ring 读取。",
    )
    eval_snapshot_encryption_keys_json: str = Field(
        default="{}",
        alias="EVAL_SNAPSHOT_ENCRYPTION_KEYS_JSON",
        repr=False,
        description=(
            "Eval 专用 AES-256-GCM key ring JSON；key 为轮换 ID，value 为 URL-safe base64 的 32 字节密钥。"
        ),
    )

    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ALLOW_ORIGINS",
    )

    # 基础认证配置。默认关闭，保留本地学习和 mock 验证体验。
    # 开启后，RAG Chat 主接口需要 X-API-Key 或 Authorization: Bearer token。
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
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
    max_upload_file_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1024,
        alias="MAX_UPLOAD_FILE_BYTES",
    )
    # multipart 请求还包含边界和普通表单字段，因此路由前上限要略大于文件上限。
    max_upload_request_body_bytes: int = Field(
        default=21 * 1024 * 1024,
        ge=1024,
        alias="MAX_UPLOAD_REQUEST_BODY_BYTES",
    )
    # Prompt Injection 分层防护配置。当前先落地规则检测和上下文隔离。
    prompt_guard_enabled: bool = Field(
        default=True,
        alias="PROMPT_GUARD_ENABLED",
    )
    prompt_guard_retrieved_document_check_enabled: bool = Field(
        default=True,
        alias="PROMPT_GUARD_RETRIEVED_DOCUMENT_CHECK_ENABLED",
        description=(
            "是否检查检索返回的文档正文；关闭后跳过逐 Chunk 的规则和 LLM 分类，"
            "但不影响用户输入与模型输出的 Prompt Guard。"
        ),
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
    rag_prompt_version: str = Field(
        default="rag_prompt.v1",
        min_length=1,
        alias="RAG_PROMPT_VERSION",
        description="当前 RAG 生成 Prompt 的人工维护版本；Prompt 语义改变时必须递增。",
    )

    agent_task_plan_reviewer_model_name: str = Field(
        default="qwen3.7-max",
        alias="AGENT_TASK_PLAN_REVIEWER_MODEL_NAME",
        description="Research TaskPlan Reviewer 使用的模型名称，与 Planner 主模型独立配置。",
    )

    # Agent Router 使用独立连接配置，不能在代码中隐式继承主 LLM 的凭据。
    # 本地开发可以在 .env 中显式填入相同值，生产环境则可单独切换低延迟模型。
    agent_router_api_key: str = Field(default="", alias="AGENT_ROUTER_API_KEY")
    agent_router_base_url: str = Field(default="", alias="AGENT_ROUTER_BASE_URL")
    agent_router_model_name: str = Field(default="", alias="AGENT_ROUTER_MODEL_NAME")
    agent_router_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        alias="AGENT_ROUTER_TEMPERATURE",
    )
    agent_router_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        alias="AGENT_ROUTER_TIMEOUT_SECONDS",
    )
    agent_router_max_retries: int = Field(
        default=0,
        ge=0,
        le=10,
        alias="AGENT_ROUTER_MAX_RETRIES",
    )
    agent_router_confidence_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        alias="AGENT_ROUTER_CONFIDENCE_THRESHOLD",
    )
    agent_router_structured_output_method: str = Field(
        default="function_calling",
        alias="AGENT_ROUTER_STRUCTURED_OUTPUT_METHOD",
    )

    rag_pipeline_provider: str = Field(default="classic", alias="RAG_PIPELINE_PROVIDER")

    # Agent Loop 循环次数配置
    agent_max_steps: int = Field(default=6, ge=1, le=50, alias="AGENT_MAX_STEPS")
    agent_max_tool_calls: int = Field(
        default=12,
        ge=0,
        le=50,
        alias="AGENT_MAX_TOOL_CALLS",
    )
    agent_max_parallel_tool_calls: int = Field(
        default=4,
        ge=1,
        le=20,
        alias="AGENT_MAX_PARALLEL_TOOL_CALLS",
    )
    agent_research_max_sub_questions: int = Field(
        default=8, ge=1, le=8, alias="AGENT_RESEARCH_MAX_SUB_QUESTIONS"
    )
    agent_research_max_parallel_workers: int = Field(
        default=4, ge=1, le=4, alias="AGENT_RESEARCH_MAX_PARALLEL_WORKERS"
    )
    agent_research_max_tool_calls_per_worker: int = Field(
        default=4, ge=0, le=4, alias="AGENT_RESEARCH_MAX_TOOL_CALLS_PER_WORKER"
    )
    agent_research_max_correction_rounds: int = Field(
        default=2, ge=0, le=2, alias="AGENT_RESEARCH_MAX_CORRECTION_ROUNDS"
    )
    agent_research_worker_timeout_seconds: float = Field(
        default=120.0, gt=0.0, alias="AGENT_RESEARCH_WORKER_TIMEOUT_SECONDS"
    )
    # Agent 文档管理工具默认关闭，并且默认只允许 dry-run。
    # 真实写入需要通过 TaskPlan 确认接口重新校验权限后再放开。
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
    agent_document_max_deliverables: int = Field(
        default=6,
        ge=1,
        le=12,
        alias="AGENT_DOCUMENT_MAX_DELIVERABLES",
    )
    agent_document_max_revision_rounds: int = Field(
        default=2,
        ge=0,
        le=4,
        alias="AGENT_DOCUMENT_MAX_REVISION_ROUNDS",
    )
    agent_document_worker_timeout_seconds: float = Field(
        default=480.0,
        gt=0.0,
        alias="AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS",
        description=(
            "一次复杂文档 Deep Agent 工作流的总墙钟超时秒数；局部模型步骤和工具"
            "调用仍由各自预算限制；默认值覆盖长文初稿、一次 Writer 返工和复审。"
        ),
    )
    agent_document_researcher_timeout_seconds: float = Field(
        default=120.0,
        gt=0.0,
        alias="AGENT_DOCUMENT_RESEARCHER_TIMEOUT_SECONDS",
        description=(
            "Document Researcher 单次长上下文模型调用的超时秒数；独立于普通"
            " LLM_TIMEOUT_SECONDS，覆盖检索结果和获准全文的综合处理。"
        ),
    )
    agent_document_researcher_max_retries: int = Field(
        default=0,
        ge=0,
        le=2,
        alias="AGENT_DOCUMENT_RESEARCHER_MAX_RETRIES",
        description=(
            "Document Researcher 单次模型调用的 SDK 自动重试次数；默认不重试，"
            "避免用相同长上下文重复占用整个文档 Worker 的墙钟预算。"
        ),
    )
    agent_document_coordinator_timeout_seconds: float = Field(
        default=120.0,
        gt=0.0,
        alias="AGENT_DOCUMENT_COORDINATOR_TIMEOUT_SECONDS",
        description=(
            "Document Coordinator 和 Reviewer 单次长上下文流式模型调用的超时秒数；"
            "覆盖编排决策和完整草稿审查，不改变整体 Worker 超时。"
        ),
    )
    agent_document_subagent_max_steps: int = Field(
        default=10,
        ge=3,
        le=20,
        alias="AGENT_DOCUMENT_SUBAGENT_MAX_STEPS",
        description=(
            "每个文档 Writer 或 Reviewer 在一次运行中允许的模型调用步数；包含"
            " Deep Agents 虚拟文件读写、修订后复核和最终结构化返回。"
        ),
    )
    agent_document_researcher_max_steps: int = Field(
        default=12,
        ge=3,
        le=20,
        alias="AGENT_DOCUMENT_RESEARCHER_MAX_STEPS",
        description=(
            "Document Researcher 一次运行允许的模型调用步数；为检索、全文读取、"
            "研究文件写入和最终结构化返回保留独立预算，不扩大 Writer/Reviewer。"
        ),
    )
    agent_document_max_total_model_calls: int = Field(
        default=36,
        ge=4,
        le=200,
        alias="AGENT_DOCUMENT_MAX_TOTAL_MODEL_CALLS",
        description=(
            "一次 Deep Document Agent 执行中 Coordinator 与全部 SubAgent 共享的模型"
            "调用总上限；恢复请求重新计数，但已写入 checkpoint 的角色派发限制继续生效。"
        ),
    )
    agent_document_max_total_draft_chars: int = Field(
        default=400_000,
        ge=1,
        alias="AGENT_DOCUMENT_MAX_TOTAL_DRAFT_CHARS",
    )
    langgraph_aes_key_base64: str = Field(
        default="",
        alias="LANGGRAPH_AES_KEY_BASE64",
        repr=False,
        description="Deep Agent LangGraph checkpoint 的 Base64 编码 AES-256 密钥。",
    )
    agent_document_checkpoint_retention_days: int = Field(
        default=7,
        ge=1,
        alias="AGENT_DOCUMENT_CHECKPOINT_RETENTION_DAYS",
        description="运行中或失败的 Deep Agent checkpoint 最长保留天数。",
    )
    agent_task_plan_dir: str = Field(
        default="runtime/agent-task-plans",
        alias="AGENT_TASK_PLAN_DIR",
    )
    agent_tool_execution_policy: str = Field(
        default="confirmation_required",
        alias="AGENT_TOOL_EXECUTION_POLICY",
    )
    # MCP调用的相关配置
    agent_task_mcp_enabled: bool = Field(
        default=False,
        alias="AGENT_TASK_MCP_ENABLED",
    )
    agent_task_mcp_stdio_servers_json: str = Field(
        default="[]",
        alias="AGENT_TASK_MCP_STDIO_SERVERS_JSON",
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

    # 自由 NL2SQL 默认关闭；业务库连接只允许通过独立 database key 查找。
    nl2sql_enabled: bool = Field(default=False, alias="NL2SQL_ENABLED")
    nl2sql_database_urls_json: str = Field(
        default="{}",
        alias="NL2SQL_DATABASE_URLS_JSON",
        repr=False,
        description="NL2SQL database_key 到 PostgreSQL 只读连接 URL 的 JSON 映射；不得传给模型或 API。",
    )
    nl2sql_model_name: str = Field(
        default="",
        alias="NL2SQL_MODEL_NAME",
        description="NL2SQL SQL 生成模型；为空时使用 LLM_MODEL_NAME。",
    )
    nl2sql_model_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        alias="NL2SQL_MODEL_TEMPERATURE",
    )
    nl2sql_model_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        alias="NL2SQL_MODEL_TIMEOUT_SECONDS",
    )
    nl2sql_default_max_rows: int = Field(
        default=200,
        ge=1,
        le=500,
        alias="NL2SQL_DEFAULT_MAX_ROWS",
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
    markdown_parent_target_tokens: int = Field(
        default=900,
        ge=1,
        alias="MARKDOWN_PARENT_TARGET_TOKENS",
        description="Markdown 有界父块的目标 token 数；达到后优先在完整 block 边界结束父块。",
    )
    markdown_parent_max_tokens: int = Field(
        default=1200,
        ge=1,
        alias="MARKDOWN_PARENT_MAX_TOKENS",
        description="Markdown 父块允许的最大预算 token 数。",
    )
    markdown_parent_max_chars: int = Field(
        default=6000,
        ge=1,
        alias="MARKDOWN_PARENT_MAX_CHARS",
        description="Markdown 父块字符硬上限，用于兜底本地 tokenizer 与模型 tokenizer 的差异。",
    )
    gitlab_integration_enabled: bool = Field(
        default=False,
        alias="GITLAB_INTEGRATION_ENABLED",
        description="是否启用 GitLab 企业文档数据源、Webhook 和后台同步能力。",
    )
    gitlab_request_timeout_seconds: float = Field(
        default=20.0,
        gt=0.0,
        alias="GITLAB_REQUEST_TIMEOUT_SECONDS",
        description="GitLab HTTP API 单次请求超时秒数。",
    )
    gitlab_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        alias="GITLAB_MAX_RETRIES",
        description="GitLab 网络错误、429 和 5xx 的最大自动重试次数。",
    )
    gitlab_archive_max_bytes: int = Field(
        default=200 * 1024 * 1024,
        ge=1024,
        alias="GITLAB_ARCHIVE_MAX_BYTES",
        description="单个 GitLab Archive 允许下载和解压的最大字节数。",
    )
    gitlab_archive_max_files: int = Field(
        default=10_000,
        ge=1,
        alias="GITLAB_ARCHIVE_MAX_FILES",
        description="一次 GitLab Archive 全量同步允许包含的最大文件数量。",
    )
    gitlab_source_file_max_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1024,
        alias="GITLAB_SOURCE_FILE_MAX_BYTES",
        description="GitLab 仓库中单个可导入文档允许的最大字节数。",
    )
    gitlab_worker_poll_seconds: float = Field(
        default=2.0,
        gt=0.0,
        alias="GITLAB_WORKER_POLL_SECONDS",
        description="GitLab 独立 Worker 在队列为空时的轮询间隔。",
    )
    gitlab_worker_lease_seconds: int = Field(
        default=300,
        ge=30,
        alias="GITLAB_WORKER_LEASE_SECONDS",
        description="GitLab 同步任务租约持续秒数。",
    )
    gitlab_worker_heartbeat_seconds: int = Field(
        default=60,
        ge=5,
        alias="GITLAB_WORKER_HEARTBEAT_SECONDS",
        description="GitLab 同步 Worker 续租心跳间隔秒数。",
    )
    gitlab_reconcile_interval_seconds: int = Field(
        default=600,
        ge=60,
        alias="GITLAB_RECONCILE_INTERVAL_SECONDS",
        description="GitLab 周期性对账的默认间隔秒数。",
    )
    gitlab_agent_changes_enabled: bool = Field(
        default=False,
        alias="GITLAB_AGENT_CHANGES_ENABLED",
        description="是否将确认后的 Agent 文档写操作转换为 GitLab 分支和 Merge Request。",
    )
    markdown_child_target_tokens: int = Field(
        default=260,
        ge=1,
        alias="MARKDOWN_CHILD_TARGET_TOKENS",
        description="Markdown 检索子块的目标 token 数。",
    )
    markdown_child_max_tokens: int = Field(
        default=350,
        ge=1,
        alias="MARKDOWN_CHILD_MAX_TOKENS",
        description="Markdown 检索子块允许的最大 token 数。",
    )
    markdown_child_min_tokens: int = Field(
        default=80,
        ge=1,
        alias="MARKDOWN_CHILD_MIN_TOKENS",
        description="Markdown 子块期望的最小 token 数；短 section 不会因此被丢弃。",
    )
    markdown_child_overlap_tokens: int = Field(
        default=50,
        ge=0,
        alias="MARKDOWN_CHILD_OVERLAP_TOKENS",
        description="相邻 Markdown 子块最多复用的完整 block token 数。",
    )
    rag_parent_context_max_tokens: int = Field(
        default=3000,
        ge=1,
        alias="RAG_PARENT_CONTEXT_MAX_TOKENS",
        description="父块扩展后允许送入 RAG 上下文的检索资料总 token 预算。",
    )
    rag_parent_context_max_parents: int = Field(
        default=3,
        ge=1,
        alias="RAG_PARENT_CONTEXT_MAX_PARENTS",
        description="单次 RAG 请求最多采用的 Markdown 父块数量。",
    )
    rag_parent_expansion_enabled: bool = Field(
        default=False,
        alias="RAG_PARENT_EXPANSION_ENABLED",
        description="是否把 rerank 后的 Markdown 子块安全扩展为有界父块；重建 v2 索引后再开启。",
    )
    # ingestion 的基础配置 end

    @model_validator(mode="after")
    def validate_upload_size_limits(self) -> "Settings":
        """确保 multipart 请求上限为文件内容之外的边界和表单字段预留空间。"""

        if self.max_upload_request_body_bytes <= self.max_upload_file_bytes:
            raise ValueError(
                "MAX_UPLOAD_REQUEST_BODY_BYTES 必须大于 MAX_UPLOAD_FILE_BYTES"
            )
        return self

    @model_validator(mode="after")
    def validate_markdown_parent_child_limits(self) -> "Settings":
        """校验 Markdown 父子预算关系，避免运行时产生越界或无法前进的窗口。"""

        if not (
            self.markdown_child_min_tokens
            <= self.markdown_child_target_tokens
            <= self.markdown_child_max_tokens
            < self.markdown_parent_max_tokens
        ):
            raise ValueError(
                "Markdown token 配置必须满足 "
                "child_min <= child_target <= child_max < parent_max"
            )
        if self.markdown_child_overlap_tokens >= self.markdown_child_target_tokens:
            raise ValueError("MARKDOWN_CHILD_OVERLAP_TOKENS 必须小于 child target")
        if self.markdown_parent_target_tokens > self.markdown_parent_max_tokens:
            raise ValueError("MARKDOWN_PARENT_TARGET_TOKENS 不能大于 parent max")
        if self.rag_parent_context_max_tokens < self.markdown_parent_max_tokens:
            raise ValueError("父块上下文总预算至少要容纳一个最大父块")
        return self

    @model_validator(mode="after")
    def validate_eval_snapshot_settings(self) -> "Settings":
        """在启动配置加载时拒绝不安全或不可解密的 Eval snapshot 配置。"""

        environment = self.app_env.strip().lower()
        if not self.rag_prompt_version.strip():
            raise ValueError("RAG_PROMPT_VERSION 不能为空")
        if (
            environment not in _LOCAL_EVAL_SNAPSHOT_ENVS
            and self.eval_snapshot_security_mode == "plain"
        ):
            raise ValueError(
                "共享环境禁止 EVAL_SNAPSHOT_SECURITY_MODE=plain；"
                "请使用 redacted 或 encrypted"
            )

        if self.eval_snapshot_security_mode != "encrypted":
            return self

        active_key_id = self.eval_snapshot_encryption_active_key_id.strip()
        if not active_key_id:
            raise ValueError(
                "encrypted Eval snapshot 必须配置 EVAL_SNAPSHOT_ENCRYPTION_ACTIVE_KEY_ID"
            )

        try:
            raw_key_ring = json.loads(self.eval_snapshot_encryption_keys_json)
        except json.JSONDecodeError as exc:
            raise ValueError("EVAL_SNAPSHOT_ENCRYPTION_KEYS_JSON 必须是合法 JSON") from exc
        if not isinstance(raw_key_ring, dict) or not raw_key_ring:
            raise ValueError("encrypted Eval snapshot key ring 不能为空")
        if active_key_id not in raw_key_ring:
            raise ValueError("Eval snapshot active key ID 必须存在于 key ring")

        for key_id, encoded_key in raw_key_ring.items():
            if not isinstance(key_id, str) or not key_id.strip():
                raise ValueError("Eval snapshot key ID 不能为空")
            if not isinstance(encoded_key, str):
                raise ValueError("Eval snapshot key 必须是 base64 字符串")
            try:
                decoded_key = base64.b64decode(
                    encoded_key,
                    altchars=b"-_",
                    validate=True,
                )
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Eval snapshot key 必须是合法 URL-safe base64") from exc
            if len(decoded_key) != 32:
                raise ValueError("Eval snapshot AES-256-GCM key 解码后必须为 32 字节")

        return self

    @field_validator("eval_snapshot_security_mode", mode="before")
    @classmethod
    def normalize_eval_snapshot_security_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

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

    @field_validator("agent_router_structured_output_method", mode="before")
    @classmethod
    def normalize_agent_router_structured_output_method(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized not in {"function_calling", "json_mode", "json_schema"}:
            raise ValueError(
                "AGENT_ROUTER_STRUCTURED_OUTPUT_METHOD 只支持 "
                "function_calling、json_mode 或 json_schema"
            )
        return normalized

    def validate_agent_router_config(self) -> None:
        """在应用启动阶段一次性拒绝缺失的 Router 连接配置。"""

        required = {
            "AGENT_ROUTER_API_KEY": self.agent_router_api_key,
            "AGENT_ROUTER_BASE_URL": self.agent_router_base_url,
            "AGENT_ROUTER_MODEL_NAME": self.agent_router_model_name,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "Agent Router 配置缺失: " + ", ".join(missing)
            )

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
        if normalized not in {"confirmation_required", "risk_based", "dry_run_only"}:
            raise ValueError(
                "AGENT_TOOL_EXECUTION_POLICY 只支持 confirmation_required / risk_based / dry_run_only"
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
    def agent_document_tools_allowed_extension_list(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.agent_document_tools_allowed_extensions.split(",")
            if item.strip()
        ]
# @lru_cache 第一次调用 get_settings() 时创建 Settings。后续再次调用，直接返回第一次创建好的对象。
# Settings 在应用运行期间通常是稳定的。没有必要每个请求都重新读取 .env。
def get_secret_env_value(name: str, env_file: str = ".env") -> str:
    """优先读取服务器环境变量，本地开发时回退到未提交的 .env。"""

    value = os.environ.get(name)
    if value is not None:
        return value
    return str(dotenv_values(env_file).get(name) or "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
