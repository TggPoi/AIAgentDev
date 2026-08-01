"""用真实外部 SQL 模型和两个真实 PostgreSQL Dataset 执行最小验收。"""

from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import select

from fast_app.core.config import get_settings
from fast_app.db.nl2sql_tables import Nl2SqlQueryAuditTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.service import Nl2SqlService


async def main() -> None:
    settings = get_settings().model_copy(
        update={
            "nl2sql_enabled": True,
            "nl2sql_database_urls_json": os.environ["NL2SQL_DATABASE_URLS_JSON"],
        }
    )
    registry = DatasetRegistry(settings)
    engine = create_database_engine(settings)
    sessions = create_session_factory(engine)
    admin = CurrentUserContext(
        user_id="nl2sql_real_acceptance",
        is_authenticated=True,
        auth_source="jwt",
        global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
        global_permission_codes=[
            PermissionCode.DATA_QUERY_EXECUTE.value,
            PermissionCode.AGENT_TOOL_CALCULATOR.value,
        ],
    )
    try:
        async with sessions() as session:
            await registry.refresh(session)
            service = Nl2SqlService(settings, registry, session)
            game = await service.query(
                user=admin,
                dataset_id="game_test",
                question=(
                    "列出星港远征中已授权的3D模型资产名称、费用、模型面数、"
                    "类别和应用场景，按费用从高到低排序。"
                ),
                max_rows=20,
            )
            assert game.rows
            assert {
                "asset_name",
                "cost_yuan",
                "polygon_count",
                "category_name",
                "usage_scenario",
            }.issubset(game.columns)
            assert all(row["category_name"] == "3D模型" for row in game.rows)

            real_estate = await service.query(
                user=admin,
                dataset_id="real_estate_test",
                question="查询云栖雅苑价格低于2500000元的可售房源，列出楼栋、户型、面积和总价。",
                max_rows=20,
            )
            assert all(
                decimal_like(row["total_price_yuan"]) < 2_500_000
                for row in real_estate.rows
            )
            audit = await session.scalar(
                select(Nl2SqlQueryAuditTable).where(
                    Nl2SqlQueryAuditTable.query_id == real_estate.query_id
                )
            )
            assert audit is not None
            for sentinel in ("云栖雅苑", "2500000"):
                assert sentinel not in audit.tokenized_question
                assert sentinel not in audit.parameterized_sql
            print(
                json.dumps(
                    {
                        "game": {
                            "query_id": game.query_id,
                            "row_count": game.row_count,
                            "attempt_count": game.attempt_count,
                        },
                        "real_estate": {
                            "query_id": real_estate.query_id,
                            "row_count": real_estate.row_count,
                            "attempt_count": real_estate.attempt_count,
                            "audit_sentinel_leaks": 0,
                        },
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await registry.close()
        await engine.dispose()


def decimal_like(value: object) -> float:
    return float(str(value))


if __name__ == "__main__":
    asyncio.run(main())
