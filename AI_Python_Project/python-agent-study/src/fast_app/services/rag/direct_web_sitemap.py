"""Direct Web 官方网站 sitemap 候选发现、解析与排序。

当搜索提供商没有召回精确官方页面时，Direct Web 节点调用本模块
读取官方网站的标准 sitemap，按当前检索计划计算通用候选；
不包含任何产品、版本或主题硬编码。
"""

from collections import defaultdict
import re
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan


_SITEMAP_DEFAULT_PATH = "/sitemap.xml"
_SITEMAP_MAX_BYTES = 5_000_000
_SITEMAP_MAX_CHILD_INDEXES = 3
_SITEMAP_MAX_ROBOTS_DECLARED = 2
_SITEMAP_MAX_CANDIDATES = 20
_SITEMAP_DOC_PATH_HINTS = (
    "/docs/",
    "/doc/",
    "/documentation/",
    "/guide/",
    "/help/",
    "/wiki/",
    "/manual/",
)
_ASCII_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{2,}")


def _xml_local_name(tag: object) -> str:
    """去掉 XML 命名空间前缀；注释等非字符串节点返回空串。"""

    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _sitemap_child_locs(root, *, child_kind: str) -> list[str]:
    """只收集根节点直接子节点中指定类型（url 或 sitemap）的 <loc> 文本。

    sitemapindex 的直接子节点是 <sitemap>，urlset 的直接子节点是 <url>；
    按类型收集后，子 sitemap 的 XML 地址不会被误当成网页候选。
    """

    locs: list[str] = []
    for element in root:
        if _xml_local_name(element.tag) != child_kind:
            continue
        for child in element:
            if _xml_local_name(child.tag) == "loc" and child.text:
                locs.append(child.text.strip())
    return locs


async def _fetch_sitemap_tree(http_client: httpx.AsyncClient, sitemap_url: str):
    """下载并解析单个 sitemap；任何网络或格式失败都返回 None。"""

    try:
        response = await http_client.get(sitemap_url, timeout=10.0)
        response.raise_for_status()
        if len(response.content) > _SITEMAP_MAX_BYTES:
            return None
        return ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return None


