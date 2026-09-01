"""验证文档授权选择目录的公共 HTTP/OpenAPI 与服务端范围。"""

import asyncio

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.api.document_access_routes import router
from fast_app.core.exception_handlers import register_exception_handlers
from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.dependencies.document_access_dependencies import (
    get_document_access_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.auth_models import AccountType
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.knowledge.document_access_repository import (
    DocumentAccessRepository,
)
from fast_app.services.knowledge.document_access_service import DocumentAccessService
from fast_app.services.exceptions import DocumentAccessPermissionDeniedError

import test_document_access_grants as grant_fixtures


CATALOG_PATH = "/admin/document-access/grantable-documents"
DOC_DEV_PUBLIC = "doc_document_grant_dev_public"


def main() -> None:
    assert_openapi_contract()
    assert_request_validation_contract()
    asyncio.run(assert_manager_catalog_scope())
    print("document_access_grantable_documents=passed")


def assert_openapi_contract() -> None:
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"][CATALOG_PATH]["get"]

    assert {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter["in"] == "query"
    } == {"cursor", "limit", "query", "department_code"}
    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema == {
        "$ref": "#/components/schemas/DocumentAccessGrantableDocumentListResponse"
    }
    validation_schema = operation["responses"]["422"]["content"][
        "application/json"
    ]["schema"]
    assert validation_schema["discriminator"]["propertyName"] == "code"


def assert_request_validation_contract() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(
        user_id="grantable-validation-admin",
        username="grantable-validation-admin",
        account_type=AccountType.ADMIN,
        is_authenticated=True,
        auth_source="jwt",
    )
    app.dependency_overrides[get_document_access_service] = object
    marker = "grantable-selection-marker"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            CATALOG_PATH,
            params={"limit": 0, "query": marker * 20},
        )

    assert response.status_code == 422, response.text
    assert {item["field"] for item in response.json()["field_errors"]} == {
        "limit",
        "query",
    }
    assert marker not in response.text


