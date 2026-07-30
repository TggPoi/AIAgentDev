from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from fast_app.core.config import get_settings
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.exceptions import (
    AppServiceError,
    Nl2SqlRepairableSqlError,
    Nl2SqlUnsafeSqlError,
)
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.models import (
    DatasetAuthorization,
    DatasetDefinition,
    SqlGenerationResult,
)
from fast_app.services.nl2sql.service import (
    Nl2SqlService,
    _fill_sensitive_summary,
    _serialize_records,
)
from fast_app.services.nl2sql.sql_policy import SqlPolicy, ValidatedSql


def expect_unsafe(sql: str) -> None:
    try:
        SqlPolicy().validate(
            sql,
            allowed_views=("analytics.asset_catalog",),
            max_rows=20,
            parameters={},
        )
    except Nl2SqlUnsafeSqlError:
        return
    raise AssertionError(f"expected unsafe SQL: {sql}")


class FakeSensitiveConnection:
    scope = ""

    class Transaction:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: object) -> None:
            return None

    def transaction(self, *, readonly: bool) -> Transaction:
        assert readonly
        return self.Transaction()

    async def fetchval(self, _: str, scope: str) -> None:
        self.scope = scope

    async def fetch(self, _: str) -> list[dict[str, object]]:
        return [
            {
                "project_name": "跨范围哨兵楼盘",
                "building_name": "1号楼",
                "address": "哨兵路1号",
                "project_id": "re_other",
                "business_code": "RE-OTHER",
                "unit_no": "101",
                "unit_type_name": "三居",
                "orientation": "南",
                "inventory_status": "可售",
            }
        ]


async def check_cross_scope_tokenization() -> None:
    connection = FakeSensitiveConnection()
    tokenized, vault = await Nl2SqlService._tokenize_sensitive_question(
        object.__new__(Nl2SqlService),
        connection=connection,  # type: ignore[arg-type]
        dataset=object(),  # type: ignore[arg-type]
        authorization=DatasetAuthorization(
            dataset_id="real_estate_test",
            scope_ids=("re_allowed",),
        ),
        question="查询跨范围哨兵楼盘的可售房源",
    )
    assert connection.scope == "*"
    assert "跨范围哨兵楼盘" not in tokenized
    assert "可售" not in tokenized
    assert "跨范围哨兵楼盘" in vault.values()


class FakeAcquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None


class FakePool:
    def acquire(self) -> FakeAcquire:
        return FakeAcquire()


class FakeRegistry:
    async def pool(self, _: DatasetDefinition) -> FakePool:
        return FakePool()


class FakeCatalog:
    async def load(self, *_: object, **__: object) -> str:
        return "catalog"


