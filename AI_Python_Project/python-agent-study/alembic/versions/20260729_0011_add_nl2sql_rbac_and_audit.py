"""add NL2SQL RBAC, Dataset grants and safe audits

Revision ID: 20260729_0011
Revises: 20260729_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260729_0011"
down_revision = "20260729_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nl2sql_dataset_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_key", sa.String(128), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('user', 'role', 'department')",
            name="ck_nl2sql_dataset_grants_subject_type",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "subject_type",
            "subject_key",
            "scope_id",
            name="uq_nl2sql_dataset_grant_subject_scope",
        ),
    )
    op.create_index(
        "idx_nl2sql_dataset_grants_lookup",
        "nl2sql_dataset_grants",
        ["dataset_id", "enabled"],
    )
    op.create_table(
        "nl2sql_query_audits",
        sa.Column("query_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("tokenized_question", sa.Text(), nullable=False),
        sa.Column("parameterized_sql", sa.Text(), nullable=False),
        sa.Column("sql_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("execution_ms", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_nl2sql_query_audits_user_created",
        "nl2sql_query_audits",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_nl2sql_query_audits_dataset_created",
        "nl2sql_query_audits",
        ["dataset_id", "created_at"],
    )

    op.execute(
        """
        INSERT INTO permissions (id, code, name, description, category, risk_level, is_system)
        VALUES (
            'perm_data_query_execute',
            'data:query:execute',
            '执行结构化数据查询',
            '允许通过受控 NL2SQL 服务查询已授权 Dataset；项目范围仍由 Dataset Grant 与 RLS 限制。',
            'data',
            'medium',
            true
        )
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            risk_level = EXCLUDED.risk_level
        """
    )
    op.execute(
        """
        INSERT INTO roles (id, code, name, description, is_system)
        VALUES (
            'role_data_analyst',
            'data_analyst',
            '数据分析员',
            '可以执行 NL2SQL；可访问 Dataset 和项目范围由 Dataset Grant 单独授予。',
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
            'rp_' || r.code || '_data_query_execute',
            r.id,
            p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code IN ('system_admin', 'data_analyst')
          AND p.code = 'data:query:execute'
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id = (
            SELECT id FROM permissions WHERE code = 'data:query:execute'
        )
        """
    )
    op.execute("DELETE FROM roles WHERE code = 'data_analyst'")
    op.execute("DELETE FROM permissions WHERE code = 'data:query:execute'")
    op.drop_index("idx_nl2sql_query_audits_dataset_created", table_name="nl2sql_query_audits")
    op.drop_index("idx_nl2sql_query_audits_user_created", table_name="nl2sql_query_audits")
    op.drop_table("nl2sql_query_audits")
    op.drop_index("idx_nl2sql_dataset_grants_lookup", table_name="nl2sql_dataset_grants")
    op.drop_table("nl2sql_dataset_grants")
