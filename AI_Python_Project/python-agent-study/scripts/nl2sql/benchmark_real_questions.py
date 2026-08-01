"""每个 Dataset 20 个真实模型/真实 PostgreSQL 问题的可执行率与正确率基准。"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fast_app.core.config import get_settings
from fast_app.domain.agent_tool_permissions import PermissionCode, RoleCode
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.service import Nl2SqlService, _serialize_records


@dataclass(frozen=True)
class Case:
    question: str
    expected_sql: str


GAME_CASES = (
    Case("列出星港远征全部资产的资产名称、费用、类别和应用场景。", "SELECT asset_name, cost_yuan, category_name, usage_scenario FROM analytics.asset_catalog WHERE project_name='星港远征'"),
    Case("列出山海旅人所有已授权资产的资产名称和授权状态。", "SELECT asset_name, license_status FROM analytics.asset_catalog WHERE project_name='山海旅人' AND license_status='已授权'"),
    Case("列出极速街区的3D模型资产名称和模型面数。", "SELECT asset_name, polygon_count FROM analytics.asset_catalog WHERE project_name='极速街区' AND category_name='3D模型'"),
    Case("统计星港远征每个资产类别的资产数量和总费用。", "SELECT category_name, count(*) AS asset_count, sum(cost_yuan) AS total_cost_yuan FROM analytics.asset_catalog WHERE project_name='星港远征' GROUP BY category_name"),
    Case("统计星港远征全部资产的总费用。", "SELECT sum(cost_yuan) AS total_cost_yuan FROM analytics.asset_catalog WHERE project_name='星港远征'"),
    Case("计算山海旅人全部资产的平均费用。", "SELECT round(avg(cost_yuan),2) AS average_cost_yuan FROM analytics.asset_catalog WHERE project_name='山海旅人'"),
    Case("列出全部项目费用最高的5个资产名称、项目名称和费用。", "SELECT asset_name, project_name, cost_yuan FROM analytics.asset_catalog ORDER BY cost_yuan DESC LIMIT 5"),
    Case("列出全部已授权3D模型的资产名称、项目名称、费用和模型面数。", "SELECT asset_name, project_name, cost_yuan, polygon_count FROM analytics.asset_catalog WHERE license_status='已授权' AND category_name='3D模型'"),
    Case("按项目统计待确认资产数量。", "SELECT project_name, count(*) AS asset_count FROM analytics.asset_catalog WHERE license_status='待确认' GROUP BY project_name"),
    Case("列出用于主城展示的资产名称、项目名称、类别和费用。", "SELECT asset_name, project_name, category_name, cost_yuan FROM analytics.asset_catalog WHERE usage_scenario='主城展示'"),
    Case("计算星港远征3D模型的平均模型面数。", "SELECT round(avg(polygon_count),0) AS average_polygon_count FROM analytics.asset_catalog WHERE project_name='星港远征' AND category_name='3D模型'"),
    Case("查询星港远征资产的最低费用和最高费用。", "SELECT min(cost_yuan) AS minimum_cost_yuan, max(cost_yuan) AS maximum_cost_yuan FROM analytics.asset_catalog WHERE project_name='星港远征'"),
    Case("列出山海旅人费用低于7000元的资产名称、费用和类别。", "SELECT asset_name, cost_yuan, category_name FROM analytics.asset_catalog WHERE project_name='山海旅人' AND cost_yuan < 7000"),
    Case("按类别统计仅内部使用资产的数量。", "SELECT category_name, count(*) AS asset_count FROM analytics.asset_catalog WHERE license_status='仅内部使用' GROUP BY category_name"),
    Case("列出极速街区的UI组件资产名称、费用和应用场景。", "SELECT asset_name, cost_yuan, usage_scenario FROM analytics.asset_catalog WHERE project_name='极速街区' AND category_name='UI组件'"),
    Case("按项目统计资产总数和总费用。", "SELECT project_name, count(*) AS asset_count, sum(cost_yuan) AS total_cost_yuan FROM analytics.asset_catalog GROUP BY project_name"),
    Case("统计星港远征已授权资产的总费用。", "SELECT sum(cost_yuan) AS total_cost_yuan FROM analytics.asset_catalog WHERE project_name='星港远征' AND license_status='已授权'"),
    Case("列出模型面数大于20000的资产名称、项目名称和模型面数。", "SELECT asset_name, project_name, polygon_count FROM analytics.asset_catalog WHERE polygon_count > 20000"),
    Case("按授权状态统计山海旅人的资产数量。", "SELECT license_status, count(*) AS asset_count FROM analytics.asset_catalog WHERE project_name='山海旅人' GROUP BY license_status"),
    Case("列出星港远征每个资产的名称、类别、费用以及该类别的项目总费用。", "SELECT a.asset_name, a.category_name, a.cost_yuan, s.total_cost_yuan FROM analytics.asset_catalog a JOIN analytics.project_asset_summary s ON a.project_id=s.project_id AND a.category_name=s.category_name WHERE a.project_name='星港远征'"),
)

REAL_ESTATE_CASES = (
    Case("列出云栖雅苑全部可售房源的楼栋、房号、户型、面积和总价。", "SELECT building_name, unit_no, unit_type_name, area_sqm, total_price_yuan FROM analytics.unit_inventory WHERE project_name='云栖雅苑' AND inventory_status='可售'"),
    Case("统计湖畔新城每种库存状态的房源数量。", "SELECT inventory_status, count(*) AS unit_count FROM analytics.unit_inventory WHERE project_name='湖畔新城' GROUP BY inventory_status"),
    Case("列出中央公园府面积大于100平方米的房源楼栋、房号、面积和总价。", "SELECT building_name, unit_no, area_sqm, total_price_yuan FROM analytics.unit_inventory WHERE project_name='中央公园府' AND area_sqm > 100"),
    Case("计算云栖雅苑可售房源的平均总价。", "SELECT round(avg(total_price_yuan),2) AS average_total_price_yuan FROM analytics.unit_inventory WHERE project_name='云栖雅苑' AND inventory_status='可售'"),
    Case("查询湖畔新城房源的最低总价和最高总价。", "SELECT min(total_price_yuan) AS minimum_total_price_yuan, max(total_price_yuan) AS maximum_total_price_yuan FROM analytics.unit_inventory WHERE project_name='湖畔新城'"),
    Case("按楼盘统计全部可售房源数量。", "SELECT project_name, count(*) AS unit_count FROM analytics.unit_inventory WHERE inventory_status='可售' GROUP BY project_name"),
    Case("列出总价低于2000000元的可售房源楼盘、楼栋、房号和总价。", "SELECT project_name, building_name, unit_no, total_price_yuan FROM analytics.unit_inventory WHERE inventory_status='可售' AND total_price_yuan < 2000000"),
    Case("列出云栖雅苑所有三居户型房源的楼栋、户型、面积和库存状态。", "SELECT building_name, unit_type_name, area_sqm, inventory_status FROM analytics.unit_inventory WHERE project_name='云栖雅苑' AND room_count=3"),
    Case("按朝向统计中央公园府的房源数量。", "SELECT orientation, count(*) AS unit_count FROM analytics.unit_inventory WHERE project_name='中央公园府' GROUP BY orientation"),
    Case("列出全部南向且面积大于120平方米的房源楼盘、楼栋、户型和面积。", "SELECT project_name, building_name, unit_type_name, area_sqm FROM analytics.unit_inventory WHERE orientation='南' AND area_sqm > 120"),
    Case("统计三个楼盘的房源总数。", "SELECT count(*) AS unit_count FROM analytics.unit_inventory"),
    Case("按楼盘统计平均房源面积。", "SELECT project_name, round(avg(area_sqm),2) AS average_area_sqm FROM analytics.unit_inventory GROUP BY project_name"),
    Case("列出湖畔新城已认购房源的楼栋、房号、户型和总价。", "SELECT building_name, unit_no, unit_type_name, total_price_yuan FROM analytics.unit_inventory WHERE project_name='湖畔新城' AND inventory_status='已认购'"),
    Case("统计云栖雅苑两居房源数量。", "SELECT count(*) AS unit_count FROM analytics.unit_inventory WHERE project_name='云栖雅苑' AND room_count=2"),
    Case("列出全部价格最高的5套房源的楼盘、楼栋、房号和总价。", "SELECT project_name, building_name, unit_no, total_price_yuan FROM analytics.unit_inventory ORDER BY total_price_yuan DESC LIMIT 5"),
    Case("按户型统计中央公园府的房源数量和平均总价。", "SELECT unit_type_name, count(*) AS unit_count, round(avg(total_price_yuan),2) AS average_total_price_yuan FROM analytics.unit_inventory WHERE project_name='中央公园府' GROUP BY unit_type_name"),
    Case("列出云栖雅苑1号楼的房号、户型、面积和库存状态。", "SELECT unit_no, unit_type_name, area_sqm, inventory_status FROM analytics.unit_inventory WHERE project_name='云栖雅苑' AND building_name='1号楼'"),
    Case("统计全部已售房源的总价合计。", "SELECT sum(total_price_yuan) AS total_price_yuan FROM analytics.unit_inventory WHERE inventory_status='已售'"),
    Case("列出面积在90到130平方米之间的房源楼盘、户型、面积和总价。", "SELECT project_name, unit_type_name, area_sqm, total_price_yuan FROM analytics.unit_inventory WHERE area_sqm BETWEEN 90 AND 130"),
    Case("把云栖雅苑房源明细与楼盘库存汇总连接，列出房号、库存状态和该状态房源数量。", "SELECT u.unit_no, u.inventory_status, s.unit_count FROM analytics.unit_inventory u JOIN analytics.project_inventory_summary s ON u.project_id=s.project_id AND u.inventory_status=s.inventory_status WHERE u.project_name='云栖雅苑'"),
)


def canonical(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    """比较查询值而非模型自由选择的列别名，并统一无业务意义的小数尾差。"""

    def normalize(value: Any) -> str:
        if isinstance(value, bool) or value is None:
            return json.dumps(value, ensure_ascii=False)
        try:
            return f"number:{Decimal(str(value)).quantize(Decimal('0.01'))}"
        except (InvalidOperation, ValueError):
            return f"text:{value}"

    return sorted(tuple(normalize(value) for value in row.values()) for row in rows)


async def run_domain(
    *,
    service: Nl2SqlService,
    user: CurrentUserContext,
    pool: asyncpg.Pool,
    dataset_id: str,
    cases: tuple[Case, ...],
) -> dict[str, Any]:
    executable = 0
    correct = 0
    failures: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        try:
            result = await service.query(
                user=user,
                dataset_id=dataset_id,
                question=case.question,
                max_rows=200,
            )
            executable += 1
            async with pool.acquire() as connection:
                async with connection.transaction(readonly=True):
                    await connection.fetchval(
                        "SELECT set_config('app.scope_ids', '*', true)"
                    )
                    expected_records = await connection.fetch(case.expected_sql)
            expected, _ = _serialize_records(expected_records)
            if canonical(result.rows) == canonical(expected):
                correct += 1
            else:
                failures.append(
                    {
                        "case": index,
                        "kind": "incorrect",
                        "query_id": result.query_id,
                        "actual_rows": result.row_count,
                        "expected_rows": len(expected),
                    }
                )
        except Exception as exc:
            failures.append(
                {"case": index, "kind": "not_executable", "error": type(exc).__name__}
            )
    return {
        "total": len(cases),
        "executable": executable,
        "correct": correct,
        "executable_rate": executable / len(cases),
        "correct_rate": correct / len(cases),
        "failures": failures,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        choices=("all", "game", "real_estate"),
        default="all",
    )
    args = parser.parse_args()
    urls = json.loads(os.environ["NL2SQL_DATABASE_URLS_JSON"])
    settings = get_settings().model_copy(
        update={
            "nl2sql_enabled": True,
            "nl2sql_database_urls_json": os.environ["NL2SQL_DATABASE_URLS_JSON"],
        }
    )
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    registry = DatasetRegistry(settings)
    game_pool = await asyncpg.create_pool(urls["game_test"], min_size=1, max_size=2)
    real_pool = await asyncpg.create_pool(urls["real_estate_test"], min_size=1, max_size=2)
    user = CurrentUserContext(
        user_id="nl2sql_benchmark",
        is_authenticated=True,
        auth_source="jwt",
        global_role_codes=[RoleCode.SYSTEM_ADMIN.value],
        global_permission_codes=[PermissionCode.DATA_QUERY_EXECUTE.value],
    )
    try:
        async with sessions() as session:
            await registry.refresh(session)
            service = Nl2SqlService(settings, registry, session)
            game = (
                await run_domain(
                    service=service,
                    user=user,
                    pool=game_pool,
                    dataset_id="game_test",
                    cases=GAME_CASES,
                )
                if args.domain in {"all", "game"}
                else None
            )
            real_estate = (
                await run_domain(
                    service=service,
                    user=user,
                    pool=real_pool,
                    dataset_id="real_estate_test",
                    cases=REAL_ESTATE_CASES,
                )
                if args.domain in {"all", "real_estate"}
                else None
            )
    finally:
        await game_pool.close()
        await real_pool.close()
        await registry.close()
        await engine.dispose()
    output = {"game": game, "real_estate": real_estate}
    print(json.dumps(output, ensure_ascii=False))
    if game is not None:
        assert game["executable_rate"] >= 0.90
        assert game["correct_rate"] >= 0.85
    if real_estate is not None:
        assert real_estate["executable_rate"] >= 0.90
        assert real_estate["correct_rate"] >= 0.85


if __name__ == "__main__":
    asyncio.run(main())
