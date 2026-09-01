"""验证跨部门文档 grant 的部门范围、幂等、撤销和 HTTP 契约。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.api.document_access_routes import router
from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    build_es_permission_filter,
)
from fast_app.components.retrievers.milvus_vector_retriever import (
    build_milvus_permission_filter_expr,
)
from fast_app.core.config import get_settings
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.document_access_dependencies import (
    get_document_access_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.document_access_schema import (
    CreateDocumentAccessGrantsRequest,
    CreateDocumentAccessGrantsResponse,
    DocumentAccessGrantItem,
    DocumentAccessGrantListResponse,
    DocumentAccessGrantUser,
)
from fast_app.services.auth.auth_crypto import hash_password
from fast_app.services.exceptions import (
    DocumentAccessGrantInvalidError,
    DocumentAccessPermissionDeniedError,
)
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessRepository,
)
from fast_app.services.knowledge.document_access_policy import DocumentAccessPolicy
from fast_app.services.knowledge.document_access_service import DocumentAccessService
from fast_app.services.knowledge.knowledge_permission_policy import (
    build_retrieval_filters_from_mapping,
)
from fast_app.services.rag.markdown_parent_context import (
    MarkdownParentContextExpander,
)


ADMIN_ID = "user_document_grant_admin"
DEV_MANAGER_ID = "user_document_grant_dev_manager"
ART_USER_ID = "user_document_grant_art_employee"
DEV_USER_ID = "user_document_grant_dev_employee"
SOURCE_DEV_ID = "source_document_grant_dev"
SOURCE_ART_ID = "source_document_grant_art"
DOC_DEV_ONE = "doc_document_grant_dev_one"
DOC_DEV_TWO = "doc_document_grant_dev_two"
DOC_ART_ONE = "doc_document_grant_art_one"


def main() -> None:
    asyncio.run(assert_database_flow())
    assert_http_contract()
    print("document_access_grants=passed")


async def assert_database_flow() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _cleanup(session)
            await _seed_facts(session)
            repository = DocumentAccessRepository(session)
            service = DocumentAccessService(repository)
            admin = _actor(ADMIN_ID, AccountType.ADMIN, "development")
            manager = _actor(
                DEV_MANAGER_ID,
                AccountType.DEPARTMENT_MANAGER,
                "development",
            )

            created = await service.create_grants(
                manager,
                CreateDocumentAccessGrantsRequest(
                    target_account="grant_art_employee",
                    document_ids=[DOC_DEV_ONE, DOC_DEV_TWO],
                ),
            )
            assert created.created_count == 2
            assert created.existing_count == 0
            assert {item.document_id for item in created.items} == {
                DOC_DEV_ONE,
                DOC_DEV_TWO,
            }
            assert all(
                item.document_department_code == "development"
                for item in created.items
            )

            repeated = await service.create_grants(
                manager,
                CreateDocumentAccessGrantsRequest(
                    target_account="GRANT_ART_EMPLOYEE",
                    document_ids=[DOC_DEV_ONE, DOC_DEV_TWO],
                ),
            )
            assert repeated.created_count == 0
            assert repeated.existing_count == 2
            assert [item.grant_id for item in repeated.items] == [
                item.grant_id for item in created.items
            ]

            page = await service.list_grants(
                manager,
                cursor=None,
                limit=1,
                target_account=None,
                doc_id=None,
                status="active",
                department_code=None,
            )
            assert len(page.items) == 1
            assert page.next_cursor is not None
            second_page = await service.list_grants(
                manager,
                cursor=page.next_cursor,
                limit=1,
                target_account=None,
                doc_id=None,
                status="active",
                department_code=None,
            )
            assert len(second_page.items) == 1
            assert page.items[0].grant_id != second_page.items[0].grant_id

            try:
                await service.create_grants(
                    manager,
                    CreateDocumentAccessGrantsRequest(
                        target_account="grant_art_employee",
                        document_ids=[DOC_ART_ONE],
                    ),
                )
            except DocumentAccessPermissionDeniedError:
                pass
            else:
                raise AssertionError("开发主管不应授权美术部门拥有的文档")

            try:
                await service.create_grants(
                    admin,
                    CreateDocumentAccessGrantsRequest(
                        target_account="grant_dev_employee",
                        document_ids=[DOC_DEV_ONE],
                    ),
                )
            except DocumentAccessGrantInvalidError as exc:
                assert exc.field == "document_ids"
                assert exc.field_code == "invalid"
            else:
                raise AssertionError("同部门文档不应创建冗余跨部门 grant")

            grant_to_revoke = created.items[0]
            try:
                await service.revoke_grant(
                    _actor(
                        "non_persistent_art_manager",
                        AccountType.DEPARTMENT_MANAGER,
                        "art",
                    ),
                    grant_to_revoke.grant_id,
                )
            except DocumentAccessPermissionDeniedError:
                pass
            else:
                raise AssertionError("其他部门主管不应撤销开发文档 grant")

            revoked = await service.revoke_grant(manager, grant_to_revoke.grant_id)
            assert revoked.status == "revoked"
            assert revoked.revoked_by_user_id == DEV_MANAGER_ID
            repeated_revoke = await service.revoke_grant(
                manager,
                grant_to_revoke.grant_id,
            )
            assert repeated_revoke.status == "revoked"
            assert repeated_revoke.revoked_by_user_id == DEV_MANAGER_ID
            active_doc_ids = await repository.list_active_granted_document_ids(
                ART_USER_ID
            )
            assert active_doc_ids == [DOC_DEV_TWO]
            art_user = _actor(ART_USER_ID, AccountType.EMPLOYEE, "art")
            access_policy = DocumentAccessPolicy(repository)
            scope = await access_policy.build_retrieval_scope(art_user)
            assert scope.department_codes == ["art"]
            assert scope.granted_document_ids == [DOC_DEV_TWO]
            assert await access_policy.can_read_document(
                art_user,
                document_id=DOC_ART_ONE,
                document_department_code="art",
                visibility="department",
            )
            assert await access_policy.can_read_document(
                art_user,
                document_id=DOC_DEV_TWO,
                document_department_code="development",
                visibility="department",
            )
            assert not await access_policy.can_read_document(
                art_user,
                document_id=DOC_DEV_ONE,
                document_department_code="development",
                visibility="department",
            )
            assert await access_policy.can_read_document(
                art_user,
                document_id="public-document",
                document_department_code="development",
                visibility="public",
            )
            assert await access_policy.can_read_document(
                art_user,
                document_id="legacy-private-document",
                document_department_code="development",
                visibility="private",
                allowed_user_ids=[ART_USER_ID],
            )
            filters = build_retrieval_filters_from_mapping(scope.model_dump())
            es_filter = build_es_permission_filter(filters)
            milvus_filter = build_milvus_permission_filter_expr(filters) or ""
            assert DOC_DEV_TWO in str(es_filter)
            assert "metadata.doc_id" in str(es_filter)
            assert DOC_DEV_TWO in milvus_filter
            assert "doc_id in" in milvus_filter
            parent_client = AsyncMock()
            parent_client.search.return_value = {"hits": {"hits": []}}
            await MarkdownParentContextExpander(
                settings,
                parent_client,
            )._load_parents(["parent-grant-test"], filters)
            parent_query = parent_client.search.await_args.kwargs["query"]
            assert DOC_DEV_TWO in str(parent_query)

            admin_page = await service.list_grants(
                admin,
                cursor=None,
                limit=20,
                target_account="grant_art",
                doc_id=None,
                status=None,
                department_code="development",
            )
            assert len(admin_page.items) == 2
    finally:
        async with session_factory() as cleanup_session:
            await _cleanup(cleanup_session)
        await engine.dispose()


async def _seed_facts(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into users (id, username, password_hash, status)
            values
                (:admin_id, 'grant_admin', :password_hash, 'active'),
                (:manager_id, 'grant_dev_manager', :password_hash, 'active'),
                (:art_user_id, 'grant_art_employee', :password_hash, 'active'),
                (:dev_user_id, 'grant_dev_employee', :password_hash, 'active')
            """
        ),
        {
            "admin_id": ADMIN_ID,
            "manager_id": DEV_MANAGER_ID,
            "art_user_id": ART_USER_ID,
            "dev_user_id": DEV_USER_ID,
            "password_hash": hash_password("DocumentGrant123!"),
        },
    )
    await session.execute(
        text(
            """
            insert into user_roles (id, user_id, role_id)
            select 'user_role_document_grant_admin', :admin_id, id
            from roles where code = 'system_admin'
            """
        ),
        {"admin_id": ADMIN_ID},
    )
    await session.execute(
        text(
            """
            insert into user_departments (id, user_id, department_code, is_primary)
            values
                ('user_dept_document_grant_manager', :manager_id, 'development', true),
                ('user_dept_document_grant_art', :art_user_id, 'art', true),
                ('user_dept_document_grant_dev', :dev_user_id, 'development', true)
            """
        ),
        {
            "manager_id": DEV_MANAGER_ID,
            "art_user_id": ART_USER_ID,
            "dev_user_id": DEV_USER_ID,
        },
    )
    await session.execute(
        text(
            """
            insert into user_department_roles (id, user_id, department_code, role_id)
            select
                'user_dept_role_document_grant_manager',
                :manager_id,
                'development',
                id
            from roles where code = 'department_manager'
            """
        ),
        {"manager_id": DEV_MANAGER_ID},
    )
    for source_id, project_id, project_path, department in (
        (SOURCE_DEV_ID, 91001, "grant/dev", "development"),
        (SOURCE_ART_ID, 91002, "grant/art", "art"),
    ):
        await session.execute(
            text(
                """
                insert into gitlab_sources
                    (id, base_url, host_id, project_id, project_path,
                     target_branch, department_code, default_visibility,
                     sync_token_env, agent_token_env, webhook_secret_env, status)
                values
                    (:id, 'https://gitlab.example.test', 'grant-test', :project_id,
                     :project_path, 'main', :department, 'department',
                     'SYNC_TOKEN', 'AGENT_TOKEN', 'WEBHOOK_SECRET', 'active')
                """
            ),
            {
                "id": source_id,
                "project_id": project_id,
                "project_path": project_path,
                "department": department,
            },
        )
    for doc_id, source_id, path, department in (
        (DOC_DEV_ONE, SOURCE_DEV_ID, "development/one.md", "development"),
        (DOC_DEV_TWO, SOURCE_DEV_ID, "development/two.md", "development"),
        (DOC_ART_ONE, SOURCE_ART_ID, "art/one.md", "art"),
    ):
        await session.execute(
            text(
                """
                insert into gitlab_documents
                    (doc_id, source_id, repository_path, source_revision,
                     content_hash, acl_hash, parser_version,
                     chunk_strategy_version, chunk_config_fingerprint,
                     document_type, acl_json, status)
                values
                    (:doc_id, :source_id, :path, 'sha-grant-test',
                     :content_hash, :acl_hash, 'parser-v1', 'chunk-v1',
                     'config-v1', 'markdown',
                     jsonb_build_object(
                         'visibility', 'department',
                         'allowed_departments',
                         jsonb_build_array(cast(:department as text)),
                         'allowed_users', '[]'::jsonb
                     ),
                     'active')
                """
            ),
            {
                "doc_id": doc_id,
                "source_id": source_id,
                "path": path,
                "content_hash": f"content-{doc_id}",
                "acl_hash": f"acl-{doc_id}",
                "department": department,
            },
        )
    await session.commit()


