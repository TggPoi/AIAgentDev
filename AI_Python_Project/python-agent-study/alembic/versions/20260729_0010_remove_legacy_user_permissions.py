"""remove legacy user permissions and complete RBAC permissions

Revision ID: 20260729_0010
Revises: 20260726_0009
Create Date: 2026-07-29 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260729_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_PERMISSIONS = (
    {
        "id": "perm_knowledge_read_all",
        "code": "knowledge:read:all",
        "name": "读取全部知识库文档",
        "description": "允许跨用户和跨部门读取全部知识库内容",
        "category": "knowledge_document",
        "risk_level": "high",
    },
    {
        "id": "perm_gitlab_source_manage",
        "code": "gitlab:source:manage",
        "name": "管理 GitLab 文档源",
        "description": "允许查看文档源、触发或重试 GitLab 同步任务",
        "category": "gitlab",
        "risk_level": "high",
    },
    {
        "id": "perm_gitlab_change_read_all",
        "code": "gitlab:change:read_all",
        "name": "读取全部 GitLab 知识变更",
        "description": "允许跨用户和跨部门读取全部 GitLab 知识变更事件",
        "category": "gitlab",
        "risk_level": "high",
    },
)

NEW_ROLES = (
    {
        "id": "role_knowledge_global_reader",
        "code": "knowledge_global_reader",
        "name": "全局知识库读者",
        "description": "允许跨用户和跨部门读取全部知识库内容",
    },
    {
        "id": "role_agent_tool_operator",
        "code": "agent_tool_operator",
        "name": "Agent 工具操作员",
        "description": "允许调用计算、Web Search 和白名单 MCP 工具",
    },
    {
        "id": "role_gitlab_manager",
        "code": "gitlab_manager",
        "name": "GitLab 文档源管理员",
        "description": "允许管理 GitLab 文档源、同步任务和知识变更事件",
    },
)

NEW_ROLE_PERMISSIONS = (
    {
        "id": "rp_admin_knowledge_read_all",
        "role_id": "role_system_admin",
        "permission_id": "perm_knowledge_read_all",
    },
    {
        "id": "rp_admin_gitlab_source_manage",
        "role_id": "role_system_admin",
        "permission_id": "perm_gitlab_source_manage",
    },
    {
        "id": "rp_admin_gitlab_change_read_all",
        "role_id": "role_system_admin",
        "permission_id": "perm_gitlab_change_read_all",
    },
    {
        "id": "rp_global_reader_read_all",
        "role_id": "role_knowledge_global_reader",
        "permission_id": "perm_knowledge_read_all",
    },
    {
        "id": "rp_agent_operator_calculator",
        "role_id": "role_agent_tool_operator",
        "permission_id": "perm_agent_tool_calculator",
    },
    {
        "id": "rp_agent_operator_web_search",
        "role_id": "role_agent_tool_operator",
        "permission_id": "perm_agent_tool_web_search",
    },
    {
        "id": "rp_agent_operator_mcp",
        "role_id": "role_agent_tool_operator",
        "permission_id": "perm_agent_tool_mcp",
    },
    {
        "id": "rp_gitlab_manager_source",
        "role_id": "role_gitlab_manager",
        "permission_id": "perm_gitlab_source_manage",
    },
    {
        "id": "rp_gitlab_manager_change",
        "role_id": "role_gitlab_manager",
        "permission_id": "perm_gitlab_change_read_all",
    },
)


def upgrade() -> None:
    # 用户明确不保留旧授权数据。CASCADE 同时清理 API Key、Refresh Token、
    # 用户部门、全局角色和部门角色绑定，避免旧身份继续访问新 RBAC 主链路。
    op.execute("TRUNCATE TABLE users CASCADE")
    op.drop_column("users", "permissions_json")
    op.drop_column("users", "role")

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("risk_level", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.String),
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(permissions, list(NEW_PERMISSIONS))
    op.bulk_insert(roles, list(NEW_ROLES))
    op.bulk_insert(role_permissions, list(NEW_ROLE_PERMISSIONS))


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE id IN "
        "('rp_admin_knowledge_read_all', 'rp_admin_gitlab_source_manage', "
        "'rp_admin_gitlab_change_read_all', 'rp_global_reader_read_all', "
        "'rp_agent_operator_calculator', 'rp_agent_operator_web_search', "
        "'rp_agent_operator_mcp', 'rp_gitlab_manager_source', "
        "'rp_gitlab_manager_change')"
    )
    op.execute(
        "DELETE FROM roles WHERE id IN "
        "('role_knowledge_global_reader', 'role_agent_tool_operator', "
        "'role_gitlab_manager')"
    )
    op.execute(
        "DELETE FROM permissions WHERE id IN "
        "('perm_knowledge_read_all', 'perm_gitlab_source_manage', "
        "'perm_gitlab_change_read_all')"
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "permissions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
