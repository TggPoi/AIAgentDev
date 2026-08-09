from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import text

from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    build_es_filters,
)
from fast_app.components.retrievers.milvus_vector_retriever import (
    build_milvus_filter_expr,
)
from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.knowledge.knowledge_permission_policy import KnowledgePermissionPolicy


@dataclass(frozen=True)
class HttpUserScenario:
    name: str
    expected_departments: list[str]
    username: str | None
    password: str | None
    token: str | None
    query: str


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: actual={actual!r}, expected={expected!r}")


def run_policy_and_filter_contract_checks() -> None:
    policy = KnowledgePermissionPolicy()

    dev_user = CurrentUserContext(
        user_id="user_dev_001",
        is_authenticated=True,
        auth_source="jwt",
        department_codes=["development"],
        primary_department_code="development",
    )
    dev_scope = policy.build_scope(dev_user)
    dev_filters = RetrievalFilters(
        can_read_all=dev_scope.can_read_all,
        user_id=dev_scope.user_id,
        department_codes=dev_scope.department_codes,
        allow_public=dev_scope.allow_public,
    )

    es_filters = build_es_filters(dev_filters)
    milvus_filter = build_milvus_filter_expr(dev_filters) or ""
    assert_true(
        any("bool" in clause for clause in es_filters),
        "ES filters 应包含权限 bool filter",
    )
    assert_true(
        "allowed_departments" in str(es_filters),
        "ES 权限 filter 应包含 allowed_departments",
    )
    assert_true(
        "development" in milvus_filter,
        "Milvus 权限 filter 应包含 development 部门",
    )
    assert_true(
        'metadata["visibility"] == "public"' in milvus_filter,
        "Milvus 权限 filter 应允许 public 文档",
    )

    admin_scope = policy.build_scope(
        CurrentUserContext(
            user_id="admin_001",
            is_authenticated=True,
            auth_source="jwt",
            global_role_codes=["system_admin"],
        )
    )
    assert_true(admin_scope.can_read_all, "admin 应拥有全量读取权限")
    assert_true(
        build_es_filters(RetrievalFilters(can_read_all=True)) == [],
        "admin 的 ES 查询不应附加权限 filter",
    )
    assert_true(
        build_milvus_filter_expr(RetrievalFilters(can_read_all=True)) is None,
        "admin 的 Milvus 查询不应附加权限 filter",
    )
    print("policy_and_filter_contract=passed")


async def run_database_checks() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("select version_num from alembic_version"))
            ).scalar_one()
            departments = (
                await conn.execute(
                    text("select code, name from departments order by code")
                )
            ).all()

        assert_equal(version, "20260729_0010", "Alembic 版本不正确")
        assert_equal(
            [code for code, _name in departments],
            ["art", "development", "product_planning"],
            "部门种子数据不正确",
        )
        print(
            "database_department_seed=passed "
            + ";".join(f"{code}:{name}" for code, name in departments)
        )
    finally:
        await engine.dispose()


def post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url=url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    return _send_json_request(request)


def get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url=url, method="GET", headers=headers)
    return _send_json_request(request)


