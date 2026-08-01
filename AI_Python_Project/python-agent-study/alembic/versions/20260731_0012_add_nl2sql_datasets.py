"""store NL2SQL Dataset definitions in the platform database

Revision ID: 20260731_0012
Revises: 20260729_0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260731_0012"
down_revision = "20260729_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nl2sql_datasets",
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(128), nullable=False),
        sa.Column("database_key", sa.String(128), nullable=False, unique=True),
        sa.Column("privacy_classification", sa.String(32), nullable=False),
        sa.Column("scope_column", sa.String(128), nullable=False),
        sa.Column("allowed_views", postgresql.JSONB(), nullable=False),
        sa.Column("logical_view_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("entity_tokenization_rules", postgresql.JSONB(), nullable=False),
        sa.Column("relationships", postgresql.JSONB(), nullable=False),
        sa.Column("synonyms", postgresql.JSONB(), nullable=False),
        sa.Column("report_supported", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "privacy_classification IN ('sensitive', 'non_sensitive')",
            name="ck_nl2sql_datasets_privacy_classification",
        ),
    )

    datasets = sa.table(
        "nl2sql_datasets",
        sa.column("dataset_id", sa.String),
        sa.column("name", sa.String),
        sa.column("domain", sa.String),
        sa.column("database_key", sa.String),
        sa.column("privacy_classification", sa.String),
        sa.column("scope_column", sa.String),
        sa.column("allowed_views", postgresql.JSONB),
        sa.column("logical_view_mapping", postgresql.JSONB),
        sa.column("entity_tokenization_rules", postgresql.JSONB),
        sa.column("relationships", postgresql.JSONB),
        sa.column("synonyms", postgresql.JSONB),
        sa.column("report_supported", sa.Boolean),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(
        datasets,
        [
            {
                "dataset_id": "real_estate_test",
                "name": "房地产数字孪生测试数据",
                "domain": "real_estate",
                "database_key": "real_estate_test",
                "privacy_classification": "sensitive",
                "scope_column": "project_id",
                "allowed_views": [
                    "analytics.unit_inventory",
                    "analytics.project_inventory_summary",
                ],
                "logical_view_mapping": {
                    "unit_inventory": "analytics.unit_inventory",
                    "project_inventory_summary": "analytics.project_inventory_summary",
                },
                "entity_tokenization_rules": [
                    "project_name",
                    "building_name",
                    "address",
                    "business_code",
                ],
                "relationships": [
                    "unit_inventory.project_id = project_inventory_summary.project_id"
                ],
                "synonyms": {
                    "project_name": ["楼盘", "项目"],
                    "total_price_yuan": ["总价", "价格"],
                    "inventory_status": ["库存状态", "销售状态"],
                },
                "report_supported": False,
                "enabled": True,
            },
            {
                "dataset_id": "game_test",
                "name": "游戏开发资产测试数据",
                "domain": "game",
                "database_key": "game_test",
                "privacy_classification": "non_sensitive",
                "scope_column": "project_id",
                "allowed_views": [
                    "analytics.asset_catalog",
                    "analytics.project_asset_summary",
                ],
                "logical_view_mapping": {
                    "asset_catalog": "analytics.asset_catalog",
                    "project_asset_summary": "analytics.project_asset_summary",
                },
                "entity_tokenization_rules": [],
                "relationships": [
                    "asset_catalog.project_id = project_asset_summary.project_id"
                ],
                "synonyms": {
                    "asset_name": ["资产", "素材"],
                    "cost_yuan": ["费用", "成本"],
                    "polygon_count": ["模型面数", "面数"],
                },
                "report_supported": True,
                "enabled": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("nl2sql_datasets")