async def _robots_sitemap_urls(http_client: httpx.AsyncClient, *, site: str) -> list[str]:
    """按标准从 robots.txt 读取 Sitemap: 声明；失败返回空列表。"""

    try:
        response = await http_client.get(f"https://{site}/robots.txt", timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    declared: list[str] = []
    for line in response.text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            declared.append(stripped[len("sitemap:") :].strip())
    return declared


def _allowed_sitemap_url(url: str, *, site: str) -> bool:
    """sitemap 候选和子索引都必须是同域（或子域）HTTPS 地址。"""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    lower_site = site.lower()
    return parsed.scheme == "https" and (
        hostname == lower_site or hostname.endswith(f".{lower_site}")
    )


async def _expand_sitemap_index(
    http_client: httpx.AsyncClient,
    root,
    *,
    site: str,
) -> list[str]:
    """根节点是 sitemapindex 时展开一层，获取子 sitemap 中的页面 URL。

    只展开一层且限制数量，避免递归下载整站索引树。
    """

    pages: list[str] = []
    for sub in _sitemap_child_locs(root, child_kind="sitemap")[
        :_SITEMAP_MAX_CHILD_INDEXES
    ]:
        if not _allowed_sitemap_url(sub, site=site):
            continue
        sub_root = await _fetch_sitemap_tree(http_client, sub)
        if sub_root is None:
            continue
        pages.extend(
            url
            for url in _sitemap_child_locs(sub_root, child_kind="url")
            if _allowed_sitemap_url(url, site=site)
        )
    return pages


async def _collect_sitemap_page_urls(
    http_client: httpx.AsyncClient, *, site: str
) -> list[str]:
    """发现并解析 sitemap，返回同域 HTTPS 页面 URL。

    发现顺序：/sitemap.xml → robots.txt 的 Sitemap: 声明；
    遇到 sitemap 索引时只展开一层，不递归下载。
    """

    async def pages_from_tree(root) -> list[str]:
        pages = [
            url
            for url in _sitemap_child_locs(root, child_kind="url")
            if _allowed_sitemap_url(url, site=site)
        ]
        if pages:
            return pages
        return await _expand_sitemap_index(http_client, root, site=site)

    root = await _fetch_sitemap_tree(
        http_client, f"https://{site}{_SITEMAP_DEFAULT_PATH}"
    )
    if root is not None:
        return await pages_from_tree(root)
    declared_urls = await _robots_sitemap_urls(http_client, site=site)
    for declared in declared_urls[:_SITEMAP_MAX_ROBOTS_DECLARED]:
        if not _allowed_sitemap_url(declared, site=site):
            continue
        declared_root = await _fetch_sitemap_tree(http_client, declared)
        if declared_root is None:
            continue
        pages = await pages_from_tree(declared_root)
        if pages:
            return pages
    return []


def _compound_variants(value: str) -> set[str]:
    """复合搜索词的压缩匹配变体。

    row-level-security 压缩成 rowlevelsecurity，但官方 URL 常用省略
    中间词的连写 rowsecurity；同时生成逐段省略一个内部分词的变体，
    只保留长度>=6 的强信号。
    """

    tokens = [token.lower() for token in _ASCII_TOKEN_PATTERN.findall(value)]
    variants: set[str] = set()
    if len(tokens) >= 2:
        joined = "".join(tokens)
        if len(joined) >= 6:
            variants.add(joined)
        for index in range(1, len(tokens) - 1):
            omitted = "".join(tokens[:index] + tokens[index + 1 :])
            if len(omitted) >= 6:
                variants.add(omitted)
    return variants


def _sitemap_needles(plan: DirectWebSearchPlan) -> set[str]:
    """打分词集合：query、主题词、URL 片段约束和跨语言桥接词。

    url_search_terms 的复合词（如 row-level-security）整体保留为强
    信号，同时拆出 ASCII token 作为弱信号；拆分后单字太泛（如
    security 几乎命中全站）时靠 IDF 加权自然降权。
    """

    needles: set[str] = set()
    for value in (
        plan.query,
        *plan.required_content_terms,
        *plan.required_url_fragments,
    ):
        needles.update(token.lower() for token in _ASCII_TOKEN_PATTERN.findall(value))
    for value in plan.url_search_terms:
        lowered = value.lower()
        if len(lowered) >= 4:
            needles.add(lowered)
        needles.update(_compound_variants(value))
        needles.update(token.lower() for token in _ASCII_TOKEN_PATTERN.findall(value))
    return needles


def _doc_path_score(url: str) -> int:
    """纯中文 query 下唯一可用的确定性信号：URL 路径处于哪些常见文档目录。"""

    lowered = url.lower()
    return sum(hint in lowered for hint in _SITEMAP_DOC_PATH_HINTS)


def _dedupe_substring_tokens(tokens: set[str]) -> set[str]:
    """同一 URL 内被更长 token 覆盖的子串 token 去冗余。

    rowsecurity 与 row/security 同时命中同一 URL 时，只计复合词；
    row/security 未参与复合词命中的页面仍单独计分。
    """

    kept: set[str] = set()
    for token in tokens:
        # token 是另一个已命中 token 的真子串（如 row ⊂ rowsecurity）时丢弃；
        # 复合词本身永远保留。
        covered = any(
            token != other and token in other for other in tokens
        )
        if not covered:
            kept.add(token)
    return kept


def _rank_sitemap_candidates(
    entries: list[str], needles: set[str]
) -> list[dict[str, str]]:
    """纯函数：把去重后的 sitemap 页面 URL 排序成最多 N 个候选。"""

    unique_entries = list(dict.fromkeys(entries))

    if needles:
        hits: list[tuple[str, set[str]]] = []
        doc_freq: dict[str, int] = defaultdict(int)
        # 打分词统一转成“去分隔符压缩形式”，使 row-level-security
        # 能命中 URL 中的连写 rowsecurity，不再被连字符阻断。
        compact_needles = {
            re.sub(r"[^a-z0-9]", "", token) for token in needles
        }
        compact_needles.discard("")
        # 复合 url_search_term（长度>=6）是高确定性的主题信号；
        # 命中它的页面优先于只命中零散短词的页面。
        compound_needles = {
            token for token in compact_needles if len(token) >= 6
        }
        for url in unique_entries:
            compact = re.sub(r"[^a-z0-9]", "", url.lower())
            matched = {
                token for token in compact_needles if token in compact
            }
            matched = _dedupe_substring_tokens(matched)
            if matched:
                hits.append((url, matched))
                for token in matched:
                    doc_freq[token] += 1
        # docs、16 这类泛化词几乎命中全站，用 1/文档频率加权保持区分度。
        scored = [
            (
                # 第一排序键：是否命中复合主题词；避免 level 这类碰巧
                # 稀有的短词把离题页推到相关页前面。
                1 if matched & compound_needles else 0,
                sum(1.0 / doc_freq[token] for token in matched),
                url,
                matched,
            )
            for url, matched in hits
        ]
        # 同分优先深路径（具体页面），废弃旧版"URL 越短越靠前"的规则。
        scored.sort(key=lambda item: (-item[0], -item[1], -item[2].count("/"), item[2]))
        return [
            {
                "title": url,
                "url": url,
                "summary": (
                    "official sitemap candidate; matched: "
                    + ", ".join(sorted(matched))
                ),
            }
            for _, _, url, matched in scored[:_SITEMAP_MAX_CANDIDATES]
        ]

    # 完全没有 ASCII 打分词（纯中文 query）时，URL 文本匹配必然失效；
    # 退化为文档目录结构启发式，仍无候选才返回空列表走明确报错路径。
    doc_pages = [url for url in unique_entries if _doc_path_score(url)]
    doc_pages.sort(key=lambda url: (-_doc_path_score(url), url))
    return [
        {
            "title": url,
            "url": url,
            "summary": "official sitemap candidate; doc-path heuristic",
        }
        for url in doc_pages[:_SITEMAP_MAX_CANDIDATES]
    ]


async def _official_sitemap_candidates(
    http_client: httpx.AsyncClient,
    *,
    plan: DirectWebSearchPlan,
) -> list[dict[str, str]]:
    """从官方网站标准 sitemap 提取与当前问题相关的真实 URL。

    用户给了版本/路径片段约束时，先用硬约束筛掉错误版本页面，
    避免旧版本页凭高分挤占候选名额；全被过滤时退回全集排序。
    """

    if not plan.site:
        return []
    entries = await _collect_sitemap_page_urls(http_client, site=plan.site)
    if not entries:
        return []
    needles = _sitemap_needles(plan)
    if plan.required_url_fragments:
        filtered = [
            url
            for url in entries
            if all(_url_has_fragment(url, fragment) for fragment in plan.required_url_fragments)
        ]
        if filtered:
            entries = filtered
    return _rank_sitemap_candidates(entries, needles)


def _url_has_fragment(url: str, fragment: str) -> bool:
    """片段必须作为完整路径段出现，避免 16 误命中 2016、news-16-18。"""

    pattern = re.compile(
        r"(?<![a-z0-9])" + re.escape(fragment.lower()) + r"(?![a-z0-9])"
    )
    return bool(pattern.search(url.lower()))


__all__ = ["_official_sitemap_candidates"]