async def _cleanup(session: AsyncSession) -> None:
    await session.execute(
        text(
            "delete from document_access_grants "
            "where grantee_user_id = any(:user_ids) "
            "or granted_by_user_id = any(:user_ids) "
            "or revoked_by_user_id = any(:user_ids)"
        ),
        {"user_ids": [ADMIN_ID, DEV_MANAGER_ID, ART_USER_ID, DEV_USER_ID]},
    )
    await session.execute(
        text("delete from gitlab_documents where doc_id = any(:doc_ids)"),
        {"doc_ids": [DOC_DEV_ONE, DOC_DEV_TWO, DOC_ART_ONE]},
    )
    await session.execute(
        text("delete from gitlab_sources where id = any(:source_ids)"),
        {"source_ids": [SOURCE_DEV_ID, SOURCE_ART_ID]},
    )
    await session.execute(
        text("delete from users where id = any(:user_ids)"),
        {"user_ids": [ADMIN_ID, DEV_MANAGER_ID, ART_USER_ID, DEV_USER_ID]},
    )
    await session.commit()


def _actor(
    user_id: str,
    account_type: AccountType,
    department: str | None,
) -> CurrentUserContext:
    return CurrentUserContext(
        user_id=user_id,
        username=user_id,
        account_type=account_type,
        is_authenticated=True,
        auth_source="jwt",
        department_codes=[department] if department else [],
        primary_department_code=department,
    )