class FakeSession:
    def add(self, _: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class OneRepairService(Nl2SqlService):
    generate_calls = 0
    execute_calls = 0

    async def authorize_action(self, **_: object) -> tuple[DatasetDefinition, DatasetAuthorization]:
        return (
            DatasetDefinition(
                dataset_id="game_test",
                name="游戏",
                domain="game",
                database_key="game_test",
                privacy_classification="non_sensitive",
                scope_column="project_id",
                allowed_views=("analytics.asset_catalog",),
                report_supported=True,
                enabled=True,
            ),
            DatasetAuthorization(dataset_id="game_test", scope_ids=("*",)),
        )

    async def _generate_sql(self, **_: object) -> SqlGenerationResult:
        self.generate_calls += 1
        return SqlGenerationResult(
            parameterized_sql="SELECT asset_name FROM analytics.asset_catalog",
            parameters={},
        )

    async def _execute_generation(self, **_: object) -> tuple[ValidatedSql, list[dict[str, str]], int]:
        self.execute_calls += 1
        if self.execute_calls == 1:
            raise Nl2SqlRepairableSqlError("repairable")
        return (
            ValidatedSql(
                parameterized_sql="SELECT asset_name FROM analytics.asset_catalog LIMIT 2",
                asyncpg_sql="SELECT asset_name FROM analytics.asset_catalog LIMIT 2",
                parameter_order=(),
            ),
            [{"asset_name": "资产A"}],
            1,
        )

    async def _summarize_game_result(self, **_: object) -> str:
        return "ok"


async def check_one_repair_only() -> None:
    service = object.__new__(OneRepairService)
    service._settings = type("Settings", (), {"nl2sql_default_max_rows": 200})()
    service._registry = FakeRegistry()
    service._catalog = FakeCatalog()
    service._session = FakeSession()
    result = await service._query_impl(
        user=type("User", (), {"user_id": "test"})(),
        dataset_id="game_test",
        question="查询资产",
    )
    assert result.attempt_count == 2
    assert service.generate_calls == 2
    assert service.execute_calls == 2


def main() -> None:
    policy = SqlPolicy()
    validated = policy.validate(
        """
        WITH licensed AS (
            SELECT project_id, cost_yuan
            FROM analytics.asset_catalog
            WHERE license_status = :status
        )
        SELECT project_id, SUM(cost_yuan) AS total_cost
        FROM licensed GROUP BY project_id ORDER BY total_cost DESC
        """,
        allowed_views=("analytics.asset_catalog",),
        max_rows=20,
        parameters={"status": "已授权"},
    )
    assert validated.asyncpg_sql.count("$1") == 1
    assert validated.parameterized_sql.endswith("LIMIT 21")
    parameterized_limit = policy.validate(
        "SELECT asset_name FROM analytics.asset_catalog LIMIT :limit_rows",
        allowed_views=("analytics.asset_catalog",),
        max_rows=20,
        parameters={"limit_rows": 5},
    )
    assert parameterized_limit.asyncpg_sql.endswith("LIMIT $1")
    expect_unsafe("SELECT * FROM analytics.asset_catalog")
    expect_unsafe("DELETE FROM analytics.asset_catalog")
    expect_unsafe("SELECT asset_name FROM pg_catalog.pg_class")
    expect_unsafe("SELECT pg_sleep(1) FROM analytics.asset_catalog")
    expect_unsafe(
        "SELECT current_setting('app.scope_ids') FROM analytics.asset_catalog"
    )
    expect_unsafe(
        "SELECT set_config('app.scope_ids', '*', true) FROM analytics.asset_catalog"
    )
    expect_unsafe(
        "SELECT asset_name FROM analytics.asset_catalog; SELECT asset_name FROM analytics.asset_catalog"
    )

    RagChatRequest(query="资产费用", dataset_id="game_test", nl2sql_action="query")
    for payload in (
        {"query": "x", "dataset_id": "game_test"},
        {"query": "x", "nl2sql_action": "query"},
    ):
        try:
            RagChatRequest.model_validate(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid request accepted: {payload}")

    summary = _fill_sensitive_summary(
        "__ENTITY_1__共有 {row_count} 套，截断：{truncated}",
        vault={"__ENTITY_1__": "哨兵楼盘"},
        row_count=3,
        truncated=False,
    )
    assert summary == "哨兵楼盘共有 3 套，截断：否"
    assert "9999999" not in _fill_sensitive_summary(
        "{unknown}",
        vault={"__VALUE_1__": 9999999},
        row_count=1,
        truncated=False,
    )
    rows, warnings = _serialize_records(
        [
            {
                "money": Decimal("123.40"),
                "created_at": datetime(2026, 7, 29, tzinfo=timezone.utc),
                "long_text": "x" * 2001,
            }
        ]
    )
    assert rows[0]["money"] == "123.40"
    assert rows[0]["created_at"] == "2026-07-29T00:00:00+00:00"
    assert len(rows[0]["long_text"]) == 2000
    assert warnings

    settings = get_settings()
    try:
        DatasetRegistry(
            settings.model_copy(
                update={
                    "nl2sql_database_urls_json": (
                        '{"forbidden":"postgresql://reader:secret@127.0.0.1/'
                        + settings.database_url.rsplit("/", 1)[-1]
                        + '"}'
                    )
                }
            )
        )
    except AppServiceError:
        pass
    else:
        raise AssertionError("platform database accepted as NL2SQL Dataset")
    asyncio.run(check_cross_scope_tokenization())
    asyncio.run(check_one_repair_only())
    print("NL2SQL module checks passed")


if __name__ == "__main__":
    main()
