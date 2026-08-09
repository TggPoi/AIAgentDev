"""离线验证 Direct Web 主题词有界降级与多来源并发全文读取。"""

import asyncio

import httpx

from fast_app.graph.rag_agent.rag_agent_nodes import (
    _content_term_hit_count,
    _hard_match_direct_web_plan,
    _matches_direct_web_plan,
    _needs_sitemap_rescue,
    _relax_content_term_results,
)
from fast_app.services.rag.direct_web_page_fetch import (
    DIRECT_WEB_FULLTEXT_MAX_PAGES,
    fetch_direct_web_page_texts,
)
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan


class SearchResult:
    """模拟 Bocha 搜索结果的最小接口。"""

    def __init__(self, *, url: str, title: str = "", snippet: str = "", summary: str = "") -> None:
        self.url = url
        self.title = title
        self.snippet = snippet
        self.summary = summary


class FakeResponse:
    def __init__(self, *, text: str, url: str, status_code: int = 200) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class FakeHttpClient:
    """按 URL 路由返回预置响应；记录实际请求顺序用于上界断言。"""

    def __init__(self, routes: dict[str, FakeResponse], *, not_found: set[str] = frozenset()) -> None:
        self.routes = routes
        self.not_found = not_found
        self.requested: list[str] = []

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        self.requested.append(url)
        if url in self.not_found:
            raise httpx.HTTPError(f"HTTP 404 for {url}")
        response = self.routes.get(url)
        if response is None:
            raise httpx.HTTPError(f"no route for {url}")
        return response


def _plan(**overrides) -> DirectWebSearchPlan:
    payload = {
        "query": "postgresql row security",
        "count": 5,
        "source_mode": "official",
        "result_strategy": "single_best_page",
        "site": "postgresql.org",
        "required_url_fragments": [],
        "required_content_terms": [],
        "url_search_terms": [],
    }
    payload.update(overrides)
    return DirectWebSearchPlan(**payload)


LONG_TEXT = (
    "PostgreSQL 行级安全策略允许数据库管理员为表配置访问策略，"
    "使得每个用户在执行查询时只能看到符合策略条件的行。" * 5
)


def test_hard_match_domain_and_fragments() -> None:
    plan = _plan(required_url_fragments=["16"])
    subdomain = SearchResult(url="https://www.postgresql.org/docs/16/ddl.html")
    other_domain = SearchResult(url="https://evil.example.com/docs/16/ddl.html")
    missing_fragment = SearchResult(url="https://www.postgresql.org/docs/15/ddl.html")
    assert _hard_match_direct_web_plan(subdomain, plan=plan)
    assert not _hard_match_direct_web_plan(other_domain, plan=plan)
    assert not _hard_match_direct_web_plan(missing_fragment, plan=plan)


def test_content_term_hit_count() -> None:
    plan = _plan(required_content_terms=["row security", "policy"])
    result = SearchResult(
        url="https://www.postgresql.org/docs/16/ddl-rowsecurity.html",
        title="Row Security Policies",
        snippet="row security enables policy enforcement",
    )
    assert _content_term_hit_count(result, plan=plan) == 2
    partial = SearchResult(
        url="https://www.postgresql.org/docs/16/ddl-rowsecurity.html",
        title="Row Security Policies",
        snippet="no theme words here",
    )
    assert _content_term_hit_count(partial, plan=plan) == 1


def test_strict_match_requires_all_terms() -> None:
    plan = _plan(required_content_terms=["row security", "policy"])
    full = SearchResult(
        url="https://www.postgresql.org/docs/16/ddl.html",
        title="Row Security Policies",
        snippet="row security policy",
    )
    partial = SearchResult(
        url="https://www.postgresql.org/docs/16/ddl.html",
        title="Row Security",
        snippet="nothing else",
    )
    assert _matches_direct_web_plan(full, plan=plan)
    assert not _matches_direct_web_plan(partial, plan=plan)


def test_relaxation_ranks_by_hit_count_when_site_present() -> None:
    plan = _plan(required_content_terms=["row security", "policy"])
    two_hits = SearchResult(
        url="https://www.postgresql.org/a",
        title="row security policy guide",
    )
    one_hit = SearchResult(
        url="https://www.postgresql.org/b",
        title="row security overview",
    )
    zero_hit = SearchResult(url="https://www.postgresql.org/c", title="changelog")
    wrong_domain = SearchResult(url="https://evil.example.com/d", title="row security policy")
    strict_results: list = []
    raw = [zero_hit, wrong_domain, one_hit, two_hits]
    relaxed = _relax_content_term_results(raw, strict_results, plan=plan)
    assert [item.url for item in relaxed] == [
        "https://www.postgresql.org/a",
        "https://www.postgresql.org/b",
        "https://www.postgresql.org/c",
    ], "应按命中数排序且域名硬约束仍生效"


