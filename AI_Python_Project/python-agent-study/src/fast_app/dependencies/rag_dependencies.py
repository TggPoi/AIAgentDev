from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.components.retrievers.mock_keyword_retriever import MockKeywordRetriever
from fast_app.components.retrievers.mock_vector_retriever import MockVectorRetriever
from fast_app.core.config import Settings, get_settings
from fast_app.services.exceptions import AppServiceError
from fast_app.services.langgraph_rag_pipeline_service import LangGraphRagPipeline
from fast_app.services.conversation_memory import (
    ConversationMemoryStore,
    InMemoryConversationMemoryStore,
    RedisConversationMemoryStore,
)
from fast_app.services.conversation_repository import PostgresConversationRepository
from fast_app.services.conversation_persistence import ConversationPersistenceService
from fast_app.services.conversation_summary import ConversationSummaryService
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.query_rewrite import ConversationQueryRewriter
from fast_app.services.rag_agent_pipeline_service import RagAgentPipeline
from fast_app.services.rag_pipeline_service import RagPipeline
from fast_app.services.prompt_guard_service import PromptGuardService
from fast_app.services.auth_service import AuthService
from fast_app.services.user_repository import UserRepository
from fast_app.services.permission_repository import PermissionRepository
from fast_app.services.permission_service import PermissionService
from fast_app.services.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tool_permission_service import AgentToolPermissionService

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.components.retrievers.milvus_vector_retriever import MilvusVectorRetriever

from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.rerankers.dashscope_reranker import DashScopeReranker
from fast_app.components.rerankers.mock_reranker import MockReranker

def get_llm_client(
    settings: Settings = Depends(get_settings),
) -> BaseLLMClient:
    provider = settings.llm_provider.lower().strip()

    if provider == "mock":
        return MockLLMClient(settings=settings)

    if provider == "qwen":
        return QwenLangChainLLMClient(settings=settings)

    raise AppServiceError(f"不支持的 LLM_PROVIDER: {settings.llm_provider}")


def get_embedding_client(
    settings: Settings = Depends(get_settings),
) -> BaseEmbeddingClient:
    provider = settings.embedding_provider.lower().strip()

    if provider == "qwen":
        return QwenEmbeddingClient(settings=settings)

    raise AppServiceError(
        f"不支持的 EMBEDDING_PROVIDER: {settings.embedding_provider}"
    )



