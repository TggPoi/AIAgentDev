from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fast_app.api.chat_routes import router as chat_router
from fast_app.api.auth_routes import router as auth_router
from fast_app.api.agent_task_plan_routes import router as agent_task_plan_router
from fast_app.api.health_routes import router as health_router
from fast_app.api.knowledge_import_routes import router as knowledge_import_router
from fast_app.api.rag_chat_routes import router as rag_chat_router
from fast_app.api.rag_routes import router as rag_router
from fast_app.api.stream_routes import router as stream_router
from fast_app.api.error_demo_routes import router as error_demo_router
from fast_app.api.debug_trace_routes import router as debug_trace_router
from fast_app.api.document_access_routes import router as document_access_router
from fast_app.api.conversation_routes import router as conversation_router
from fast_app.api.knowledge_document_routes import router as knowledge_document_router
from fast_app.api.gitlab_routes import router as gitlab_router
from fast_app.api.nl2sql_routes import router as nl2sql_router
from fast_app.api.user_admin_routes import router as user_admin_router
from fast_app.core.config import get_settings
from fast_app.core.langsmith import configure_langsmith
from fast_app.core.logging import get_logger, setup_logging
from fast_app.core.request_context import REQUEST_ID_HEADER
from fast_app.middlewares.request_id_middleware import RequestIdMiddleware
from fast_app.middlewares.request_size_middleware import RequestSizeLimitMiddleware

from fast_app.core.exception_handlers import register_exception_handlers
import httpx
from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient
from redis.asyncio import Redis

from fast_app.components.retrievers.milvus_vector_retriever import build_milvus_uri
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
)
from fast_app.services.agent_tasks.deep_document_runtime import DeepDocumentRuntime
from fast_app.services.nl2sql.registry import DatasetRegistry

settings = get_settings()
logger = get_logger(__name__)

# 把一个 async generator 函数，包装成可以用于管理“进入 / 退出”流程的上下文管理器。
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(settings)
    configure_langsmith(settings)
    settings.validate_agent_router_config()

    logger.info("应用启动: app_name=%s, env=%s", settings.app_name, settings.app_env)

    if settings.vector_retriever_provider.lower().strip() == "milvus":
        app.state.milvus_client = MilvusClient(
            uri=build_milvus_uri(
                host=settings.milvus_host,
                port=settings.milvus_port,
            )
        )
        logger.info("Milvus client 已创建")

    if settings.keyword_retriever_provider.lower().strip() == "elasticsearch":
        app.state.elasticsearch_client = AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
        )
        logger.info("ElasticSearch client 已创建")

    if settings.reranker_provider.lower().strip() == "dashscope":
        app.state.rerank_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.rerank_timeout_seconds)
        )
        logger.info("Rerank httpx client 已创建")

    if settings.memory_store_provider.lower().strip() == "redis":
        app.state.redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        logger.info("Redis client 已创建")

    app.state.db_engine = create_database_engine(settings)
    app.state.db_session_factory = create_session_factory(app.state.db_engine)
    logger.info("PostgreSQL async engine 已创建")
    app.state.agent_task_plan_repository = AgentTaskPlanRepository(
        app.state.db_session_factory
    )
    # 多实例共享的复杂任务容量槽：幂等补齐当前配置的槽位，多个 Worker 同时
    # 启动也不会产生重复行。
    await app.state.agent_task_plan_repository.ensure_capacity_slots(
        workload_type="research",
        count=settings.agent_research_global_concurrency,
    )
    await app.state.agent_task_plan_repository.ensure_capacity_slots(
        workload_type="document",
        count=settings.agent_document_global_concurrency,
    )
    logger.info("Agent TaskPlan PostgreSQL Repository 与容量槽已初始化")
    app.state.nl2sql_dataset_registry = DatasetRegistry(settings)
    async with app.state.db_session_factory() as session:
        await app.state.nl2sql_dataset_registry.refresh(session)
    logger.info("NL2SQL Dataset 配置已从平台数据库加载")

    if settings.agent_document_tools_enabled:
        # Deep Agent 的 StateBackend.files 随加密 checkpoint 持久化；同一 runtime
        # 在整个 FastAPI lifespan 内复用，避免每个请求重复创建 psycopg 连接池。
        app.state.deep_document_runtime = await DeepDocumentRuntime.start(
            settings,
            app.state.agent_task_plan_repository,
        )
        logger.info("Deep Agent PostgreSQL checkpoint 已创建")

    try:
        yield
    finally:
        milvus_client = getattr(app.state, "milvus_client", None)
        if milvus_client is not None:
            milvus_client.close()
            logger.info("Milvus client 已关闭")

        elasticsearch_client = getattr(app.state, "elasticsearch_client", None)
        if elasticsearch_client is not None:
            await elasticsearch_client.close()
            logger.info("ElasticSearch client 已关闭")

        rerank_http_client = getattr(app.state, "rerank_http_client", None)
        if rerank_http_client is not None:
            await rerank_http_client.aclose()
            logger.info("Rerank httpx client 已关闭")

        redis_client = getattr(app.state, "redis_client", None)
        if redis_client is not None:
            await redis_client.aclose()
            logger.info("Redis client 已关闭")

        deep_document_runtime = getattr(app.state, "deep_document_runtime", None)
        if deep_document_runtime is not None:
            await deep_document_runtime.close()
            logger.info("Deep Agent PostgreSQL checkpoint/store 已关闭")

        db_engine = getattr(app.state, "db_engine", None)
        if db_engine is not None:
            await db_engine.dispose()
            logger.info("PostgreSQL async engine 已关闭")

        nl2sql_registry = getattr(app.state, "nl2sql_dataset_registry", None)
        if isinstance(nl2sql_registry, DatasetRegistry):
            await nl2sql_registry.close()
            logger.info("NL2SQL 只读连接池已关闭")

        logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
    max_upload_body_bytes=settings.max_upload_request_body_bytes,
)
app.add_middleware(
    RequestIdMiddleware,
    slow_http_request_threshold_ms=settings.slow_http_request_threshold_ms,
)

register_exception_handlers(app)

app.include_router(health_router)
app.include_router(knowledge_import_router)
app.include_router(auth_router)
app.include_router(agent_task_plan_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(rag_chat_router)
app.include_router(stream_router)
app.include_router(error_demo_router)
app.include_router(debug_trace_router)
app.include_router(gitlab_router)
app.include_router(nl2sql_router)
app.include_router(user_admin_router)
app.include_router(document_access_router)
app.include_router(conversation_router)
app.include_router(knowledge_document_router)