def _send_json_request(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(
            f"HTTP 请求失败: status={exc.code}, url={request.full_url}, body={error_body}"
        ) from exc

    return json.loads(raw)


def login(base_url: str, username: str, password: str) -> str:
    data = post_json(
        url=f"{base_url}/auth/login",
        payload={
            "username_or_email": username,
            "password": password,
        },
    )
    token = data.get("access_token")
    assert_true(isinstance(token, str) and bool(token), "登录响应缺少 access_token")
    return token


def assert_source_authorized(
    *,
    source: dict[str, Any],
    user_id: str,
    department_codes: list[str],
) -> None:
    metadata = source.get("metadata") or {}
    assert_true(isinstance(metadata, dict), "source.metadata 必须是 object")

    visibility = metadata.get("visibility")
    allowed_departments = metadata.get("allowed_departments") or []
    allowed_users = metadata.get("allowed_users") or []

    if visibility == "public":
        return

    if user_id in allowed_users:
        return

    if set(department_codes).intersection(set(allowed_departments)):
        return

    raise AssertionError(
        "返回了当前用户无权访问的 source: "
        f"id={source.get('id')}, visibility={visibility}, "
        f"allowed_departments={allowed_departments}, allowed_users={allowed_users}, "
        f"user_id={user_id}, user_departments={department_codes}"
    )


def run_http_scenario(base_url: str, scenario: HttpUserScenario) -> None:
    token = scenario.token
    if token is None:
        assert_true(
            scenario.username is not None and scenario.password is not None,
            f"{scenario.name} 缺少 token 或 username/password",
        )
        token = login(base_url, scenario.username or "", scenario.password or "")

    headers = {"Authorization": f"Bearer {token}"}
    me = get_json(f"{base_url}/auth/me", headers=headers)
    user_id = str(me["user_id"])
    department_codes = [str(item) for item in me.get("department_codes", [])]
    assert_equal(
        department_codes,
        scenario.expected_departments,
        f"{scenario.name} /auth/me 部门范围不正确",
    )

    response = post_json(
        url=f"{base_url}/rag/chat",
        payload={
            "query": scenario.query,
            "mode": "hybrid",
            "top_k": 5,
        },
        headers=headers,
    )
    sources = response.get("sources")
    assert_true(isinstance(sources, list), f"{scenario.name} 响应缺少 sources")
    assert_true(bool(sources), f"{scenario.name} 未返回 sources，请先重建带 ACL metadata 的知识库")

    for source in sources:
        assert_true(isinstance(source, dict), "source 必须是 object")
        assert_source_authorized(
            source=source,
            user_id=user_id,
            department_codes=department_codes,
        )

    print(
        f"http_acl_{scenario.name}=passed "
        f"user_id={user_id} departments={','.join(department_codes)} "
        f"source_count={len(sources)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="阶段 15-3 部门级知识库权限验收脚本"
    )
    parser.add_argument("--skip-db", action="store_true", help="跳过 PostgreSQL 部门种子检查")
    parser.add_argument("--base-url", default=None, help="传入后启用 HTTP 验收，例如 http://127.0.0.1:8000")

    parser.add_argument("--dev-token", default=None)
    parser.add_argument("--dev-username", default=None)
    parser.add_argument("--dev-password", default=None)
    parser.add_argument("--dev-query", default="RAG 后端部署步骤是什么？")

    parser.add_argument("--art-token", default=None)
    parser.add_argument("--art-username", default=None)
    parser.add_argument("--art-password", default=None)
    parser.add_argument("--art-query", default="角色原画风格规范是什么？")

    parser.add_argument("--product-token", default=None)
    parser.add_argument("--product-username", default=None)
    parser.add_argument("--product-password", default=None)
    parser.add_argument("--product-query", default="战斗系统设计原则是什么？")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    run_policy_and_filter_contract_checks()

    if not args.skip_db:
        await run_database_checks()

    if args.base_url is None:
        print("http_acl_checks=skipped reason=base_url_empty")
        return

    base_url = args.base_url.rstrip("/")
    scenarios = [
        HttpUserScenario(
            name="development",
            expected_departments=["development"],
            username=args.dev_username,
            password=args.dev_password,
            token=args.dev_token,
            query=args.dev_query,
        ),
        HttpUserScenario(
            name="art",
            expected_departments=["art"],
            username=args.art_username,
            password=args.art_password,
            token=args.art_token,
            query=args.art_query,
        ),
        HttpUserScenario(
            name="product_planning",
            expected_departments=["product_planning"],
            username=args.product_username,
            password=args.product_password,
            token=args.product_token,
            query=args.product_query,
        ),
    ]

    for scenario in scenarios:
        has_credential = scenario.token or (scenario.username and scenario.password)
        if not has_credential:
            print(f"http_acl_{scenario.name}=skipped reason=credential_empty")
            continue
        run_http_scenario(base_url, scenario)


if __name__ == "__main__":
    asyncio.run(async_main())