async def assert_manager_catalog_scope() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _cleanup(session)
            await grant_fixtures._seed_facts(session)
            await _seed_public_document(session)
            service = DocumentAccessService(DocumentAccessRepository(session))
            manager = grant_fixtures._actor(
                grant_fixtures.DEV_MANAGER_ID,
                AccountType.DEPARTMENT_MANAGER,
                "development",
            )

            page = await service.list_grantable_documents(
                manager,
                cursor=None,
                limit=20,
                query=None,
                department_code=None,
            )

            assert {item.doc_id for item in page.items} == {
                grant_fixtures.DOC_DEV_ONE,
                grant_fixtures.DOC_DEV_TWO,
            }
            assert all(
                item.document_department_code == "development"
                for item in page.items
            )

            admin = grant_fixtures._actor(
                grant_fixtures.ADMIN_ID,
                AccountType.ADMIN,
                "development",
            )
            admin_page = await service.list_grantable_documents(
                admin,
                cursor=None,
                limit=20,
                query=None,
                department_code=None,
            )
            assert {item.doc_id for item in admin_page.items} == {
                grant_fixtures.DOC_DEV_ONE,
                grant_fixtures.DOC_DEV_TWO,
                grant_fixtures.DOC_ART_ONE,
            }

            admin_development_page = await service.list_grantable_documents(
                admin,
                cursor=None,
                limit=20,
                query=None,
                department_code="development",
            )
            assert {item.doc_id for item in admin_development_page.items} == {
                grant_fixtures.DOC_DEV_ONE,
                grant_fixtures.DOC_DEV_TWO,
            }

            try:
                await service.list_grantable_documents(
                    manager,
                    cursor=None,
                    limit=20,
                    query=None,
                    department_code="art",
                )
            except DocumentAccessPermissionDeniedError:
                pass
            else:
                raise AssertionError("manager must not expand the catalog department")

            employee = grant_fixtures._actor(
                grant_fixtures.ART_USER_ID,
                AccountType.EMPLOYEE,
                "art",
            )
            try:
                await service.list_grantable_documents(
                    employee,
                    cursor=None,
                    limit=20,
                    query=None,
                    department_code=None,
                )
            except DocumentAccessPermissionDeniedError:
                pass
            else:
                raise AssertionError("employee must not list grantable documents")

            query_page = await service.list_grantable_documents(
                manager,
                cursor=None,
                limit=20,
                query="two",
                department_code=None,
            )
            assert [item.doc_id for item in query_page.items] == [
                grant_fixtures.DOC_DEV_TWO
            ]

            first_page = await service.list_grantable_documents(
                manager,
                cursor=None,
                limit=1,
                query=None,
                department_code=None,
            )
            assert len(first_page.items) == 1
            assert first_page.next_cursor is not None
            second_page = await service.list_grantable_documents(
                manager,
                cursor=first_page.next_cursor,
                limit=1,
                query=None,
                department_code=None,
            )
            assert len(second_page.items) == 1
            assert second_page.next_cursor is None
            assert {
                first_page.items[0].doc_id,
                second_page.items[0].doc_id,
            } == {
                grant_fixtures.DOC_DEV_ONE,
                grant_fixtures.DOC_DEV_TWO,
            }

            app = FastAPI()
            register_exception_handlers(app)
            app.include_router(router)
            app.dependency_overrides[get_current_user_context] = lambda: manager
            app.dependency_overrides[get_document_access_service] = lambda: service
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.get(CATALOG_PATH, params={"query": "two"})
                invalid_cursor_marker = "grantable-invalid-cursor-marker"
                invalid_response = await client.get(
                    CATALOG_PATH,
                    params={"cursor": invalid_cursor_marker},
                )

            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == {"items", "next_cursor"}
            assert len(body["items"]) == 1
            assert set(body["items"][0]) == {
                "doc_id",
                "title",
                "repository_path",
                "document_department_code",
                "document_type",
            }
            assert not {
                "acl_json",
                "allowed_users",
                "visibility",
                "source",
                "permissions",
            }.intersection(body["items"][0])

            assert invalid_response.status_code == 422, invalid_response.text
            invalid_body = invalid_response.json()
            assert invalid_body["code"] == "DOCUMENT_ACCESS_GRANT_INVALID"
            assert invalid_body["field_errors"] == []
            assert invalid_cursor_marker not in invalid_response.text
    finally:
        async with session_factory() as cleanup_session:
            await _cleanup(cleanup_session)
        await engine.dispose()


async def _seed_public_document(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            insert into gitlab_documents
                (doc_id, source_id, repository_path, source_revision,
                 content_hash, acl_hash, parser_version,
                 chunk_strategy_version, chunk_config_fingerprint,
                 document_type, acl_json, status)
            values
                (:doc_id, :source_id, 'development/public.md', 'sha-grant-test',
                 :content_hash, :acl_hash, 'parser-v1', 'chunk-v1',
                 'config-v1', 'markdown',
                 jsonb_build_object(
                     'visibility', 'public',
                     'allowed_departments', '[]'::jsonb,
                     'allowed_users', '[]'::jsonb
                 ),
                 'active')
            """
        ),
        {
            "doc_id": DOC_DEV_PUBLIC,
            "source_id": grant_fixtures.SOURCE_DEV_ID,
            "content_hash": f"content-{DOC_DEV_PUBLIC}",
            "acl_hash": f"acl-{DOC_DEV_PUBLIC}",
        },
    )
    await session.commit()


async def _cleanup(session: AsyncSession) -> None:
    await session.execute(
        text("delete from gitlab_documents where doc_id = :doc_id"),
        {"doc_id": DOC_DEV_PUBLIC},
    )
    await grant_fixtures._cleanup(session)


if __name__ == "__main__":
    main()
