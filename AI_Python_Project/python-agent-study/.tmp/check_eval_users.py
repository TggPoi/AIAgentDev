"""只读检查 rbac_reader / rbac_operator 的部门与全局角色分布。"""

from __future__ import annotations

import psycopg

DSN = "postgresql://user:123456@127.0.0.1:5432/python_agent_study"


def main() -> None:
    conn = psycopg.connect(DSN)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT u.id, u.username, u.status
        FROM users u
        WHERE u.username IN ('rbac_reader', 'rbac_operator')
        ORDER BY u.username
        """
    )
    users = cur.fetchall()
    print("== 用户 ==")
    for row in users:
        print(row)

    user_ids = [row[0] for row in users]
    if user_ids:
        cur.execute(
            """
            SELECT ud.user_id, ud.department_code, ud.is_primary
            FROM user_departments ud
            WHERE ud.user_id = ANY(%s)
            ORDER BY ud.user_id
            """,
            (user_ids,),
        )
        print("\n== 部门绑定（is_primary=True 为主部门）==")
        for row in cur.fetchall():
            print(row)

        cur.execute(
            """
            SELECT ur.user_id, r.code
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = ANY(%s)
            ORDER BY ur.user_id
            """,
            (user_ids,),
        )
        print("\n== 全局角色 ==")
        for row in cur.fetchall():
            print(row)

        cur.execute(
            """
            SELECT udr.user_id, udr.department_code, r.code
            FROM user_department_roles udr
            JOIN roles r ON r.id = udr.role_id
            WHERE udr.user_id = ANY(%s)
            ORDER BY udr.user_id
            """,
            (user_ids,),
        )
        print("\n== 部门角色 ==")
        for row in cur.fetchall():
            print(row)

    cur.execute("SELECT COUNT(*) FROM api_keys")
    print("\napi_keys 当前行数:", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
