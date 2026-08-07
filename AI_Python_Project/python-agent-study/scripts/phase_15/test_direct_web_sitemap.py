"""离线验证 Direct Web sitemap 救援的解析、排序和中文回退逻辑。"""

import asyncio

import httpx

from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan
from fast_app.services.rag.direct_web_sitemap import (
    _official_sitemap_candidates,
    _rank_sitemap_candidates,
    _sitemap_needles,
)


class FakeResponse:
    """模拟 httpx.Response 的最小接口。"""

    def __init__(self, content: bytes, *, status_code: int = 200) -> None:
        self.content = content
        self.text = content.decode("utf-8")
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class FakeHttpClient:
    """按 URL 路由返回预置响应；未配置或标记 404 的地址抛出 HTTPError。"""

    def __init__(self, routes: dict[str, bytes], *, not_found: set[str] | None = None) -> None:
        self._routes = routes
        self._not_found = not_found or set()
        self.requested: list[str] = []

    async def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        self.requested.append(url)
        if url in self._not_found:
            raise httpx.HTTPError("HTTP 404")
        content = self._routes.get(url)
        if content is None:
            raise httpx.HTTPError("HTTP 404")
        return FakeResponse(content)


def build_official_plan(**overrides: object) -> DirectWebSearchPlan:
    base: dict[str, object] = {
        "query": "PostgreSQL 16 row level security",
        "count": 5,
        "source_mode": "official",
        "result_strategy": "single_best_page",
        "site": "example.com",
    }
    base.update(overrides)
    return DirectWebSearchPlan(**base)  # type: ignore[arg-type]


def test_rank_prefers_specific_page_over_index() -> None:
    entries = [
        "https://example.com/docs/16/",
        "https://example.com/docs/16/ddl-rowsecurity.html",
        "https://example.com/docs/16/index.html",
        "https://example.com/about/",
    ]
    candidates = _rank_sitemap_candidates(entries, {"docs", "16", "rowsecurity"})
    assert candidates, "泛化词场景必须产出候选"
    # rowsecurity 是稀有词（IDF 权重高），具体页面必须排在 /docs/16/ 泛化首页之前。
    assert candidates[0]["url"] == "https://example.com/docs/16/ddl-rowsecurity.html"
    assert "rowsecurity" in candidates[0]["summary"]
    urls = [item["url"] for item in candidates]
    assert "https://example.com/about/" not in urls


def test_rank_deep_path_tiebreak() -> None:
    entries = [
        "https://example.com/docs/16/",
        "https://example.com/docs/16/admin/failover.html",
    ]
    candidates = _rank_sitemap_candidates(entries, {"docs", "16"})
    assert candidates[0]["url"] == "https://example.com/docs/16/admin/failover.html"


def test_rank_chinese_query_doc_path_fallback() -> None:
    entries = [
        "https://example.com/docs/admin/failover.html",
        "https://example.com/help/faq.html",
        "https://example.com/about/company",
        "https://example.com/pricing",
    ]
    # 纯中文 query 提取不到 ASCII 打分词，走文档目录启发式。
    candidates = _rank_sitemap_candidates(entries, set())
    urls = [item["url"] for item in candidates]
    assert "https://example.com/docs/admin/failover.html" in urls
    assert "https://example.com/help/faq.html" in urls
    assert "https://example.com/about/company" not in urls
    assert "https://example.com/pricing" not in urls
    assert all("doc-path heuristic" in item["summary"] for item in candidates)


def test_rank_empty_entries() -> None:
    assert _rank_sitemap_candidates([], {"docs"}) == []
    assert _rank_sitemap_candidates([], set()) == []


def test_needles_include_url_search_terms() -> None:
    plan = build_official_plan(
        query="查询主备切换的配置",
        required_content_terms=["主备切换"],
        url_search_terms=["failover", "ha"],
    )
    needles = _sitemap_needles(plan)
    assert needles == {"failover", "ha"}


def test_needles_compound_variants() -> None:
    """复合搜索词必须生成省略内部分词的连写变体。

    官方 URL 常用 rowsecurity 而非 rowlevelsecurity，缺变体会
    导致复合词永远无法命中目标页。
    """

    plan = build_official_plan(url_search_terms=["row-level-security"])
    needles = _sitemap_needles(plan)
    assert "rowlevelsecurity" in needles
    assert "rowsecurity" in needles


def test_rank_compound_match_beats_rare_short_token() -> None:
    """命中复合主题词的页面必须排在只命中稀有短词的离题页之前。"""

    entries = [
        "https://example.com/docs/16/applevel-consistency.html",
        "https://example.com/docs/16/ddl-rowsecurity.html",
    ]
    candidates = _rank_sitemap_candidates(entries, {"rowsecurity", "level", "16"})
    assert candidates[0]["url"] == "https://example.com/docs/16/ddl-rowsecurity.html"


