"""create agent tool permission tables

Revision ID: 20260704_0005
Revises: 20260628_0004
Create Date: 2026-07-04 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0005"
down_revision: str | None = "20260628_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    {
        "id": "perm_knowledge_document_read",
        "code": "knowledge:document:read",
        "name": "读取知识库文档",
        "description": "允许检索、查看和引用授权范围内的知识库文档",
        "category": "knowledge_document",
        "risk_level": "low",
    },
    {
        "id": "perm_knowledge_document_update",
        "code": "knowledge:document:update",
        "name": "修改知识库文档",
        "description": "允许对授权部门内的已有知识库文档生成修改计划",
        "category": "knowledge_document",
        "risk_level": "high",
    },
    {
        "id": "perm_knowledge_document_create",
        "code": "knowledge:document:create",
        "name": "新增知识库文档",
        "description": "允许对授权部门内的知识库目录生成新增文档计划",
        "category": "knowledge_document",
        "risk_level": "medium",
    },
    {
        "id": "perm_knowledge_document_delete",
        "code": "knowledge:document:delete",
        "name": "删除知识库文档",
        "description": "允许对授权部门内的知识库文档生成删除计划",
        "category": "knowledge_document",
        "risk_level": "critical",
    },
    {
        "id": "perm_knowledge_document_approve",
        "code": "knowledge:document:approve",
        "name": "确认执行知识库文档计划",
        "description": "允许确认执行已生成的高风险文档管理计划",
        "category": "knowledge_document",
        "risk_level": "critical",
    },
    {
        "id": "perm_agent_tool_calculator",
        "code": "agent:tool:calculator",
        "name": "调用计算工具",
        "description": "允许调用本地安全计算工具",
        "category": "agent_tool",
        "risk_level": "low",
    },
    {
        "id": "perm_agent_tool_web_search",
        "code": "agent:tool:web_search",
        "name": "调用 Web Search 工具",
        "description": "允许调用外部网络搜索工具",
        "category": "agent_tool",
        "risk_level": "medium",
    },
    {
        "id": "perm_agent_tool_mcp",
        "code": "agent:tool:mcp",
        "name": "调用 MCP 工具",
        "description": "允许调用白名单内 MCP 工具",
        "category": "agent_tool",
        "risk_level": "high",
    },
]

ROLES = [
    {
        "id": "role_system_admin",
        "code": "system_admin",
        "name": "系统管理员",
        "description": "平台级管理员，默认拥有全部系统权限",
    },
    {
        "id": "role_department_reader",
        "code": "department_reader",
        "name": "部门只读成员",
        "description": "只能读取部门内可见文档",
    },
    {
        "id": "role_department_editor",
        "code": "department_editor",
        "name": "部门文档编辑者",
        "description": "可以读取和修改部门内已有文档",
    },
    {
        "id": "role_department_document_manager",
        "code": "department_document_manager",
        "name": "部门文档管理员",
        "description": "可以读取、新增、修改、删除部门内文档",
    },
]

ROLE_PERMISSION_CODES = {
    "role_system_admin": [item["id"] for item in PERMISSIONS],
    "role_department_reader": [
        "perm_knowledge_document_read",
    ],
    "role_department_editor": [
        "perm_knowledge_document_read",
        "perm_knowledge_document_update",
    ],
    "role_department_document_manager": [
        "perm_knowledge_document_read",
        "perm_knowledge_document_update",
        "perm_knowledge_document_create",
        "perm_knowledge_document_delete",
        "perm_knowledge_document_approve",
    ],
}


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("role_id", sa.String(length=64), nullable=False),
        sa.Column("permission_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )
    op.create_index("idx_role_permissions_role_id", "role_permissions", ["role_id"], unique=False)
    op.create_index("idx_role_permissions_permission_id", "role_permissions", ["permission_id"], unique=False)

    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("role_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )
    op.create_index("idx_user_roles_user_id", "user_roles", ["user_id"], unique=False)
    op.create_index("idx_user_roles_role_id", "user_roles", ["role_id"], unique=False)

    op.create_table(
        "user_department_roles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("department_code", sa.String(length=64), nullable=False),
        sa.Column("role_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["department_code"], ["departments.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "department_code",
            "role_id",
            name="uq_user_department_roles_user_department_role",
        ),
    )
    op.create_index("idx_user_department_roles_user_id", "user_department_roles", ["user_id"], unique=False)
    op.create_index(
        "idx_user_department_roles_department_code",
        "user_department_roles",
        ["department_code"],
        unique=False,
    )
    op.create_index("idx_user_department_roles_role_id", "user_department_roles", ["role_id"], unique=False)

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("risk_level", sa.String),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", sa.String),
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )

    op.bulk_insert(permissions, PERMISSIONS)
    op.bulk_insert(roles, ROLES)
    op.bulk_insert(
        role_permissions,
        [
            {
                "id": f"rp_{role_id.replace('role_', '')}_{permission_id.replace('perm_', '')}",
                "role_id": role_id,
                "permission_id": permission_id,
            }
            for role_id, permission_ids in ROLE_PERMISSION_CODES.items()
            for permission_id in permission_ids
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_user_department_roles_role_id", table_name="user_department_roles")
    op.drop_index("idx_user_department_roles_department_code", table_name="user_department_roles")
    op.drop_index("idx_user_department_roles_user_id", table_name="user_department_roles")
    op.drop_table("user_department_roles")
    op.drop_index("idx_user_roles_role_id", table_name="user_roles")
    op.drop_index("idx_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("idx_role_permissions_permission_id", table_name="role_permissions")
    op.drop_index("idx_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
