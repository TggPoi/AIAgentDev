"""离线验证 Direct Web 重定向约束、exact_url 预验证与错误分类分流。"""

import asyncio

import httpx

from fast_app.agents.runtime.agent_error_policy import classify_agent_error
from fast_app.graph.rag_agent.rag_agent_nodes import route_after_direct_web
from fast_app.services.exceptions import ExternalServiceError, NoSearchResultError
from fast_app.services.rag.direct_web_page_fetch import (
    _fetch_single_page,
    final_url_within_constraint,
    verify_exact_url_page,
)


LONG_TEXT = (
    "PostgreSQL 行级安全策略允许数据库管理员为表配置访问策略，"
    "使得每个用户在执行查询时只能看到符合策略条件的行。" * 5
)


class FakeResponse:
    def __init__(self, *, text: str, url: str, status_code: int = 200) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self, routes: dict[str, FakeResponse], *, not_found: set[str] = frozenset()) -> None:
        self.routes = routes
        self.not_found = not_found

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        if url in self.not_found:
            raise httpx.HTTPError(f"HTTP 404 for {url}")
        response = self.routes.get(url)
        if response is None:
            raise httpx.HTTPError(f"no route for {url}")
        return response


def test_final_url_constraint_site_mode() -> None:
    original = "https://www.postgresql.org/docs/16/ddl.html"
    assert final_url_within_constraint(
        "https://www.postgresql.org/docs/16/ddl.html",
        site="postgresql.org",
        original_url=original,
    )
    assert not final_url_within_constraint(
        "https://evil.example.com/phish",
        site="postgresql.org",
        original_url=original,
    ), "site 模式下跨域重定向必须拒绝"


def test_final_url_constraint_general_mode() -> None:
    original = "https://www.example.com/blog/post"
    # 同域、子域、父域跳转允许
    assert final_url_within_constraint(
        "https://www.example.com/blog/post-2", site=None, original_url=original
    )
    assert final_url_within_constraint(
        "https://cdn.example.com/x", site=None, original_url=original
    )
    assert final_url_within_constraint(
        "https://example.com/x", site=None, original_url=original
    )
    # 跨域跳转拒绝
    assert not final_url_within_constraint(
        "https://evil.example.org/x", site=None, original_url=original
    ), "general 模式下跨域重定向必须拒绝"


def test_verify_exact_url_page_accepts_valid_page() -> None:
    url = "https://www.postgresql.org/docs/16/ddl-rowsecurity.html"
    client = FakeHttpClient(
        routes={url: FakeResponse(text=f"<body><article>{LONG_TEXT}</article></body>", url=url)}
    )
    text = asyncio.run(verify_exact_url_page(client, url, site="postgresql.org"))
    assert text is not None and "行级安全策略" in text


def test_verify_exact_url_page_rejects_failures() -> None:
    valid_url = "https://www.postgresql.org/docs/16/a.html"
    # 404 → None
    client_404 = FakeHttpClient(routes={}, not_found={valid_url})
    assert asyncio.run(verify_exact_url_page(client_404, valid_url, site="postgresql.org")) is None
    # 跨域重定向 → None
    client_redirect = FakeHttpClient(
        routes={valid_url: FakeResponse(text=f"<body>{LONG_TEXT}</body>", url="https://evil.example.com/x")}
    )
    assert asyncio.run(verify_exact_url_page(client_redirect, valid_url, site="postgresql.org")) is None
    # SPA 骨架页 → None
    client_spa = FakeHttpClient(
        routes={valid_url: FakeResponse(text="<body><div>Loading...</div></body>", url=valid_url)}
    )
    assert asyncio.run(verify_exact_url_page(client_spa, valid_url, site="postgresql.org")) is None


def test_fetch_single_page_general_mode_redirect_check() -> None:
    url = "https://www.example.com/blog/post"
    client = FakeHttpClient(
        routes={url: FakeResponse(text=f"<body>{LONG_TEXT}</body>", url="https://evil.example.org/x")}
    )
    _, text = asyncio.run(_fetch_single_page(client, url, site=None))
    assert text == "", "general 模式多来源 GET 也必须校验重定向终点"


def test_route_after_direct_web_branches() -> None:
    assert route_after_direct_web({"error_decision": None}) == "build_context"
    no_result = classify_agent_error(NoSearchResultError("Web Search 未返回可用结果"))
    assert no_result.kind == "no_search_result" and no_result.action == "final_answer"
    assert route_after_direct_web({"error_decision": no_result}) == "final_error_answer"
    external = classify_agent_error(
        ExternalServiceError("Direct Web 搜索参数生成失败"), tool_name="web_search"
    )
    assert external.kind == "tool_error" and external.action == "fail_request"
    assert route_after_direct_web({"error_decision": external}) == "fail_request"


def test_compiled_graph_has_direct_web_error_edges() -> None:
    """通过编译图验证 call_direct_web 的三分支契约（AGENTS.md 规则 8）。"""

    from fast_app.core.config import Settings
    from fast_app.graph.rag_agent.rag_agent_builder import build_rag_agent_graph

    class Stub:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __call__(self, *args, **kwargs):
            return []

    graph = build_rag_agent_graph(
        settings=Settings(),
        vector_retriever=Stub(),
        keyword_retriever=Stub(),
        llm_client=Stub(),
        reranker=Stub(),
        rerank_top_k=3,
    )
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("call_direct_web", "build_context") in edges
    assert ("call_direct_web", "final_error_answer") in edges
    assert ("call_direct_web", "fail_request") in edges


if __name__ == "__main__":
    test_final_url_constraint_site_mode()
    test_final_url_constraint_general_mode()
    test_verify_exact_url_page_accepts_valid_page()
    test_verify_exact_url_page_rejects_failures()
    test_fetch_single_page_general_mode_redirect_check()
    test_route_after_direct_web_branches()
    test_compiled_graph_has_direct_web_error_edges()
    print("test_direct_web_redirect_error: 全部通过")