def test_relaxation_disabled_without_site_or_strict_hits() -> None:
    terms = ["row security"]
    raw = [SearchResult(url="https://x.com/a", title="row security")]
    # general 模式：site 为空不降级
    general_plan = _plan(source_mode="general", site=None, required_content_terms=terms)
    assert _relax_content_term_results(raw, [], plan=general_plan) == []
    # 严格集非空时不降级
    site_plan = _plan(required_content_terms=terms)
    assert _relax_content_term_results(raw, raw[:1], plan=site_plan) == []
    # 无主题词时不降级
    no_terms_plan = _plan(required_content_terms=[])
    assert _relax_content_term_results(raw, [], plan=no_terms_plan) == []


def test_fetch_fulltext_concurrent_with_partial_failure() -> None:
    url_ok = "https://www.postgresql.org/docs/16/ddl-rowsecurity.html"
    url_fail = "https://www.postgresql.org/docs/16/broken.html"
    client = FakeHttpClient(
        routes={url_ok: FakeResponse(text=f"<body><article>{LONG_TEXT}</article></body>", url=url_ok)},
        not_found={url_fail},
    )
    results = dict(
        asyncio.run(
            fetch_direct_web_page_texts(
                client, [url_ok, url_fail], site="postgresql.org"
            )
        )
    )
    assert "行级安全策略" in results[url_ok]
    assert results[url_fail] == "", "失败页应返回空正文触发摘要回退"


def test_fetch_rejects_cross_domain_redirect() -> None:
    url = "https://www.postgresql.org/docs/16/ddl.html"
    client = FakeHttpClient(
        routes={
            url: FakeResponse(
                text=f"<body>{LONG_TEXT}</body>",
                url="https://evil.example.com/phish",
            )
        }
    )
    results = dict(
        asyncio.run(fetch_direct_web_page_texts(client, [url], site="postgresql.org"))
    )
    assert results[url] == "", "重定向脱离 site 约束后正文必须无效"


def test_fetch_cap_limits_page_count() -> None:
    urls = [f"https://www.postgresql.org/p{i}.html" for i in range(5)]
    client = FakeHttpClient(
        routes={
            url: FakeResponse(text=f"<body>{LONG_TEXT}</body>", url=url)
            for url in urls
        }
    )
    asyncio.run(fetch_direct_web_page_texts(client, urls, site="postgresql.org"))
    assert len(client.requested) == DIRECT_WEB_FULLTEXT_MAX_PAGES == 3


def test_sitemap_rescue_decision() -> None:
    """盲区 B 回归：救援触发条件从候选全空扩展为主题零命中。"""

    plan = _plan(
        required_url_fragments=["16"],
        required_content_terms=["row level security"],
    )
    strict_hit = SearchResult(
        url="https://www.postgresql.org/docs/16/ddl-rowsecurity.html",
        title="Row Level Security",
    )
    off_topic_hard_match = SearchResult(
        url="https://www.postgresql.org/docs/16/release-16-5.html",
        title="PostgreSQL 16.5 Release Notes",
        snippet="bug fixes and improvements",
    )
    topic_relaxed = SearchResult(
        url="https://www.postgresql.org/docs/16/something.html",
        title="Row Level Security overview",
    )
    # 严格过滤有命中 → 不救援。
    assert not _needs_sitemap_rescue([strict_hit], [], plan=plan)
    # 降级候选主题词命中为 0（只剩离题硬约束候选）→ 救援。
    assert _needs_sitemap_rescue([], [off_topic_hard_match], plan=plan)
    # 降级候选存在主题命中 → 搜索引擎方向正确，不救援。
    assert not _needs_sitemap_rescue([], [topic_relaxed], plan=plan)
    # 候选全空 → 保持原有救援行为。
    assert _needs_sitemap_rescue([], [], plan=plan)
    # 无主题词且严格过滤全拒 → 救援。
    plan_no_terms = _plan(required_url_fragments=["16"])
    assert _needs_sitemap_rescue([], [off_topic_hard_match], plan=plan_no_terms)


if __name__ == "__main__":
    test_hard_match_domain_and_fragments()
    test_content_term_hit_count()
    test_strict_match_requires_all_terms()
    test_relaxation_ranks_by_hit_count_when_site_present()
    test_relaxation_disabled_without_site_or_strict_hits()
    test_sitemap_rescue_decision()
    test_fetch_fulltext_concurrent_with_partial_failure()
    test_fetch_rejects_cross_domain_redirect()
    test_fetch_cap_limits_page_count()
    print("test_direct_web_filter_fetch: 全部通过")