def test_rank_dedupe_substring_tokens() -> None:
    """rowsecurity 与 row/security 同时命中时只计复合词。"""

    entries = ["https://example.com/docs/16/ddl-rowsecurity.html"]
    candidates = _rank_sitemap_candidates(entries, {"rowsecurity", "row", "security"})
    assert "rowsecurity" in candidates[0]["summary"]
    assert "row" not in candidates[0]["summary"].replace("rowsecurity", "")


async def test_fragment_prefilter_excludes_wrong_version() -> None:
    """片段约束预筛：错误版本与伪片段页面不得进入候选。"""

    urlset = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/docs/16/rowsecurity.html</loc></url>
      <url><loc>https://example.com/docs/15/rowsecurity.html</loc></url>
      <url><loc>https://example.com/docs/165/rowsecurity.html</loc></url>
    </urlset>"""
    client = FakeHttpClient({"https://example.com/sitemap.xml": urlset})
    plan = build_official_plan(required_url_fragments=["16"])
    candidates = await _official_sitemap_candidates(client, plan=plan)
    urls = [item["url"] for item in candidates]
    assert urls == ["https://example.com/docs/16/rowsecurity.html"]


async def test_urlset_parsing_with_namespace() -> None:
    urlset = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/docs/16/rowsecurity.html</loc></url>
      <url><loc>https://evil.example.net/phish.html</loc></url>
      <url><loc>http://example.com/insecure.html</loc></url>
    </urlset>"""
    client = FakeHttpClient({"https://example.com/sitemap.xml": urlset})
    plan = build_official_plan()
    candidates = await _official_sitemap_candidates(client, plan=plan)
    urls = [item["url"] for item in candidates]
    assert urls == ["https://example.com/docs/16/rowsecurity.html"]
    assert all("evil.example.net" not in url for url in urls)


async def test_sitemapindex_expands_one_level() -> None:
    index = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-docs.xml</loc></sitemap>
      <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
    </sitemapindex>"""
    docs_map = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/docs/16/rowsecurity.html</loc></url>
    </urlset>"""
    blog_map = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/blog/release-16</loc></url>
    </urlset>"""
    client = FakeHttpClient(
        {
            "https://example.com/sitemap.xml": index,
            "https://example.com/sitemap-docs.xml": docs_map,
            "https://example.com/sitemap-blog.xml": blog_map,
        }
    )
    plan = build_official_plan()
    candidates = await _official_sitemap_candidates(client, plan=plan)
    urls = [item["url"] for item in candidates]
    # 索引展开后必须是真实页面；子 sitemap 的 XML 地址绝不能成为候选。
    assert urls, "sitemapindex 展开必须产出页面候选"
    assert all(not url.endswith(".xml") for url in urls)
    assert "https://example.com/docs/16/rowsecurity.html" in urls


async def test_robots_txt_fallback() -> None:
    robots = b"User-agent: *\nSitemap: https://example.com/custom/map.xml\n"
    custom_map = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/docs/16/rowsecurity.html</loc></url>
    </urlset>"""
    client = FakeHttpClient(
        {
            "https://example.com/robots.txt": robots,
            "https://example.com/custom/map.xml": custom_map,
        },
        not_found={"https://example.com/sitemap.xml"},
    )
    plan = build_official_plan()
    candidates = await _official_sitemap_candidates(client, plan=plan)
    urls = [item["url"] for item in candidates]
    assert urls == ["https://example.com/docs/16/rowsecurity.html"]


async def test_all_sources_fail_returns_empty() -> None:
    client = FakeHttpClient({}, not_found={"https://example.com/sitemap.xml"})
    plan = build_official_plan()
    candidates = await _official_sitemap_candidates(client, plan=plan)
    assert candidates == []


async def test_no_site_returns_empty() -> None:
    client = FakeHttpClient({})
    plan = build_official_plan(source_mode="general", site=None)
    candidates = await _official_sitemap_candidates(client, plan=plan)
    assert candidates == []


def main() -> None:
    test_rank_prefers_specific_page_over_index()
    test_rank_deep_path_tiebreak()
    test_rank_chinese_query_doc_path_fallback()
    test_rank_empty_entries()
    test_needles_include_url_search_terms()
    test_needles_compound_variants()
    test_rank_compound_match_beats_rare_short_token()
    test_rank_dedupe_substring_tokens()
    asyncio.run(test_fragment_prefilter_excludes_wrong_version())
    asyncio.run(test_urlset_parsing_with_namespace())
    asyncio.run(test_sitemapindex_expands_one_level())
    asyncio.run(test_robots_txt_fallback())
    asyncio.run(test_all_sources_fail_returns_empty())
    asyncio.run(test_no_site_returns_empty())
    print("direct_web_sitemap=passed")


if __name__ == "__main__":
    main()
