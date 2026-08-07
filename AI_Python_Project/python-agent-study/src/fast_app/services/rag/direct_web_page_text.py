"""Direct Web 选中页面的正文提取：确定性规则，不依赖模型。

节点拿到选择器确认的公开页面后，用本模块把 HTML 转成纯文本。
提取结果过短（SPA 骨架、跳转页等）时返回空串，由调用方回退到
仍然经过域名/片段/主题过滤的搜索摘要，绝不使用未过滤内容。
"""

from html import unescape
import re

# 提取后低于该长度视为无有效正文，节点应回退摘要。
MIN_USEFUL_TEXT_CHARS = 200
# 单页最多参与择优的容器块数，防御异常巨型页面。
MAX_CONTAINER_BLOCKS = 20

_NOISE_TAG_PATTERN = re.compile(
    r"(?is)<(?:script|style|nav|header|footer|aside|form|iframe|"
    r"noscript|svg|button)\b[^>]*>.*?</(?:script|style|nav|header|"
    r"footer|aside|form|iframe|noscript|svg|button)>"
)
_HTML_COMMENT_PATTERN = re.compile(r"(?s)<!--.*?-->")
_TAG_PATTERN = re.compile(r"(?s)<[^>]+>")


def _container_blocks(raw_html: str, tag: str) -> list[str]:
    """收集页面中某个标签的全部块，而不是只取第一个匹配。"""

    return [
        matched.group(1)
        for matched in re.finditer(
            rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>", raw_html
        )
    ][:MAX_CONTAINER_BLOCKS]


def _strip_to_text(html_fragment: str) -> str:
    """移除注释、噪声标签和全部 HTML 标记，归一化空白。"""

    without_comments = _HTML_COMMENT_PATTERN.sub(" ", html_fragment)
    without_noise = _NOISE_TAG_PATTERN.sub(" ", without_comments)
    return " ".join(
        unescape(_TAG_PATTERN.sub(" ", without_noise)).split()
    )


def extract_page_text(raw_html: str) -> str:
    """提取页面主正文；无有效正文时返回空串，由调用方决定回退。

    择优规则：article → main → body 依次尝试，同一标签存在多个块时
    选择剥离标签后文本最长的块，避免列表页或推荐卡片压过正文。
    """

    for tag in ("article", "main", "body"):
        blocks = _container_blocks(raw_html, tag)
        if not blocks:
            continue
        best = max(
            (_strip_to_text(block) for block in blocks),
            key=len,
            default="",
        )
        if len(best) >= MIN_USEFUL_TEXT_CHARS:
            return best
        if tag == "body":
            return ""
    return ""
