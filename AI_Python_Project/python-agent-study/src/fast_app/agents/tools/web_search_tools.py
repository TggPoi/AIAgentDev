from typing import Any

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.exceptions import ExternalServiceError


logger = get_logger(__name__)

WEB_SEARCH_TOOL_NAME = "web_search"


class WebSearchToolInput(BaseModel):
    """互联网搜索工具输入。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="需要搜索的互联网问题或关键词")
    count: int = Field(default=5, ge=1, le=10, description="返回网页结果数量")
    site: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9.-]+$",
        description="可选的可信站点域名；查询官方资料时用于 site: 精确限定，不含协议和路径",
    )


class WebSearchResult(BaseModel):
    """外部搜索结果归一化后的内部模型。"""

    title: str
    url: str
    snippet: str = ""
    summary: str = ""
    site_name: str = ""
    published_at: str | None = None


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    return {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value

    return []


def _pick_first_string(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value

    return ""


def _extract_raw_result_items(payload: dict[str, Any]) -> list[object]:
    """从常见搜索 API 响应形态中提取网页结果列表。

    博查 API 的真实字段以后仍应以官方文档或实际响应为准。
    这里保持边界层兼容：只要响应里出现 data/results、data/webPages/value
    或顶层 results，就能归一化成 WebSearchResult。
    """
    data = _as_dict(payload.get("data"))

    candidates = [
        data.get("results"),
        _as_dict(data.get("webPages")).get("value"),
        payload.get("results"),
        _as_dict(payload.get("webPages")).get("value"),
        payload.get("webPages"),
    ]

    for candidate in candidates:
        items = _as_list(candidate)
        if items:
            return items

    return []


def normalize_web_search_results(payload: dict[str, Any]) -> list[WebSearchResult]:
    """把外部搜索 API 原始 JSON 转成当前工程内部搜索结果模型。"""
    results: list[WebSearchResult] = []

    for raw_item in _extract_raw_result_items(payload):
        item = _as_dict(raw_item)
        title = _pick_first_string(item, "title", "name")
        url = _pick_first_string(item, "url", "link")

        if not title and not url:
            continue

        results.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=_pick_first_string(item, "snippet", "description"),
                summary=_pick_first_string(item, "summary", "content"),
                site_name=_pick_first_string(item, "site_name", "siteName"),
                published_at=_pick_first_string(
                    item,
                    "published_at",
                    "publishedAt",
                    "datePublished",
                )
                or None,
            )
        )

    return results


def summarize_web_search_results(results: list[WebSearchResult]) -> str:
    """把搜索结果格式化成 Agent 容易消费的文本。"""
    if not results:
        return "未搜索到相关网页结果。"

    lines = [f"搜索到 {len(results)} 条网页结果。"]
    for index, result in enumerate(results, start=1):
        details = [
            f"{index}. title={result.title}",
            f"url={result.url}",
        ]
        if result.snippet:
            details.append(f"snippet={result.snippet}")
        if result.summary:
            details.append(f"summary={result.summary}")
        if result.site_name:
            details.append(f"site_name={result.site_name}")
        if result.published_at:
            details.append(f"published_at={result.published_at}")
        lines.append(", ".join(details))

    return "\n".join(lines)


async def search_web_with_bocha(
    *,
    settings: Settings,
    http_client: httpx.AsyncClient,
    query: str,
    count: int,
    site: str | None = None,
) -> list[WebSearchResult]:
    """调用博查 Web Search API，并把响应归一化成内部模型。"""
    if not settings.bocha_api_key:
        raise ExternalServiceError("BOCHA_API_KEY 未配置，无法调用 web_search 工具")

    logger.info(
        "web_search %s",
        format_log_fields(
            event="web_search.bocha.start",
            query=query,
            count=count,
        ),
    )

    search_query = f"site:{site} {query}" if site else query

    try:
        response = await http_client.post(
            settings.bocha_web_search_url,
            headers={
                "Authorization": f"Bearer {settings.bocha_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": search_query,
                "summary": True,
                "count": count,
            },
            timeout=settings.bocha_web_search_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"博查 Web Search API 调用失败: {exc}") from exc
    except ValueError as exc:
        raise ExternalServiceError("博查 Web Search API 返回了非 JSON 响应") from exc

    if not isinstance(payload, dict):
        raise ExternalServiceError("博查 Web Search API 返回格式不正确")

    results = normalize_web_search_results(payload)
    logger.info(
        "web_search %s",
        format_log_fields(
            event="web_search.bocha.finish",
            query=query,
            count=count,
            result_count=len(results),
        ),
    )
    return results[:count]


def build_web_search_tool(
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> BaseTool:
    """构造公开互联网搜索工具，不接入当前 RAG Graph 主线。"""

    async def web_search(query: str, count: int = 5, site: str | None = None) -> str:
        results = await search_web_with_bocha(
            settings=settings,
            http_client=http_client,
            query=query,
            count=count,
            site=site,
        )
        return summarize_web_search_results(results)

    return StructuredTool.from_function(
        coroutine=web_search,
        name=WEB_SEARCH_TOOL_NAME,
        description=(
            "搜索公开互联网，适合回答当前知识库没有覆盖、需要最新网页信息的问题。"
            "查询官方资料时优先使用官方网站或官方文档关键词；返回网页标题、URL 和摘要。"
        ),
        args_schema=WebSearchToolInput,
    )


__all__ = [
    "WEB_SEARCH_TOOL_NAME",
    "WebSearchResult",
    "WebSearchToolInput",
    "build_web_search_tool",
    "normalize_web_search_results",
    "search_web_with_bocha",
    "summarize_web_search_results",
]
