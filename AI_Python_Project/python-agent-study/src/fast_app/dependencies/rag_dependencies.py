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
from fast_app.services.rag.langgraph_rag_pipeline_service import LangGraphRagPipeline
from fast_app.services.conversation.conversation_memory import (
    ConversationMemoryStore,
    InMemoryConversationMemoryStore,
    RedisConversationMemoryStore,
)
from fast_app.services.conversation.conversation_repository import PostgresConversationRepository
from fast_app.services.conversation.conversation_persistence import ConversationPersistenceService
from fast_app.services.conversation.conversation_summary import ConversationSummaryService
from fast_app.services.knowledge.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)
from fast_app.services.conversation.query_rewrite import ConversationQueryRewriter
from fast_app.services.rag.rag_agent_pipeline_service import RagAgentPipeline
from fast_app.services.rag.rag_pipeline_service import RagPipeline
from fast_app.services.rag.prompt_guard_service import PromptGuardService
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.auth.auth_service import AuthService
from fast_app.services.auth.user_repository import UserRepository
from fast_app.services.auth.permission_repository import PermissionRepository
from fast_app.services.auth.permission_service import PermissionService
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.research.agentic_research_executor import AgenticResearchExecutor
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from fast_app.services.agent_tasks.deep_document_agent import DeepDocumentAgent
from fast_app.services.agent_tasks.deep_document_runtime import DeepDocumentRuntime
from fast_app.services.agent_tasks.document_supervisor_agent import DocumentSupervisorAgent
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import ResearchToolLoop
from fast_app.services.research.research_worker_agent import ResearchWorkerAgent
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.agent_task_router import AgentTaskRouter
from fast_app.services.agent_tasks.agent_tool_audit_service import AgentToolAuditService
from fast_app.services.agent_tasks.agent_tool_permission_service import AgentToolPermissionService
from fast_app.integrations.gitlab.agent_change_service import GitLabAgentChangeService
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.service import Nl2SqlService

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


def get_auth_service(
    settings: Settings = Depends(get_settings),
    repository: UserRepository = Depends(get_user_repository),
    permission_service: PermissionService = Depends(get_permission_service),
) -> AuthService:
    """提供认证业务服务。"""

    return AuthService(
        settings=settings,
        repository=repository,
        permission_service=permission_service,
    )


def get_agent_task_planner(
    settings: Settings = Depends(get_settings),
) -> AgentTaskPlanner:
    """提供 Agent 多步骤任务规划器。"""

    return AgentTaskPlanner(settings=settings)


def get_agent_task_router(
    settings: Settings = Depends(get_settings),
) -> AgentTaskRouter:
    """提供使用独立连接配置的 Agent 语义 Router。"""

    return AgentTaskRouter(settings=settings)


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


