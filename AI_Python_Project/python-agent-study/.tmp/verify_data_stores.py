r"""一次性只读验证脚本：检查本地 Docker 的 Milvus / ES / PostgreSQL / Redis 连通性与数据概况。

不修改任何数据。运行：
    $env:PYTHONPATH="src"; .\.venv\Scripts\python.exe .tmp\verify_data_stores.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

MILVUS_HOST = "127.0.0.1"
MILVUS_PORT = 19530
MILVUS_COLLECTION = "python_agent_demo_chunks"

ES_URL = "http://127.0.0.1:9200"
ES_INDEX = "python_agent_demo_chunks"

PG_URL = "postgresql://user:123456@127.0.0.1:5432/python_agent_study"

REDIS_URL = "redis://127.0.0.1:6379/0"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    mark = "OK " if ok else "FAIL"
    print(f"[{mark}] {name}: {detail}")


def check_milvus() -> None:
    from pymilvus import MilvusClient

    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    collections = client.list_collections()
    if MILVUS_COLLECTION not in collections:
        record("Milvus", False, f"连接成功，但未找到 collection={MILVUS_COLLECTION}；现有: {collections}")
        return
    client.load_collection(MILVUS_COLLECTION)
    count = client.query(MILVUS_COLLECTION, filter="", output_fields=["count(*)"])[0]["count(*)"]
    # 只按 collection 真实存在的字段抽样，避免旧/新 schema 字段差异导致报错
    schema = client.describe_collection(MILVUS_COLLECTION)
    field_names = [f["name"] for f in schema.get("fields", [])]
    sample_fields = [
        name
        for name in ("id", "doc_id", "source", "logical_chunk_id", "logical_record_id", "title", "content")
        if name in field_names
    ]
    sample = client.query(MILVUS_COLLECTION, filter="", output_fields=sample_fields, limit=3)
    doc_id_field = "doc_id" if "doc_id" in field_names else "logical_record_id"
    doc_ids = sorted({str(row.get(doc_id_field) or "?") for row in sample})
    titles = sorted({str(row.get("title") or "?") for row in sample}) if "title" in field_names else []
    record(
        "Milvus",
        True,
        (
            f"collection={MILVUS_COLLECTION} 共 {count} 条实体；"
            f"抽样 {doc_id_field}={doc_ids}；抽样 title={titles}；全部字段={field_names}"
        ),
    )


def check_elasticsearch() -> None:
    from elasticsearch import AsyncElasticsearch

    async def run() -> None:
        last_error = None
        auth_options = (
            {},
            {"basic_auth": ("elastic", "你的密码")},
        )
        for auth in auth_options:
            try:
                async with AsyncElasticsearch(ES_URL, request_timeout=5, **auth) as es:
                    info = await es.info()
                    exists = await es.indices.exists(index=ES_INDEX)
                    if not exists:
                        indices = await es.indices.get_alias(index="*")
                        record(
                            "Elasticsearch",
                            False,
                            (
                                f"连接成功 (v{info['version']['number']})，"
                                f"但未找到 index={ES_INDEX}；现有索引: {sorted(indices)}"
                            ),
                        )
                        return
                    count = (await es.count(index=ES_INDEX))["count"]
                    sample = await es.search(
                        index=ES_INDEX,
                        body={"size": 3, "query": {"match_all": {}}, "_source": ["doc_id", "source", "logical_chunk_id"]},
                    )
                    doc_ids = sorted({str(h["_source"].get("doc_id") or "?") for h in sample["hits"]["hits"]})
                    record(
                        "Elasticsearch",
                        True,
                        f"index={ES_INDEX} 共 {count} 条文档；抽样 doc_id={doc_ids}",
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        record("Elasticsearch", False, f"连接失败: {type(last_error).__name__}: {last_error}")

    asyncio.run(run())


def check_postgresql() -> None:
    import psycopg

    with psycopg.connect(PG_URL.replace("postgresql+asyncpg://", "postgresql://"), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
            detail_tables = []
            for table in ("knowledge_documents", "knowledge_chunks", "auth_users", "auth_api_keys"):
                if table in tables:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    detail_tables.append(f"{table}={cur.fetchone()[0]}")
            record(
                "PostgreSQL",
                True,
                f"database=python_agent_study 共 {len(tables)} 张表；关键表行数: {detail_tables or '未找到预期表'}；全部表: {tables}",
            )


def check_redis() -> None:
    import redis as redis_lib

    client = redis_lib.Redis.from_url(REDIS_URL, socket_connect_timeout=5, decode_responses=True)
    pong = client.ping()
    dbsize = client.dbsize()
    keys = client.keys("*")[:10]
    record("Redis", bool(pong), f"ping={pong}, dbsize={dbsize}, 前 10 个 key: {keys}")


def main() -> None:
    checks = {
        "Milvus": check_milvus,
        "Elasticsearch": check_elasticsearch,
        "PostgreSQL": check_postgresql,
        "Redis": check_redis,
    }
    for name, func in checks.items():
        try:
            func()
        except Exception:
            record(name, False, traceback.format_exc(limit=3).strip().splitlines()[-1])
    failed = [name for name, ok, _ in RESULTS if not ok]
    print()
    if failed:
        print(f"验证结果：{len(failed)} 个服务异常：{failed}")
        sys.exit(1)
    print("验证结果：4 个服务全部可访问。")


if __name__ == "__main__":
    main()
