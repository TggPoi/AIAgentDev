"""增强 Web 检索共享服务的离线回归测试。

覆盖 execute_enhanced_web_search 主流程，以及增强/fallback 双路径
共用的载荷构造器契约。
"""

from __future__ import annotations

import asyncio

import fast_app.services.rag.enhanced_web_search as enhanced_module
from fast_app.agents.tools.web_search_tools import WebSearchResult
from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import NoSearchResultError
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan


class FakeEnhancedPlanner:
    """记录入参并按固定策略返回规划与选择的测试替身。"""

    def __init__(self, plan: DirectWebSearchPlan, selected_url: str | None = None):
        self._plan = plan
        self._selected_url = selected_url
        self.plan_questions: list[str] = []
        self.last_candidates: list[dict[str, str]] = []

    async def plan(self, *, question, count, langchain_config=None):
        self.plan_questions.append(question)
        return self._plan.model_copy(update={"count": count})

    async def select_candidate_url(
        self, *, question, plan, candidates, langchain_config=None
    ):
        self.last_candidates = candidates
        return self._selected_url


def _result(url: str, title: str = "", snippet: str = "", summary: str = "") -> WebSearchResult:
    return WebSearchResult(
        title=title or url, url=url, snippet=snippet, summary=summary
    )


async def _run_with_fakes(planner, raw_results, *, fetch_texts=None, forced_site=None):
    """patch bocha 与全文抓取后执行服务入口。"""

    original_bocha = enhanced_module.search_web_with_bocha
    original_fetch = enhanced_module.fetch_direct_web_page_texts
    calls: dict[str, object] = {}

    async def fake_bocha(**kwargs):
        calls.update(kwargs)
        return raw_results

    async def fake_fetch(http_client, page_urls, *, site):
        return list(fetch_texts or [])

    enhanced_module.search_web_with_bocha = fake_bocha
    enhanced_module.fetch_direct_web_page_texts = fake_fetch
    try:
        docs = await enhanced_module.execute_enhanced_web_search(
            settings=Settings(),
            planner=planner,
            question="测试问题",
            top_k=3,
            forced_site=forced_site,
        )
    finally:
        enhanced_module.search_web_with_bocha = original_bocha
        enhanced_module.fetch_direct_web_page_texts = original_fetch
    return docs, calls


async def step_multiple_sources_snippet_fallback() -> None:
    """multiple_sources 且正文抓取为空时，文档回退为摘要拼接。"""

    plan = DirectWebSearchPlan(
        query="postgresql row security", count=3, result_strategy="multiple_sources"
    )
    raw = [
        _result("https://example.com/a", snippet="snippet a"),
        _result("https://example.com/b", snippet="snippet b"),
    ]
    docs, _ = await _run_with_fakes(FakeEnhancedPlanner(plan), raw)
    assert len(docs) == 2
    assert "snippet a" in docs[0].content
    assert docs[0].metadata["url"] == "https://example.com/a"
    print("step_multiple_sources_snippet_fallback OK")


async def step_multiple_sources_fulltext() -> None:
    """multiple_sources 正文抓取成功时，文档内容为 URL 加全文。"""

    plan = DirectWebSearchPlan(
        query="postgresql row security", count=3, result_strategy="multiple_sources"
    )
    raw = [_result("https://example.com/a", snippet="snippet a")]
    docs, _ = await _run_with_fakes(
        FakeEnhancedPlanner(plan),
        raw,
        fetch_texts=[("https://example.com/a", "完整正文")],
    )
    assert docs[0].content == "https://example.com/a\n完整正文"
    print("step_multiple_sources_fulltext OK")


async def step_forced_site_and_hard_filter() -> None:
    """forced_site 补入空 site 计划，且域名硬约束过滤离站候选。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="multiple_sources",
        required_url_fragments=["16"],
    )
    raw = [
        _result("https://postgresql.org/docs/16/x.html", snippet="row security"),
        _result("https://other.com/docs/16/y.html", snippet="row security"),
    ]
    planner = FakeEnhancedPlanner(plan)
    docs, calls = await _run_with_fakes(planner, raw, forced_site="postgresql.org")
    assert calls["site"] == "postgresql.org"
    assert len(docs) == 1
    assert docs[0].metadata["url"] == "https://postgresql.org/docs/16/x.html"
    print("step_forced_site_and_hard_filter OK")


async def step_off_topic_raises() -> None:
    """general 模式无 site 且主题词全不命中时抛 NoSearchResultError。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="multiple_sources",
        required_content_terms=["row security"],
    )
    raw = [_result("https://example.com/unrelated", snippet="无关内容")]
    try:
        await _run_with_fakes(FakeEnhancedPlanner(plan), raw)
    except NoSearchResultError:
        print("step_off_topic_raises OK")
        return
    raise AssertionError("离题候选应触发 NoSearchResultError")


async def step_single_best_page_candidate_pool() -> None:
    """盲区 A：single_best_page 候选池保留 URL 片段硬约束。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="single_best_page",
        site="example.org",
        required_url_fragments=["16"],
    )
    raw = [
        _result("https://example.org/docs/16/a.html", snippet="row security"),
        _result("https://example.org/docs/15/b.html", snippet="row security"),
    ]
    planner = FakeEnhancedPlanner(plan, selected_url=None)
    docs, _ = await _run_with_fakes(planner, raw)
    assert all("16" in item["url"] for item in planner.last_candidates)
    assert len(docs) == 1
    assert docs[0].metadata["url"] == "https://example.org/docs/16/a.html"
    print("step_single_best_page_candidate_pool OK")


_PAYLOAD_KEYS = {"title", "url", "site_name", "content"}


async def step_payload_contract() -> None:
    """增强路径载荷构造器：key 集合与 content 截断是固化契约。"""

    doc = RetrievedDoc(
        id="web:1",
        content="x" * 20,
        score=1.0,
        source="web_search",
        title="标题",
        metadata={"url": "https://postgresql.org/a", "site_name": "postgresql.org"},
    )
    payload = enhanced_module.build_web_search_payload([doc], content_limit=10)
    assert payload[0].keys() == _PAYLOAD_KEYS
    assert payload[0]["url"] == "https://postgresql.org/a"
    assert payload[0]["content"] == "x" * 10
    print("step_payload_contract OK")


async def step_fallback_payload_contract() -> None:
    """fallback 路径载荷构造器：与增强路径 key 集合完全一致，content 拼接自摘要字段。"""

    results = [
        _result(
            "https://postgresql.org/docs/16/x.html",
            title="Row Security",
            snippet="snippet text",
            summary="summary text",
        )
    ]
    payload = enhanced_module.build_payload_from_web_search_results(
        results, content_limit=8000
    )
    assert payload[0].keys() == _PAYLOAD_KEYS
    assert payload[0]["url"] == "https://postgresql.org/docs/16/x.html"
    assert payload[0]["site_name"] == ""
    assert "snippet text" in payload[0]["content"]
    assert "summary text" in payload[0]["content"]
    print("step_fallback_payload_contract OK")


async def main() -> None:
    await step_multiple_sources_snippet_fallback()
    await step_multiple_sources_fulltext()
    await step_forced_site_and_hard_filter()
    await step_off_topic_raises()
    await step_single_best_page_candidate_pool()
    await step_payload_contract()
    await step_fallback_payload_contract()
    print("test_enhanced_web_search ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
