from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlsplit

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings
from fast_app.db.nl2sql_tables import Nl2SqlDatasetTable
from fast_app.services.exceptions import AppServiceError
from fast_app.services.nl2sql.models import DatasetDefinition


def _asyncpg_url(url: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


class DatasetRegistry:
    """平台数据库驱动的 Dataset 目录和对应只读连接池。

    DatasetDefinition 是服务端可信配置：数据库连接、隐私等级、白名单视图和
    Scope 字段不会交给模型选择。连接 URL 只从部署环境读取，对外只暴露 dataset_id。
    """

    def __init__(
        self,
        settings: Settings,
        datasets: Iterable[DatasetDefinition] = (),
    ) -> None:
        self._settings = settings
        try:
            urls = json.loads(settings.nl2sql_database_urls_json)
        except json.JSONDecodeError as exc:
            raise AppServiceError("NL2SQL_DATABASE_URLS_JSON 不是合法 JSON") from exc
        if not isinstance(urls, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in urls.items()
        ):
            raise AppServiceError("NL2SQL_DATABASE_URLS_JSON 必须是字符串到字符串的映射")
        main_database = urlsplit(_asyncpg_url(settings.database_url)).path.lstrip("/")
        # 即使运维误把平台连接写进 Dataset 映射，也在启动阶段拒绝。自由 SQL
        # 永远不能触达保存用户、权限、TaskPlan 和审计记录的 python_agent_study。
        if any(
            urlsplit(_asyncpg_url(url)).path.lstrip("/") == main_database
            for url in urls.values()
        ):
            raise AppServiceError("平台主库禁止注册为 NL2SQL Dataset")
        self._urls: dict[str, str] = urls
        self._pools: dict[str, asyncpg.Pool] = {}
        self._datasets = {item.dataset_id: item for item in datasets}

    async def refresh(self, session: AsyncSession) -> None:
        """从平台主库加载可信 Dataset 配置；连接凭证不存入该表。"""

        rows = (
            await session.scalars(
                select(Nl2SqlDatasetTable).order_by(Nl2SqlDatasetTable.dataset_id)
            )
        ).all()
        self._datasets = {
            row.dataset_id: DatasetDefinition(
                dataset_id=row.dataset_id,
                name=row.name,
                domain=row.domain,
                database_key=row.database_key,
                privacy_classification=row.privacy_classification,
                scope_column=row.scope_column,
                allowed_views=tuple(row.allowed_views),
                logical_view_mapping=dict(row.logical_view_mapping),
                entity_tokenization_rules=tuple(row.entity_tokenization_rules),
                relationships=tuple(row.relationships),
                synonyms={
                    key: tuple(values) for key, values in row.synonyms.items()
                },
                report_supported=row.report_supported,
                enabled=self._settings.nl2sql_enabled and row.enabled,
            )
            for row in rows
        }

    def get(self, dataset_id: str) -> DatasetDefinition:
        dataset = self._datasets.get(dataset_id)
        if dataset is None or not dataset.enabled:
            raise AppServiceError("Dataset 不存在或未启用")
        if dataset.database_key not in self._urls:
            raise AppServiceError("Dataset 的只读数据库连接尚未配置")
        return dataset

    def enabled(self) -> list[DatasetDefinition]:
        return [
            item
            for item in self._datasets.values()
            if item.enabled and item.database_key in self._urls
        ]

    async def pool(self, dataset: DatasetDefinition) -> asyncpg.Pool:
        """按 database_key 复用业务库连接池；池中连接只使用专用只读账号。"""

        pool = self._pools.get(dataset.database_key)
        if pool is None:
            pool = await asyncpg.create_pool(
                dsn=_asyncpg_url(self._urls[dataset.database_key]),
                min_size=1,
                max_size=max(2, self._settings.database_pool_size),
                command_timeout=self._settings.nl2sql_model_timeout_seconds,
            )
            self._pools[dataset.database_key] = pool
        return pool

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()

    def safe_database_name(self, dataset: DatasetDefinition) -> str:
        """只供本地诊断使用，绝不返回主机、用户或密码。"""

        return urlsplit(_asyncpg_url(self._urls[dataset.database_key])).path.lstrip("/")


__all__ = ["DatasetRegistry"]
