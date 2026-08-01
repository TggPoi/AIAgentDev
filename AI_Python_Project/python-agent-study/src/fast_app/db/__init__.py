"""数据库基础设施包。

这个包只负责数据库连接、ORM 表结构和迁移边界，不承载具体业务流程。
"""

from fast_app.db.base import Base
from fast_app.db.auth_tables import (
    ApiKeyTable,
    DepartmentTable,
    PermissionTable,
    RefreshTokenTable,
    RolePermissionTable,
    RoleTable,
    UserDepartmentTable,
    UserDepartmentRoleTable,
    UserRoleTable,
    UserTable,
)
from fast_app.db.conversation_tables import (
    ConversationMessageTable,
    ConversationSummaryTable,
    ConversationTable,
)
from fast_app.db.ingestion_tables import (
    KnowledgeDocumentTable,
    KnowledgeExcelImportProfileTable,
    KnowledgeIngestionJobTable,
)
from fast_app.db.gitlab_tables import (
    GitLabChangeRequestTable,
    GitLabDocumentTable,
    GitLabSourceTable,
    GitLabSyncJobTable,
    GitLabWebhookDeliveryTable,
    KnowledgeChangeEventTable,
    KnowledgePublicationStateTable,
    KnowledgePublicationTable,
)
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.db.nl2sql_tables import (
    Nl2SqlDatasetGrantTable,
    Nl2SqlDatasetTable,
    Nl2SqlQueryAuditTable,
)

__all__ = [
    "ApiKeyTable",
    "Base",
    "ConversationMessageTable",
    "ConversationSummaryTable",
    "ConversationTable",
    "DepartmentTable",
    "KnowledgeDocumentTable",
    "KnowledgeExcelImportProfileTable",
    "KnowledgeIngestionJobTable",
    "GitLabChangeRequestTable",
    "GitLabDocumentTable",
    "GitLabSourceTable",
    "GitLabSyncJobTable",
    "GitLabWebhookDeliveryTable",
    "KnowledgeChangeEventTable",
    "KnowledgePublicationStateTable",
    "KnowledgePublicationTable",
    "PermissionTable",
    "Nl2SqlDatasetGrantTable",
    "Nl2SqlDatasetTable",
    "Nl2SqlQueryAuditTable",
    "RefreshTokenTable",
    "RolePermissionTable",
    "RoleTable",
    "UserDepartmentTable",
    "UserDepartmentRoleTable",
    "UserRoleTable",
    "UserTable",
    "create_database_engine",
    "create_session_factory",
]
