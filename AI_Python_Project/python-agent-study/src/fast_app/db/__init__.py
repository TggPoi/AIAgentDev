"""数据库基础设施包。

这个包只负责数据库连接、ORM 表结构和迁移边界，不承载具体业务流程。
"""

from fast_app.db.base import Base
from fast_app.db.auth_tables import (
    ApiKeyTable,
    DepartmentTable,
    RefreshTokenTable,
    UserDepartmentTable,
    UserTable,
)
from fast_app.db.conversation_tables import (
    ConversationMessageTable,
    ConversationSummaryTable,
    ConversationTable,
)
from fast_app.db.session import create_database_engine, create_session_factory

__all__ = [
    "ApiKeyTable",
    "Base",
    "ConversationMessageTable",
    "ConversationSummaryTable",
    "ConversationTable",
    "DepartmentTable",
    "RefreshTokenTable",
    "UserDepartmentTable",
    "UserTable",
    "create_database_engine",
    "create_session_factory",
]