def assert_http_contract() -> None:
    now = datetime.now(UTC)
    item = DocumentAccessGrantItem(
        grant_id="grant-http",
        document_id="doc-http",
        repository_path="development/http.md",
        document_department_code="development",
        grantee=DocumentAccessGrantUser(
            user_id="target-http",
            username="target-http",
            primary_department_code="art",
        ),
        status="active",
        granted_by_user_id="actor-http",
        granted_at=now,
    )
    fake_service = AsyncMock()
    fake_service.list_grants.return_value = DocumentAccessGrantListResponse(
        items=[item]
    )
    fake_service.create_grants.return_value = CreateDocumentAccessGrantsResponse(
        items=[item],
        created_count=1,
        existing_count=0,
    )
    fake_service.revoke_grant.return_value = item.model_copy(
        update={
            "status": "revoked",
            "revoked_by_user_id": "actor-http",
            "revoked_at": now,
        }
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _actor(
        "actor-http",
        AccountType.ADMIN,
        "development",
    )
    app.dependency_overrides[get_document_access_service] = lambda: fake_service
    client = TestClient(app, raise_server_exceptions=False)

    listed = client.get("/admin/document-access/grants?status=active")
    assert listed.status_code == 200, listed.text
    created = client.post(
        "/admin/document-access/grants",
        json={"target_account": "target-http", "document_ids": ["doc-http"]},
    )
    assert created.status_code == 200, created.text
    revoked = client.delete("/admin/document-access/grants/grant-http")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    invalid = client.post(
        "/admin/document-access/grants",
        json={
            "target_account": "target-http",
            "document_ids": ["doc-http", "doc-http"],
        },
    )
    assert invalid.status_code == 422, invalid.text
    paths = app.openapi()["paths"]
    assert "/admin/document-access/grants" in paths
    assert "/admin/document-access/grants/{grant_id}" in paths


if __name__ == "__main__":
    main()
