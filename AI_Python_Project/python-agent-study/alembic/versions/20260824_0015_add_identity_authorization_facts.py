"""add identity and authorization fact tables

Revision ID: 20260824_0015
Revises: 20260815_0014
Create Date: 2026-08-24 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0015"
down_revision: str | None = "20260815_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_permission_grants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("permission_id", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_user_permission_grants_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_by_user_id IS NULL AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_by_user_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_user_permission_grants_revocation",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_permission_grants_user_status",
        "user_permission_grants",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_user_permission_grants_active",
        "user_permission_grants",
        ["user_id", "permission_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "document_access_grants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("grantee_user_id", sa.String(length=64), nullable=False),
        sa.Column("doc_id", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_document_access_grants_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_by_user_id IS NULL AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_by_user_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_document_access_grants_revocation",
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["gitlab_documents.doc_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_document_access_grants_grantee_status",
        "document_access_grants",
        ["grantee_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_document_access_grants_doc_status",
        "document_access_grants",
        ["doc_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_document_access_grants_active",
        "document_access_grants",
        ["grantee_user_id", "doc_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        """
        INSERT INTO roles (id, code, name, description, is_system)
        VALUES (
            'role_department_manager',
            'department_manager',
            '部门主管',
            '管理主归属部门普通员工、部门文档及本部门文档的跨部门读取授权。',
            true
        )
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT
            'rp_department_manager_' || replace(p.code, ':', '_'),
            r.id,
            p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'department_manager'
          AND p.code IN (
              'knowledge:document:read',
              'knowledge:document:create',
              'knowledge:document:update',
              'knowledge:document:delete',
              'knowledge:document:approve'
          )
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM user_department_roles
        WHERE role_id = (SELECT id FROM roles WHERE code = 'department_manager')
        """
    )
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id = (SELECT id FROM roles WHERE code = 'department_manager')
        """
    )
    op.execute("DELETE FROM roles WHERE code = 'department_manager'")
    op.drop_index(
        "uq_document_access_grants_active",
        table_name="document_access_grants",
    )
    op.drop_index(
        "idx_document_access_grants_doc_status",
        table_name="document_access_grants",
    )
    op.drop_index(
        "idx_document_access_grants_grantee_status",
        table_name="document_access_grants",
    )
    op.drop_table("document_access_grants")
    op.drop_index(
        "uq_user_permission_grants_active",
        table_name="user_permission_grants",
    )
    op.drop_index(
        "idx_user_permission_grants_user_status",
        table_name="user_permission_grants",
    )
    op.drop_table("user_permission_grants")
