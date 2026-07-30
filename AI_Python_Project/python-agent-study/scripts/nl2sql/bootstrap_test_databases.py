"""创建两个专用 PostgreSQL 测试 Database，并执行可重复的真实种子 SQL。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg

from fast_app.core.config import get_settings


ROOT = Path(__file__).resolve().parents[2]
DATABASES = (
    (
        "nl2sql_real_estate_test",
        "nl2sql_real_estate_owner",
        "NL2SQL_REAL_ESTATE_OWNER_PASSWORD",
        "nl2sql_real_estate_reader",
        "NL2SQL_REAL_ESTATE_READER_PASSWORD",
        "real_estate.sql",
    ),
    (
        "nl2sql_game_test",
        "nl2sql_game_owner",
        "NL2SQL_GAME_OWNER_PASSWORD",
        "nl2sql_game_reader",
        "NL2SQL_GAME_READER_PASSWORD",
        "game.sql",
    ),
)


def _base_url(database: str) -> str:
    raw = get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


def _role_url(database: str, role: str, password: str) -> str:
    parts = urlsplit(_base_url(database))
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{quote(role)}:{quote(password)}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


async def _quoted(connection: asyncpg.Connection, value: str) -> str:
    return await connection.fetchval("SELECT quote_literal($1)", value)


async def main() -> None:
    admin = await asyncpg.connect(_base_url("postgres"))
    try:
        for database, owner, owner_env, reader, reader_env, _ in DATABASES:
            owner_password = os.environ[owner_env]
            reader_password = os.environ[reader_env]
            for role, password in ((owner, owner_password), (reader, reader_password)):
                quoted_password = await _quoted(admin, password)
                if not await admin.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=$1)", role
                ):
                    await admin.execute(
                        f'CREATE ROLE "{role}" LOGIN PASSWORD {quoted_password} '
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    )
                else:
                    await admin.execute(
                        f'ALTER ROLE "{role}" PASSWORD {quoted_password} '
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    )
            if not await admin.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=$1)",
                database,
            ):
                await admin.execute(f'CREATE DATABASE "{database}" OWNER "{owner}"')
            await admin.execute(
                f'ALTER DATABASE "{database}" OWNER TO "{owner}"'
            )
    finally:
        await admin.close()

    for database, owner, owner_env, _, _, sql_file in DATABASES:
        connection = await asyncpg.connect(
            _role_url(database, owner, os.environ[owner_env])
        )
        try:
            await connection.execute(
                (Path(__file__).parent / sql_file).read_text(encoding="utf-8")
            )
        finally:
            await connection.close()

    host = urlsplit(_base_url("postgres")).hostname or "127.0.0.1"
    port = urlsplit(_base_url("postgres")).port or 5432
    real_reader = os.environ["NL2SQL_REAL_ESTATE_READER_PASSWORD"]
    game_reader = os.environ["NL2SQL_GAME_READER_PASSWORD"]
    mapping = (
        "{"
        f'"real_estate_test":"postgresql://nl2sql_real_estate_reader:{quote(real_reader)}@{host}:{port}/nl2sql_real_estate_test",'
        f'"game_test":"postgresql://nl2sql_game_reader:{quote(game_reader)}@{host}:{port}/nl2sql_game_test"'
        "}"
    )
    print("NL2SQL 测试数据库初始化完成。请把以下值写入仅部署环境可读的配置：")
    print(f"NL2SQL_DATABASE_URLS_JSON={mapping}")


if __name__ == "__main__":
    asyncio.run(main())
