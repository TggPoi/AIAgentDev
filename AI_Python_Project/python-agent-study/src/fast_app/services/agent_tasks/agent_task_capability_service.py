"""Research Planner 和 Direct Web 共用的当前能力解析。"""

from __future__ import annotations

from fast_app.core.config import Settings
from fast_app.domain.agent_tool_permissions import PermissionCode
from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskExternalSourceType,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import (
    AgentTaskSourceUnavailableError,
    ToolPermissionDeniedError,
)
from fast_app.services.nl2sql.authorization import Nl2SqlAuthorizationService
from fast_app.services.nl2sql.catalog import SchemaCatalog
from fast_app.services.nl2sql.registry import DatasetRegistry


class AgentTaskCapabilityService:
    """从当前用户、请求策略和可信 Dataset 配置解析非敏感能力。"""

    def __init__(
        self,
        *,
        settings: Settings,
        dataset_registry: DatasetRegistry | None,
        nl2sql_authorization: Nl2SqlAuthorizationService,
    ) -> None:
        self._settings = settings
        self._dataset_registry = dataset_registry
        self._nl2sql_authorization = nl2sql_authorization
        self._catalog = SchemaCatalog()

    def resolve_direct_web(
        self,
        *,
        user: CurrentUserContext,
        allow_direct_web: bool,
    ) -> None:
        """校验简单 Web 路由，复用同一权限与 Provider 判断。"""

        if not user.has_global_permission(PermissionCode.AGENT_TOOL_WEB_SEARCH.value):
            raise ToolPermissionDeniedError("当前用户没有 Web Search Tool 权限")
        if not allow_direct_web:
            raise AgentTaskSourceUnavailableError("当前请求策略禁止 direct Web")
        if not self._settings.bocha_api_key:
            raise AgentTaskSourceUnavailableError("Web Search Provider 尚未配置")

    async def resolve_research(
        self,
        *,
        user: CurrentUserContext,
        dataset_id: str | None,
        allow_direct_web: bool,
        allow_web_fallback: bool,
        required_source_types: list[AgentTaskExternalSourceType] | None = None,
    ) -> AgentTaskCapabilitySnapshot:
        """构造 Planner 可用的当前能力摘要；确认时必须重新调用。"""

        required_sources = set(required_source_types or [])
        if "web_search" in required_sources:
            self.resolve_direct_web(
                user=user,
                allow_direct_web=allow_direct_web,
            )

        web_permission = user.has_global_permission(
            PermissionCode.AGENT_TOOL_WEB_SEARCH.value
        )
        web_configured = bool(self._settings.bocha_api_key)
        available_sources = ["knowledge_retrieval"]
        if web_permission and web_configured and (
            allow_direct_web or allow_web_fallback
        ):
            available_sources.append("web_search")

        dataset_name = None
        dataset_domain = None
        allowed_views: list[str] = []
        allowed_fields: list[str] = []
        dataset_schema_context = None
        nl2sql_available = False
        if dataset_id:
            if self._dataset_registry is None:
                raise AgentTaskSourceUnavailableError("NL2SQL Dataset Registry 尚未配置")
            dataset = self._dataset_registry.get(dataset_id)
            if dataset.privacy_classification == "sensitive":
                raise AgentTaskSourceUnavailableError(
                    "敏感 Dataset 不允许进入普通 Research PlanningContext"
                )
            await self._nl2sql_authorization.authorize(user, dataset)
            pool = await self._dataset_registry.pool(dataset)
            async with pool.acquire() as connection:
                fields = await self._catalog.load_logical_fields(connection, dataset)
                raw_schema_context = await self._catalog.load(
                    connection,
                    dataset,
                    logical_names=False,
                )
                dataset_schema_context = (
                    "<dataset_metadata trust=\"untrusted_business_data\">\n"
                    + raw_schema_context[:20_000].replace(
                        "</dataset_metadata>", "&lt;/dataset_metadata&gt;"
                    )
                    + "\n</dataset_metadata>"
                )
            dataset_name = dataset.name
            dataset_domain = dataset.domain
            allowed_views = list(dataset.allowed_views)
            allowed_fields = sorted(fields)
            nl2sql_available = True
            available_sources.append("nl2sql_query")

        missing_required_sources = required_sources - set(available_sources)
        if missing_required_sources:
            missing_text = ", ".join(sorted(missing_required_sources))
            raise AgentTaskSourceUnavailableError(
                f"当前请求无法提供用户必需来源: {missing_text}"
            )

        return AgentTaskCapabilitySnapshot(
            available_source_types=available_sources,
            web_direct_allowed=web_permission and web_configured and allow_direct_web,
            web_fallback_allowed=(
                web_permission and web_configured and allow_web_fallback
            ),
            knowledge_retrieval_available=True,
            nl2sql_query_available=nl2sql_available,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            dataset_domain=dataset_domain,
            allowed_dataset_views=allowed_views,
            allowed_dataset_fields=allowed_fields,
            dataset_schema_context=dataset_schema_context,
            max_requirements=self._settings.agent_research_max_sub_questions * 2,
            max_sub_questions=self._settings.agent_research_max_sub_questions,
        )


__all__ = ["AgentTaskCapabilityService"]