def get_markdown_parent_context_expander(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> MarkdownParentContextExpander:
    return MarkdownParentContextExpander(
        settings=settings,
        client=getattr(request.app.state, "elasticsearch_client", None),
    )


def get_knowledge_document_management_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    embedding_client: BaseEmbeddingClient = Depends(get_embedding_client),
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeDocumentManagementService:
    """提供 Agent 文档管理工具的后端服务边界。

    dry-run 只读取预览；TaskPlan 确认执行会使用这里注入的 embedding、ES、Milvus
    client 做单文档同步。生产装配缺任一 client 时，真实写入会被 service 拒绝。
    """

    return KnowledgeDocumentManagementService(
        settings=settings,
        embedding_client=embedding_client,
        elasticsearch_client=getattr(request.app.state, "elasticsearch_client", None),
        milvus_client=getattr(request.app.state, "milvus_client", None),
        gitlab_change_service=GitLabAgentChangeService(
            settings=settings,
            repository=GitLabRepository(session),
        ),
    )


def get_agent_task_executor(
    request: Request,
    settings: Settings = Depends(get_settings),
    vector_retriever: BaseRetriever = Depends(get_vector_retriever),
    keyword_retriever: BaseRetriever = Depends(get_keyword_retriever),
    llm_client: BaseLLMClient = Depends(get_llm_client),
    reranker: BaseReranker = Depends(get_reranker),
    document_management_service: KnowledgeDocumentManagementService = Depends(
        get_knowledge_document_management_service
    ),
    tool_permission_service: AgentToolPermissionService = Depends(
        get_agent_tool_permission_service
    ),
    tool_audit_service: AgentToolAuditService = Depends(get_agent_tool_audit_service),
    task_plan_store: AgentTaskPlanStore = Depends(get_agent_task_plan_store),
    prompt_guard: PromptGuardService = Depends(get_prompt_guard_service),
    parent_expander: MarkdownParentContextExpander = Depends(
        get_markdown_parent_context_expander
    ),
    session: AsyncSession = Depends(get_db_session),
) -> AgentTaskExecutor:
    """提供 Agent TaskPlan 执行器。"""

    deep_document_runtime = getattr(
        request.app.state,
        "deep_document_runtime",
        None,
    )
    if settings.agent_document_tools_enabled and not isinstance(
        deep_document_runtime,
        DeepDocumentRuntime,
    ):
        raise AppServiceError("Deep Agent PostgreSQL checkpoint/store 未初始化")
    nl2sql_registry = getattr(request.app.state, "nl2sql_dataset_registry", None)
    nl2sql_service = (
        Nl2SqlService(
            settings=settings,
            registry=nl2sql_registry,
            session=session,
        )
        if isinstance(nl2sql_registry, DatasetRegistry)
        else None
    )

    # 两条多 Agent 链路在依赖层显式装配，Facade 只负责按 task_kind 分派：
    # Research 使用父图 + Worker 子图；文档任务使用 Supervisor + Deep Agents。
    research_tool_loop = ResearchToolLoop(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
        reranker=reranker,
        prompt_guard=prompt_guard,
        parent_expander=parent_expander,
        nl2sql_service=nl2sql_service,
    )
    research_worker = ResearchWorkerAgent(
        settings=settings,
        tool_loop=research_tool_loop,
        evaluator=ResearchEvidenceEvaluator(settings),
    )
    research_executor = AgenticResearchExecutor(
        settings=settings,
        llm_client=llm_client,
        task_plan_store=task_plan_store,
        worker_agent=research_worker,
    )
    # 真实写入 Service 同时注入 Executor 和 DeepDocumentAgent：前者负责确认执行，
    # 后者只通过受控 read 工具读取原文，不拥有 execute_confirmed_actions 入口。
    document_executor = DocumentTaskExecutor(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        document_management_service=document_management_service,
        tool_permission_service=tool_permission_service,
        tool_audit_service=tool_audit_service,
        task_plan_store=task_plan_store,
        supervisor_agent=DocumentSupervisorAgent(settings),
        deep_document_agent=DeepDocumentAgent(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            document_management_service=document_management_service,
            task_plan_store=task_plan_store,
            prompt_guard=prompt_guard,
            runtime=deep_document_runtime,
            nl2sql_service=nl2sql_service,
        ),
    )
    return AgentTaskExecutor(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
        document_management_service=document_management_service,
        tool_permission_service=tool_permission_service,
        tool_audit_service=tool_audit_service,
        task_plan_store=task_plan_store,
        research_executor=research_executor,
        document_executor=document_executor,
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
    parent_expander: MarkdownParentContextExpander = Depends(
        get_markdown_parent_context_expander
    ),
    task_router: AgentTaskRouter = Depends(get_agent_task_router),
    task_planner: AgentTaskPlanner = Depends(get_agent_task_planner),
    task_executor: AgentTaskExecutor = Depends(get_agent_task_executor),
    conversation_persistence: ConversationPersistenceService = Depends(
        get_conversation_persistence_service
    ),
    session: AsyncSession = Depends(get_db_session),
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
            parent_expander=parent_expander,
        )

    if provider == "langgraph":
        return LangGraphRagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
            prompt_guard=prompt_guard,
            parent_expander=parent_expander,
        )

    # 13-11 新增的第三条执行路线。
    # 它复用同一组 retriever / reranker / llm 依赖，但进入独立的 RAG Agent graph。
    if provider == "rag_agent":
        registry = getattr(request.app.state, "nl2sql_dataset_registry", None)
        nl2sql_service = (
            Nl2SqlService(settings=settings, registry=registry, session=session)
            if isinstance(registry, DatasetRegistry)
            else None
        )
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
            task_router=task_router,
            task_planner=task_planner,
            task_executor=task_executor,
            parent_expander=parent_expander,
            nl2sql_service=nl2sql_service,
        )

    raise AppServiceError(
        f"不支持的 RAG_PIPELINE_PROVIDER: {settings.rag_pipeline_provider}"
    )
