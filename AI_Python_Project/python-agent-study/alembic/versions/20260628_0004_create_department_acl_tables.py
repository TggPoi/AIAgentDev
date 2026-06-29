"""create department ACL tables

Revision ID: 20260628_0004
Revises: 20260626_0003
Create Date: 2026-06-28 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0004"
down_revision: str | None = "20260626_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "user_departments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("department_code", sa.String(length=64), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["department_code"], ["departments.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "department_code",
            name="uq_user_departments_user_department",
        ),
    )
    op.create_index(
        "idx_user_departments_user_id",
        "user_departments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_user_departments_department_code",
        "user_departments",
        ["department_code"],
        unique=False,
    )

    departments = sa.table(
        "departments",
        sa.column("id", sa.String),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        departments,
        [
            {
                "id": "dept_art",
                "code": "art",
                "name": "美术部门",
                "description": "角色设定、场景资源、视觉风格等美术知识库权限范围",
            },
            {
                "id": "dept_product_planning",
                "code": "product_planning",
                "name": "产品策划部门",
                "description": "需求文档、玩法设计、数值规则和版本规划权限范围",
            },
            {
                "id": "dept_development",
                "code": "development",
                "name": "开发部门",
                "description": "技术方案、接口文档、部署文档和工程规范权限范围",
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_departments_department_code",
        table_name="user_departments",
    )
    op.drop_index("idx_user_departments_user_id", table_name="user_departments")
    op.drop_table("user_departments")
    op.drop_table("departments")
