"""真实 PostgreSQL Dataset、COMMENT、RLS 和连接池 Scope 隔离验收。"""

from __future__ import annotations

import asyncio
import json
import os

import asyncpg


async def scoped_count(
    pool: asyncpg.Pool,
    view: str,
    scope: str | None,
) -> int:
    async with pool.acquire() as connection:
        async with connection.transaction(readonly=True):
            if scope is not None:
                await connection.fetchval(
                    "SELECT set_config('app.scope_ids', $1, true)", scope
                )
            return await connection.fetchval(f"SELECT count(*) FROM {view}")


async def main() -> None:
    urls = json.loads(os.environ["NL2SQL_DATABASE_URLS_JSON"])
    real_pool = await asyncpg.create_pool(urls["real_estate_test"], min_size=1, max_size=2)
    game_pool = await asyncpg.create_pool(urls["game_test"], min_size=1, max_size=2)
    try:
        assert await scoped_count(real_pool, "analytics.unit_inventory", None) == 0
        assert await scoped_count(real_pool, "analytics.unit_inventory", "re_p1") == 24
        assert await scoped_count(real_pool, "analytics.unit_inventory", "re_p2") == 24
        assert await scoped_count(real_pool, "analytics.unit_inventory", "*") == 72
        assert await scoped_count(game_pool, "analytics.asset_catalog", None) == 0
        assert await scoped_count(game_pool, "analytics.asset_catalog", "game_p1") == 15
        assert await scoped_count(game_pool, "analytics.asset_catalog", "game_p3") == 15
        assert await scoped_count(game_pool, "analytics.asset_catalog", "*") == 45

        # 同一个物理连接连续服务不同 Scope，事务级 set_config 不能串线。
        assert await scoped_count(game_pool, "analytics.asset_catalog", "game_p1") == 15
        assert await scoped_count(game_pool, "analytics.asset_catalog", None) == 0

        async with game_pool.acquire() as connection:
            role = await connection.fetchrow(
                """
                SELECT r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole
                FROM pg_catalog.pg_roles r
                WHERE r.rolname = current_user
                """
            )
            assert role == (False, False, False, False)
            comments = await connection.fetchval(
                """
                SELECT count(*)
                FROM information_schema.columns c
                JOIN pg_catalog.pg_namespace n ON n.nspname = c.table_schema
                JOIN pg_catalog.pg_class pc
                  ON pc.relnamespace=n.oid AND pc.relname=c.table_name
                WHERE c.table_schema='analytics'
                  AND pg_catalog.col_description(pc.oid, c.ordinal_position) IS NOT NULL
                """
            )
            assert comments >= 16
            async with connection.transaction(readonly=True):
                await connection.fetchval(
                    "SELECT set_config('app.scope_ids', '*', true)"
                )
                invalid = await connection.fetchval(
                    """
                    SELECT count(*) FROM analytics.asset_catalog
                    WHERE (category_name='3D模型') <> (polygon_count IS NOT NULL)
                    """
                )
            assert invalid == 0
            try:
                await connection.fetchval("SELECT count(*) FROM business.assets")
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("reader can resolve a non-whitelisted business table")
        async with game_pool.acquire() as connection:
            try:
                async with connection.transaction():
                    await connection.execute(
                        "CREATE TABLE analytics.nl2sql_forbidden_write(id integer)"
                    )
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("read-only role unexpectedly created a table")
    finally:
        await real_pool.close()
        await game_pool.close()
    print("NL2SQL real database checks passed")


if __name__ == "__main__":
    asyncio.run(main())
