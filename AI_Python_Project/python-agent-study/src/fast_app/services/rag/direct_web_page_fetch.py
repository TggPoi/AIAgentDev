"""Direct Web 多来源分支的页面全文读取：并发、有界、逐文档回退。

节点过滤出合格搜索结果后，用本模块并发读取前 N 页并提取正文。
单页失败（网络错误、SPA 空正文、重定向后域名脱离 site 约束）
只返回空正文，由调用方回退该文档的搜索摘要；本模块永不抛异常。
"""

import asyncio
from urllib.parse import urlparse

import httpx

from fast_app.services.rag.direct_web_page_text import extract_page_text

# 多来源分支最多读取全文的页面数，超出部分保持搜索摘要。
DIRECT_WEB_FULLTEXT_MAX_PAGES = 3
DIRECT_WEB_FULLTEXT_TIMEOUT_SECONDS = 10.0


def _final_url_within_site(final_url: str, site: str) -> bool:
    """重定向后的最终 URL 域名必须等于 site 或属于其子域名。"""

    hostname = (urlparse(final_url).hostname or "").lower()
    lowered_site = site.lower()
    return hostname == lowered_site or hostname.endswith(f".{lowered_site}")


def _hostname_site_root(hostname: str) -> str:
    """取主机名的最后两段作为注册根域（如 www.example.com → example.com）。

    启发式规则，不识别 co.uk 等多段公共后缀；重定向约束只用于
    阻止完全跨站跳转，该精度在可接受范围内。
    """

    parts = hostname.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else hostname


def final_url_within_constraint(
    final_url: str, *, site: str | None, original_url: str
) -> bool:
    """重定向终点的域名约束。

    有 site 约束时最终域名必须在 site 内；无 site（general 模式）时
    最终域名必须与原候选同属一个注册根域，允许同根域内的
    子域、父域或兄弟子域跳转。
    """

    hostname = (urlparse(final_url).hostname or "").lower()
    if not hostname:
        return False
    if site:
        return _final_url_within_site(final_url, site)
    original_host = (urlparse(original_url).hostname or "").lower()
    if not original_host:
        return False
    return _hostname_site_root(hostname) == _hostname_site_root(original_host)


async def verify_exact_url_page(
    http_client,
    url: str,
    *,
    site: str | None,
) -> str | None:
    """入池前验证 planner 声明的 exact_url 真实可用。

    通过条件：HTTP 2xx、重定向终点仍在约束内、提取到有效正文；
    任一不满足返回 None，该 URL 不入候选池；通过则返回正文供复用。
    """

    try:
        response = await http_client.get(
            url, timeout=DIRECT_WEB_FULLTEXT_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    if not final_url_within_constraint(
        str(response.url), site=site, original_url=url
    ):
        return None
    text = extract_page_text(response.text)
    return text or None


async def _fetch_single_page(
    http_client,
    url: str,
    *,
    site: str | None,
) -> tuple[str, str]:
    try:
        response = await http_client.get(
            url, timeout=DIRECT_WEB_FULLTEXT_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        if not final_url_within_constraint(
            str(response.url), site=site, original_url=url
        ):
            return (url, "")
        return (url, extract_page_text(response.text))
    except httpx.HTTPError:
        return (url, "")


async def fetch_direct_web_page_texts(
    http_client,
    page_urls: list[str],
    *,
    site: str | None,
) -> list[tuple[str, str]]:
    """并发读取 URL 全文并提取正文，返回 (请求 URL, 正文) 列表。"""

    tasks = [
        _fetch_single_page(http_client, url, site=site)
        for url in page_urls[:DIRECT_WEB_FULLTEXT_MAX_PAGES]
    ]
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))
