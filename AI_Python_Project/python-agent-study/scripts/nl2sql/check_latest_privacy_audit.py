import argparse

from fast_app.core.config import get_settings
import psycopg


parser = argparse.ArgumentParser()
parser.add_argument("--purge-test-sentinel-leaks", action="store_true")
args = parser.parse_args()
url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
with psycopg.connect(url) as connection:
    if args.purge_test_sentinel_leaks:
        deleted = connection.execute(
            """
            DELETE FROM nl2sql_query_audits
            WHERE dataset_id = %s
              AND (
                tokenized_question LIKE %s
                OR tokenized_question LIKE %s
                OR parameterized_sql LIKE %s
                OR parameterized_sql LIKE %s
              )
            """,
            (
                "real_estate_test",
                "%云栖雅苑%",
                "%2500000%",
                "%云栖雅苑%",
                "%2500000%",
            ),
        ).rowcount
        print({"purged_test_audit_rows": deleted})
    row = connection.execute(
        """
        SELECT tokenized_question, parameterized_sql
        FROM nl2sql_query_audits
        WHERE dataset_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        ("real_estate_test",),
    ).fetchone()
    audit_count = connection.execute(
        "SELECT count(*) FROM nl2sql_query_audits WHERE dataset_id = %s",
        ("real_estate_test",),
    ).fetchone()[0]
assert row is not None
print(
    {
        "audit_count": audit_count,
        "name_in_question": "云栖雅苑" in row[0],
        "price_in_question": "2500000" in row[0],
        "name_in_sql": "云栖雅苑" in row[1],
        "price_in_sql": "2500000" in row[1],
    }
)
