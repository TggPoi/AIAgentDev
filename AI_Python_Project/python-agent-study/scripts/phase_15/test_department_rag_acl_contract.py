from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    build_es_filters,
)
from fast_app.components.retrievers.milvus_vector_retriever import (
    build_milvus_filter_expr,
)
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.knowledge.knowledge_permission_policy import (
    KnowledgePermissionPolicy,
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    policy = KnowledgePermissionPolicy()

    dev_user = CurrentUserContext(
        user_id="user_dev_001",
        is_authenticated=True,
        auth_source="jwt",
        role="user",
        permissions=["rag:chat"],
        department_codes=["development"],
        primary_department_code="development",
    )
    dev_scope = policy.build_scope(dev_user)
    assert_true(not dev_scope.can_read_all, "普通开发用户不应拥有全量读取权限")
    assert_true(
        dev_scope.department_codes == ["development"],
        "开发用户应携带 development 部门范围",
    )

    dev_filters = RetrievalFilters(
        source_path=None,
        section_path=[],
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

    admin = CurrentUserContext(
        user_id="admin_001",
        is_authenticated=True,
        auth_source="jwt",
        role="admin",
        permissions=["*"],
    )
    admin_scope = policy.build_scope(admin)
    admin_filters = RetrievalFilters(can_read_all=admin_scope.can_read_all)
    assert_true(admin_scope.can_read_all, "admin 应拥有全量读取权限")
    assert_true(
        build_milvus_filter_expr(admin_filters) is None,
        "admin 的 Milvus 查询不应附加权限 filter",
    )
    assert_true(
        build_es_filters(admin_filters) == [],
        "admin 的 ES 查询不应附加权限 filter",
    )

    print("department_acl_policy_and_filter_contract=passed")


if __name__ == "__main__":
    main()