def get_vector_retriever(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> BaseRetriever:
    provider = settings.vector_retriever_provider.lower().strip()

    if provider == "mock":
        return MockVectorRetriever()

    if provider == "milvus":
        embedding_client = get_embedding_client(settings=settings)
        milvus_client = request.app.state.milvus_client

        return MilvusVectorRetriever(
            settings=settings,
            embedding_client=embedding_client,
            client=milvus_client,
        )

    raise AppServiceError(
        f"不支持的 VECTOR_RETRIEVER_PROVIDER: {settings.vector_retriever_provider}"
    )


def get_keyword_retriever(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> BaseRetriever:
    provider = settings.keyword_retriever_provider.lower().strip()

    if provider == "mock":
        return MockKeywordRetriever()

    if provider == "elasticsearch":
        elasticsearch_client = request.app.state.elasticsearch_client

        return ElasticsearchKeywordRetriever(
            settings=settings,
            client=elasticsearch_client,
        )

    raise AppServiceError(
        f"不支持的 KEYWORD_RETRIEVER_PROVIDER: {settings.keyword_retriever_provider}"
    )


def get_reranker(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> BaseReranker:
    provider = settings.reranker_provider.lower().strip()

    if provider == "none":
        return MockReranker()

    if provider == "mock":
        return MockReranker()

    if provider == "dashscope":
        return DashScopeReranker(
            settings=settings,
            http_client=request.app.state.rerank_http_client,
        )

    raise AppServiceError(
        f"不支持的 RERANKER_PROVIDER: {settings.reranker_provider}"
    )

# 内存记忆配置
def get_conversation_memory_store(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ConversationMemoryStore:
    provider = settings.memory_store_provider.lower().strip()

    if provider == "in_memory":
        store = getattr(request.app.state, "conversation_memory_store", None)
        if store is None:
            store = InMemoryConversationMemoryStore()
            request.app.state.conversation_memory_store = store

        return store

    if provider == "redis":
        redis_client = getattr(request.app.state, "redis_client", None)
        if redis_client is None:
            raise AppServiceError("Redis client 尚未初始化，无法使用 Redis 会话记忆")

        return RedisConversationMemoryStore(
            redis_client=redis_client,
            ttl_seconds=settings.memory_ttl_seconds,
            max_messages=settings.memory_max_messages,
        )

    raise AppServiceError(
        f"不支持的 MEMORY_STORE_PROVIDER: {settings.memory_store_provider}"
    )


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """为一次请求打开一个数据库 Session，并在请求结束后自动关闭。"""

    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise AppServiceError("数据库 Session 工厂尚未初始化")

    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_conversation_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresConversationRepository:
    """提供 Conversation 持久化仓储，后续 API 可以按需注入。"""

    return PostgresConversationRepository(session=session)


def get_conversation_persistence_service(
    repository: PostgresConversationRepository = Depends(get_conversation_repository),
) -> ConversationPersistenceService:
    """提供 PostgreSQL 会话持久化服务。"""

    return ConversationPersistenceService(repository=repository)


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """提供用户身份体系仓储。"""

    return UserRepository(session=session)


def get_auth_service(
    settings: Settings = Depends(get_settings),
    repository: UserRepository = Depends(get_user_repository),
) -> AuthService:
    """提供认证业务服务。"""

    return AuthService(settings=settings, repository=repository)


def get_permission_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PermissionRepository:
    """提供 RBAC 权限仓储。"""

    return PermissionRepository(session=session)


def get_permission_service(
    repository: PermissionRepository = Depends(get_permission_repository),
) -> PermissionService:
    """提供用户有效权限计算服务。"""

    return PermissionService(repository=repository)


def get_agent_task_planner(
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanner:
    """提供 Agent 多步骤任务规划器。"""

    return AgentTaskPlanner(settings=settings)


def get_agent_task_plan_store(
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanStore:
    """提供 Agent task plan runtime JSON 存储。"""

    return AgentTaskPlanStore(settings=settings)


def get_agent_tool_permission_service(
    permission_service: PermissionService = Depends(get_permission_service),
) -> AgentToolPermissionService:
    """提供 Agent 工具权限网关。"""

    return AgentToolPermissionService(permission_service=permission_service)


def get_agent_tool_audit_service() -> AgentToolAuditService:
    """提供 Agent 工具审计服务。"""

    return AgentToolAuditService()


def get_prompt_guard_service(
    settings: Settings = Depends(get_settings),
) -> PromptGuardService:
    """提供 Prompt Injection 分层防护服务。"""

    return PromptGuardService(settings=settings)


def get_knowledge_document_management_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    embedding_client: BaseEmbeddingClient = Depends(get_embedding_client),
) -> KnowledgeDocumentManagementService:
    """提供 Agent 文档管理工具的后端服务边界。

    15-6.5 只使用 dry-run 主线，所以 ES / Milvus client 可以为空。这里仍优先从
    app.state 读取外部 client，是为了后续 15-7 放开受控执行时复用同一套依赖注入。
    """

    return KnowledgeDocumentManagementService(
        settings=settings,
        embedding_client=embedding_client,
        elasticsearch_client=getattr(request.app.state, "elasticsearch_client", None),
        milvus_client=getattr(request.app.state, "milvus_client", None),
    )


def get_agent_task_executor(
    settings: Settings = Depends(get_settings),
    vector_retriever: BaseRetriever = Depends(get_vector_retriever),
    keyword_retriever: BaseRetriever = Depends(get_keyword_retriever),
    llm_client: BaseLLMClient = Depends(get_llm_client),
    document_management_service: KnowledgeDocumentManagementService = Depends(
        get_knowledge_document_management_service
    ),
    tool_permission_service: AgentToolPermissionService = Depends(
        get_agent_tool_permission_service
    ),
    tool_audit_service: AgentToolAuditService = Depends(get_agent_tool_audit_service),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
) -> AgentTaskExecutor:
    """提供 Agent TaskPlan 执行器。"""

    return AgentTaskExecutor(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
        document_management_service=document_management_service,
        tool_permission_service=tool_permission_service,
        tool_audit_service=tool_audit_service,
        task_plan_store=task_plan_store,
    )



# 这里先不写返回类型，因为RagPipeline LangGraphRagPipeline这两个类目前没有共同的显式基类。
def get_rag_pipeline(
    request: Request,
    settings: Settings = Depends(get_settings),
    vector_retriever: BaseRetriever = Depends(get_vector_retriever),
    keyword_retriever: BaseRetriever = Depends(get_keyword_retriever),
    llm_client: BaseLLMClient = Depends(get_llm_client),
    reranker: BaseReranker = Depends(get_reranker),
    prompt_guard: PromptGuardService = Depends(get_prompt_guard_service),
    task_planner: AgentTaskPlanner = Depends(get_agent_task_planner),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    conversation_persistence: ConversationPersistenceService = Depends(
        get_conversation_persistence_service
    ),
):
    provider = settings.rag_pipeline_provider.lower().strip()

    if provider == "classic":
        return RagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            prompt_guard=prompt_guard,
        )

    if provider == "langgraph":
        return LangGraphRagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            prompt_guard=prompt_guard,
        )

    # 13-11 新增的第三条执行路线。
    # 它复用同一组 retriever / reranker / llm 依赖，但进入独立的 RAG Agent graph。
    if provider == "rag_agent":
        conversation_memory_store = get_conversation_memory_store(
            request=request,
            settings=settings,
        )
        conversation_summary_service = ConversationSummaryService.from_settings(
            settings=settings,
            repository=conversation_persistence.repository,
        )
        return RagAgentPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            conversation_memory_store=conversation_memory_store,
            query_rewriter=ConversationQueryRewriter.from_settings(settings),
            conversation_persistence=conversation_persistence,
            conversation_summary_service=conversation_summary_service,
            prompt_guard=prompt_guard,
            task_planner=task_planner,
            task_executor=task_executor,
        )

    raise AppServiceError(
        f"不支持的 RAG_PIPELINE_PROVIDER: {settings.rag_pipeline_provider}"
    )
