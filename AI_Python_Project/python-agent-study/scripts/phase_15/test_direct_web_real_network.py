"""真实网络验证 Direct Web 修复项：LLM 规划、Bocha 搜索、过滤降级、
exact_url 预验证、重定向约束、并发全文读取与错误分类分流。

需要外网、BOCHA_API_KEY 与 LLM 配置；不做任何写操作。
"""

import asyncio

import httpx

from fast_app.core.config import Settings
from fast_app.graph.rag_agent.rag_agent_nodes import (
    _hard_match_direct_web_plan,
    _matches_direct_web_plan,
    _relax_content_term_results,
    create_call_direct_web_node,
)
from fast_app.agents.tools.web_search_tools import search_web_with_bocha
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.exceptions import ExternalServiceError
from fast_app.services.rag.direct_web_page_fetch import (
    fetch_direct_web_page_texts,
    final_url_within_constraint,
    verify_exact_url_page,
)
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner


QUESTION = "请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。"


async def step1_planner(settings: Settings):
    planner = DirectWebSearchPlanner(settings)
    plan = await planner.plan(question=QUESTION, count=5)
    print(f"[1] planner 输出: query={plan.query!r}")
    print(f"    source_mode={plan.source_mode} site={plan.site} strategy={plan.result_strategy}")
    print(f"    required_url_fragments={plan.required_url_fragments}")
    print(f"    required_content_terms={plan.required_content_terms}")
    print(f"    url_search_terms={plan.url_search_terms}")
    print(f"    exact_url={plan.exact_url}")
    return planner, plan


async def step2_bocha_and_filters(settings: Settings, plan) -> list:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        raw = await search_web_with_bocha(
            settings=settings,
            http_client=client,
            query=plan.query,
            count=plan.count,
            site=plan.site,
        )
    strict = [item for item in raw if _matches_direct_web_plan(item, plan=plan)]
    hard_only = [item for item in raw if _hard_match_direct_web_plan(item, plan=plan)]
    relaxed = _relax_content_term_results(raw, strict, plan=plan)
    print(f"[2] Bocha 真实召回 {len(raw)} 条；硬约束通过 {len(hard_only)} 条；"
          f"严格过滤 {len(strict)} 条；主题词降级 {len(relaxed)} 条")
    for item in raw[:5]:
        mark = "严格通过" if item in strict else ("硬约束通过" if item in hard_only else "拒绝")
        print(f"    [{mark}] {item.url}")
    assert raw, "真实 Bocha 搜索应当返回结果"
    return raw


async def step3_exact_url_verification(settings: Settings, plan) -> None:
    site = plan.site or "postgresql.org"
    real_url = f"https://www.{site}/docs/current/ddl-rowsecurity.html"
    hallucinated_url = f"https://www.{site}/docs/16/nonexistent-row-security-page-xyz-98765.html"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        real_text = await verify_exact_url_page(client, real_url, site=site)
        fake_text = await verify_exact_url_page(client, hallucinated_url, site=site)
    print(f"[3] exact_url 预验证: 真实页面 -> {'通过, 正文 ' + str(len(real_text)) + ' 字符' if real_text else '未通过'}")
    print(f"    幻觉页面 {hallucinated_url}")
    print(f"              -> {'被拒绝（None）' if fake_text is None else '异常：竟然通过'}")
    assert real_text, "真实官方页面应当通过预验证并提取到正文"
    assert fake_text is None, "幻觉 URL 必须被预验证拒绝（404/空正文）"


async def step4_fulltext_and_redirect(settings: Settings, raw: list, plan) -> None:
    urls = [item.url for item in raw if item.url.startswith("https")][:3]
    assert urls, "需要至少一个 HTTPS 候选用于全文读取"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        responses = {
            url: await client.get(url, timeout=10.0) for url in urls
        }
        fetched = dict(
            await fetch_direct_web_page_texts(client, urls, site=plan.site)
        )
    print(f"[4] 并发全文读取 {len(urls)} 页：")
    for url in urls:
        response = responses[url]
        final_url = str(response.url)
        within = final_url_within_constraint(
            final_url, site=plan.site, original_url=url
        )
        text = fetched.get(url, "")
        print(f"    {url}")
        print(f"      最终地址={final_url} 约束内={within} 正文={len(text)} 字符")
        assert within, "真实候选的重定向终点应当仍在约束内"
    assert any(len(text) > 0 for text in fetched.values()), "至少一页应提取到正文"


async def step5_error_classification(settings: Settings) -> None:
    class BrokenPlanner:
        async def plan(self, *, question, count, langchain_config=None):
            raise ExternalServiceError("Direct Web 搜索参数生成失败")

    node = create_call_direct_web_node(settings=settings, search_planner=BrokenPlanner())
    result = await node(
        {"query": QUESTION, "tool_call_count": 0, "operation": "chat", "top_k": 3}
    )
    decision = result.get("error_decision")
    print(f"[5] 节点错误分类: tool_error={result.get('tool_error')} "
          f"kind={decision.kind} action={decision.action} code={decision.error_code}")
    assert decision is not None and decision.kind == "tool_error"
    assert decision.action == "fail_request"
    assert result.get("docs") is None or "docs" not in result


async def step6_full_node(settings: Settings) -> None:
    """完整节点端到端：planner → Bocha → 过滤 → 选择器 → GET → docs。"""

    node = create_call_direct_web_node(settings=settings)
    state = build_rag_agent_initial_state(
        RagChatRequest(query=QUESTION, mode="hybrid", top_k=3),
        operation="run",
    )
    update = await node(state)
    decision = update.get("error_decision")
    assert decision is None, f"完整节点不应进入错误分支: {decision}"
    docs = update["docs"]
    print(f"[6] 完整节点端到端：产出 {len(docs)} 份文档")
    assert docs, "完整节点应当产出至少一份文档"
    for index, doc in enumerate(docs, start=1):
        url = doc.metadata.get("url") if doc.metadata else None
        print(f"    文档{index}: url={url}")
        print(f"      title={doc.title}")
        print(f"      正文长度={len(doc.content)} 字符")
        print(f"      正文前200字: {doc.content[:200]}")
    top_url = str((docs[0].metadata or {}).get("url") or docs[0].title)
    print(f"    首选文档 URL: {top_url}")
    assert len(docs[0].content) >= 200, "首选文档正文应为有效全文而非摘要回退"


async def main() -> None:
    settings = Settings()
    assert settings.bocha_api_key, "BOCHA_API_KEY 未配置，无法执行真实网络测试"
    print("=" * 60)
    print("Direct Web 修复真实网络验证")
    print("=" * 60)
    planner, plan = await step1_planner(settings)
    raw = await step2_bocha_and_filters(settings, plan)
    await step3_exact_url_verification(settings, plan)
    await step4_fulltext_and_redirect(settings, raw, plan)
    await step5_error_classification(settings)
    await step6_full_node(settings)
    print("=" * 60)
    print("真实网络验证全部通过")


if __name__ == "__main__":
    asyncio.run(main())
