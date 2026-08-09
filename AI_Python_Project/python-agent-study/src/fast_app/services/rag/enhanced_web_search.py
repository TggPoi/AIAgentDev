"""跨链路共享的增强 Web 检索服务。

把 Direct Web 增强检索策略（Planner 参数规划、域名/片段硬约束过滤、
主题词降级、官方 sitemap 救援、单页候选选择、正文抓取与重定向约束）
收敛为一个可复用执行入口，供 RAG Agent 主链路、Research Worker 链路、
DeepAgent 文档创作链路和 direct 文档任务链路共用，避免各链路直接裸调
Bocha 搜索引擎导致结果质量不可控。

隐私边界不在本模块：各链路负责在调用前把 question 清洗为公开查询；
本模块只对收到的 question 做确定性增强，不做会话或私有数据读取。
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from langchain_core.runnables import RunnableConfig

from fast_app.agents.tools.web_search_tools import search_web_with_bocha
from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import NoSearchResultError
from fast_app.services.rag.direct_web_page_fetch import (
    fetch_direct_web_page_texts,
    final_url_within_constraint,
    verify_exact_url_page,
)
from fast_app.services.rag.direct_web_page_text import extract_page_text
from fast_app.services.rag.direct_web_search_planner import (
    DirectWebSearchPlan,
    DirectWebSearchPlanner,
)
from fast_app.services.rag.direct_web_sitemap import _official_sitemap_candidates


logger = get_logger(__name__)

# 主题词降级时最多保留的候选数：域名/片段硬约束仍然生效，主题词仅作排序信号。
_CONTENT_TERM_RELAX_MAX = 3


def _hard_match_direct_web_plan(result, *, plan: DirectWebSearchPlan) -> bool:
    """确定性检查域名与 URL 片段硬约束；site 为空时域名检查跳过。"""

    parsed = urlparse(result.url)
    hostname = (parsed.hostname or "").lower()
    site = (plan.site or "").lower()
    if site and hostname != site and not hostname.endswith(f".{site}"):
        return False
    lowered_url = result.url.lower()
    return not any(
        item.lower() not in lowered_url for item in plan.required_url_fragments
    )


def _content_term_hit_count(result, *, plan: DirectWebSearchPlan) -> int:
    """统计主题词在标题、摘要和 summary 中的命中数量。"""

    searchable = " ".join(
        (result.title, result.snippet, result.summary)
    ).lower()
    return sum(
        1 for item in plan.required_content_terms if item.lower() in searchable
    )


def _matches_direct_web_plan(result, *, plan: DirectWebSearchPlan) -> bool:
    """严格过滤：硬约束加全部主题词命中。"""

    if not _hard_match_direct_web_plan(result, plan=plan):
        return False
    return _content_term_hit_count(result, plan=plan) == len(
        plan.required_content_terms
    )


def _relax_content_term_results(
    raw_results,
    strict_results: list,
    *,
    plan: DirectWebSearchPlan,
) -> list:
    """严格过滤全拒且存在域名硬约束时，把主题词降级为排序信号。

    仅 site 非空时启用（域名约束仍强制生效）；general 模式无 site 时
    保持原有的空结果报错行为，不做无约束降级。
    """

    if strict_results or not plan.site or not plan.required_content_terms:
        return []
    relaxed = sorted(
        (
            item
            for item in raw_results
            if _hard_match_direct_web_plan(item, plan=plan)
        ),
        key=lambda item: _content_term_hit_count(item, plan=plan),
        reverse=True,
    )[:_CONTENT_TERM_RELAX_MAX]
    if relaxed:
        logger.warning(
            "direct_web_content_terms_relaxed %s",
            format_log_fields(
                site=plan.site,
                raw_count=len(raw_results),
                relaxed_count=len(relaxed),
            ),
        )
    return relaxed


def _needs_sitemap_rescue(
    strict_results: list, relaxed_results: list, *, plan: DirectWebSearchPlan
) -> bool:
    """判断是否需要官方 sitemap 救援。

    触发条件：严格过滤无候选通过，且降级候选的主题词命中数全部为 0。
    这表示搜索引擎只返回了碰巧满足域名/版本硬约束的离题页面，
    目标官方页大概率不在召回池里，需要直接查官网 sitemap 补召回。
    降级候选为空时 all() 返回 True，兼容原有“候选全空即救援”行为。
    """

    if strict_results:
        return False
    return all(
        _content_term_hit_count(item, plan=plan) == 0 for item in relaxed_results
    )


def _build_direct_web_doc(url: str, page_text: str, site: str | None) -> RetrievedDoc:
    """用选中页面的真实正文构造 Web 检索文档。"""

    return RetrievedDoc(
        id="web:1",
        content=f"{url}\n{page_text}",
        score=1.0,
        source="web_search",
        title=url,
        metadata={"url": url, "site_name": site},
        retrieval_sources=["web_search"],
    )


async def execute_enhanced_web_search(
    *,
    settings: Settings,
    planner: DirectWebSearchPlanner,
    question: str,
    top_k: int,
    forced_site: str | None = None,
    plan_langchain_config: RunnableConfig | None = None,
    select_langchain_config: RunnableConfig | None = None,
) -> list[RetrievedDoc]:
    """执行增强 Web 检索主流程，返回带全文或摘要的检索文档。

    - ``question`` 是调用方已完成隐私清洗的公开问题；
    - ``forced_site`` 尊重工具调用方显式传入的站点：仅当 Planner 未规划出
      site 时补入，不覆盖已规划的 site；
    - ``plan_langchain_config`` / ``select_langchain_config`` 是两次 Planner
      LLM 子调用的 trace 配置，由各链路按自己的 trace 策略传入，可为 None；
    - 异常一律外抛，由各调用链路自行决定分类或降级回退。
    """

    plan = await planner.plan(
        question=question,
        count=min(max(top_k, 2), 10),
        langchain_config=plan_langchain_config,
    )
    if forced_site and not plan.site:
        plan = plan.model_copy(update={"site": forced_site})
    direct_doc: RetrievedDoc | None = None
    async with httpx.AsyncClient(follow_redirects=True) as http_client:
        results = []
        fulltext_by_url: dict[str, str] = {}
        raw_results = await search_web_with_bocha(
            settings=settings,
            http_client=http_client,
            query=plan.query,
            count=plan.count,
            site=plan.site,
        )
        strict_results = [
            item
            for item in raw_results
            if _matches_direct_web_plan(item, plan=plan)
        ]
        relaxed_results = _relax_content_term_results(
            raw_results, strict_results, plan=plan
        )
        usable_results = strict_results or relaxed_results
        if plan.result_strategy == "single_best_page":
            # 候选池保留域名与 URL 片段硬约束（用户明确要求的版本/路径
            # 必须在选择阶段继续生效），只把主题词放宽为软信号，
            # 避免错误版本页面进入选择器视野。
            candidate_payload = [
                {
                    "title": item.title,
                    "url": item.url,
                    "summary": item.summary or item.snippet,
                }
                for item in raw_results
                if _matches_direct_web_plan(
                    item,
                    plan=plan.model_copy(
                        update={
                            "required_content_terms": [],
                        }
                    ),
                )
            ]
            if (
                _needs_sitemap_rescue(
                    strict_results, relaxed_results, plan=plan
                )
                and plan.source_mode == "official"
                and plan.site is not None
            ):
                candidate_payload.extend(
                    await _official_sitemap_candidates(http_client, plan=plan)
                )
            exact_url_text: str | None = None
            if plan.exact_url:
                exact_url_text = await verify_exact_url_page(
                    http_client, plan.exact_url, site=plan.site
                )
                if exact_url_text is not None:
                    candidate_payload.append(
                        {
                            "title": plan.exact_url,
                            "url": plan.exact_url,
                            "summary": "planner candidate (verified)",
                        }
                    )
            unique_candidates = list(
                {item["url"]: item for item in candidate_payload}.values()
            )
            selected_url = await planner.select_candidate_url(
                question=question,
                plan=plan,
                candidates=unique_candidates,
                langchain_config=select_langchain_config,
            )
            if selected_url:
                if selected_url == plan.exact_url and exact_url_text:
                    # 复用入池预验证时已读取的正文，避免二次请求。
                    direct_doc = _build_direct_web_doc(
                        selected_url, exact_url_text, plan.site
                    )
                else:
                    try:
                        response = await http_client.get(selected_url, timeout=10.0)
                        response.raise_for_status()
                        if not final_url_within_constraint(
                            str(response.url),
                            site=plan.site,
                            original_url=selected_url,
                        ):
                            # 重定向逃逸约束：丢弃正文，回退过滤后的摘要。
                            direct_doc = None
                        else:
                            page_text = extract_page_text(response.text)
                            if page_text:
                                direct_doc = _build_direct_web_doc(
                                    selected_url, page_text, plan.site
                                )
                        # 正文为空（SPA/骨架页）或重定向逃逸时 direct_doc
                        # 保持 None，复用下方摘要回退，过滤约束仍然生效。
                    except httpx.HTTPError:
                        direct_doc = None
            if direct_doc is None:
                results = usable_results[:1]
        else:
            results = usable_results
            # 多来源分支读取前几页真实全文；单页失败回退该文档摘要。
            fulltext_by_url = dict(
                await fetch_direct_web_page_texts(
                    http_client,
                    [result.url for result in results],
                    site=plan.site,
                )
            )
    docs = [
        RetrievedDoc(
            id=f"web:{index}",
            content=(
                f"{result.url}\n{fulltext_by_url[result.url]}"
                if fulltext_by_url.get(result.url)
                else "\n".join(
                    item
                    for item in (result.title, result.snippet, result.summary, result.url)
                    if item
                )
            ),
            score=1.0,
            source="web_search",
            title=result.title,
            metadata={"url": result.url, "site_name": result.site_name},
            retrieval_sources=["web_search"],
        )
        for index, result in enumerate(results, start=1)
    ]
    if direct_doc is not None:
        docs = [direct_doc]
    if not docs:
        raise NoSearchResultError("Web Search 未返回可用结果")
    return docs


def build_web_search_payload(
    docs: list[RetrievedDoc], *, content_limit: int
) -> list[dict[str, str]]:
    """构造给模型消费的 Web 搜索结果 JSON 载荷。

    返回 key 集合固定为 {title, url, site_name, content}，是 DeepAgent
    Researcher 与 direct 文档工具循环的对外契约；content 为增强链路产出
    的页面全文或摘要拼接，并按 content_limit 确定性截断。
    """

    return [
        {
            "title": doc.title,
            "url": str((doc.metadata or {}).get("url") or doc.title),
            "site_name": str((doc.metadata or {}).get("site_name") or ""),
            "content": doc.content[:content_limit],
        }
        for doc in docs
    ]


def build_payload_from_web_search_results(
    results, *, content_limit: int
) -> list[dict[str, str]]:
    """fallback 路径的载荷构造器：先把 WebSearchResult 转成 RetrievedDoc，
    再经 build_web_search_payload 输出，保证与增强路径 key 集合一致。

    content 用 title/snippet/summary/url 拼接，与增强链路摘要回退的
    内容来源保持一致。
    """

    fallback_docs = [
        RetrievedDoc(
            id=f"web:{index}",
            content="\n".join(
                part
                for part in (item.title, item.snippet, item.summary, item.url)
                if part
            ),
            score=1.0,
            source="web_search",
            title=item.title,
            metadata={"url": item.url, "site_name": item.site_name},
        )
        for index, item in enumerate(results, start=1)
    ]
    return build_web_search_payload(fallback_docs, content_limit=content_limit)


__all__ = [
    "build_payload_from_web_search_results",
    "build_web_search_payload",
    "execute_enhanced_web_search",
]
