"""跨 Worker 共享的 RAG Store mutation PostgreSQL advisory lock。"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


STORE_MUTATION_LOCK_NAMESPACE = "python-agent-study:rag-store-mutation:v1"


def store_mutation_lock_key() -> int:
    raw = hashlib.sha256(STORE_MUTATION_LOCK_NAMESPACE.encode("utf-8")).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)


class StoreMutationLock:
    """在同一专用数据库连接上获取和释放 session-level advisory lock。"""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._key = store_mutation_lock_key()

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        async with self._engine.connect() as connection:
            acquired = False
            try:
                await connection.execute(
                    text("SELECT pg_advisory_lock(:key)"), {"key": self._key}
                )
                acquired = True
                yield
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": self._key}
                    )


__all__ = [
    "STORE_MUTATION_LOCK_NAMESPACE",
    "StoreMutationLock",
    "store_mutation_lock_key",
]
