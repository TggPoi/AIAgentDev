"""通过真实 GitLab MR 发布一份游戏设计测试文档，供 RAG 报告验收。"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import psycopg
from dotenv import dotenv_values

from fast_app.core.config import get_settings


CONTENT = """# 星港远征资产使用设计说明

## 项目目标

星港远征是一款科幻策略游戏。当前版本优先建设主城展示和战斗关卡，资产选择必须同时考虑授权状态、制作费用、模型面数和实际使用场景。

## 资产选择规则

1. 只把“已授权”资产列入可直接采用清单；“待确认”和“仅内部使用”资产必须单独说明。
2. 主城展示优先选择辨识度高的角色、载具和场景模型。
3. 战斗关卡需要控制模型复杂度；同类资产应比较模型面数和费用，不应只按名称判断。
4. 报告必须引用真实资产查询的 query_id，并保留 NL2SQL 后端生成的 Markdown 表格。
5. 总费用、平均费用由 SQL 聚合；预算占比、成本差额等派生值必须使用 Calculator 计算。

## 报告验收

报告至少包含候选资产表、授权风险、成本统计、模型面数说明和最终推荐，并明确哪些结论来自本设计文档、哪些结论来自资产数据库。
"""


def api(client: httpx.Client, method: str, path: str, **kwargs: object) -> object:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}


def main() -> None:
    settings = get_settings()
    database_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    with psycopg.connect(database_url) as connection:
        source = connection.execute(
            """
            SELECT base_url, project_id, target_branch, agent_token_env
            FROM gitlab_sources
            WHERE department_code = %s AND status = 'active'
            """,
            ("product_planning",),
        ).fetchone()
    if source is None:
        raise RuntimeError("product_planning GitLab Source 不存在")
    base_url, project_id, target_branch, token_env = source
    token = dotenv_values(".env").get(token_env)
    if not token:
        raise RuntimeError(f"{token_env} 未配置")

    branch = "nl2sql-game-design-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    file_path = "product_planning/星港远征游戏设计说明.md"
    encoded_file = quote(file_path, safe="")
    headers = {"PRIVATE-TOKEN": str(token)}
    with httpx.Client(
        base_url=f"{base_url}/api/v4",
        headers=headers,
        timeout=30.0,
    ) as client:
        api(
            client,
            "POST",
            f"/projects/{project_id}/repository/branches",
            data={"branch": branch, "ref": target_branch},
        )
        probe = client.get(
            f"/projects/{project_id}/repository/files/{encoded_file}",
            params={"ref": target_branch},
        )
        action = "update" if probe.status_code == 200 else "create"
        commit = api(
            client,
            "POST",
            f"/projects/{project_id}/repository/commits",
            json={
                "branch": branch,
                "commit_message": "test: seed NL2SQL game design document",
                "actions": [
                    {
                        "action": action,
                        "file_path": file_path,
                        "content": CONTENT,
                    }
                ],
            },
        )
        merge_request = api(
            client,
            "POST",
            f"/projects/{project_id}/merge_requests",
            data={
                "source_branch": branch,
                "target_branch": target_branch,
                "title": "test: seed NL2SQL game design document",
                "remove_source_branch": True,
            },
        )
        merged = api(
            client,
            "PUT",
            f"/projects/{project_id}/merge_requests/{merge_request['iid']}/merge",
            data={"should_remove_source_branch": True},
        )
    print(
        {
            "project_id": project_id,
            "merge_request_iid": merge_request["iid"],
            "commit_sha": commit["id"],
            "merge_status": merged["state"],
            "file_path": file_path,
        }
    )


if __name__ == "__main__":
    main()
