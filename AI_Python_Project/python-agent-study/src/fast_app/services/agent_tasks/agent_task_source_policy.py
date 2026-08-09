"""从服务端持有的用户文本解析 Research 必需来源。"""

from __future__ import annotations

import re

from fast_app.domain.research_task_plan import (
    AgentTaskExternalSourceType,
    ResolvedPlanningRequest,
)


_NEGATED_DIRECT_WEB_PATTERN = re.compile(
    (
        r"(?:不要|无需|不需要|不必|禁止|不允许|不能|别)"
        r"(?:再)?(?:进行|使用)?\s*"
        r"(?:联网|上网|互联网|公开网络|公网|web\s*search|online\s*search)"
        r"(?:\s*(?:搜索|查询|检索|查找|调研|研究|查阅|核实|验证|比较|分析))?"
        r"|(?:不要|无需|不需要|禁止|不允许)[^。！？\n]{0,16}https?://\S*"
        r"|(?:(?:do\s+not|don't|without)\s+(?:use\s+)?"
        r"(?:web|internet|online)(?:\s+search)?)"
    ),
    re.IGNORECASE,
)

_EXPLICIT_DIRECT_WEB_PATTERNS = (
    re.compile(
        r"(?:联网|上网)\s*"
        r"(?:搜索|查询|检索|查找|调研|研究|查阅|核实|验证|比较|分析)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:请|需要|需|必须|要求|通过|使用|进行)\s*(?:联网|上网)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:互联网|公开网络|公网)\s*"
        r"(?:搜索|查询|检索|资料|来源|证据|网页|文档)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:搜索|查询|检索|查找|查阅|核实|验证|参考|基于|结合|综合)"
        r"[^。！？\n]{0,32}(?:网页|网站|URL|链接)",
        re.IGNORECASE,
    ),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(
        r"\b(?:web|internet|online)\s+"
        r"(?:search|research|sources?|evidence)\b",
        re.IGNORECASE,
    ),
)


def resolve_required_source_types(
    request: ResolvedPlanningRequest,
) -> list[AgentTaskExternalSourceType]:
    """只根据真实 user 文本解析当前任务不可替换的来源。

    current_query 始终参与判断。relevant_history 必须由 Pipeline 根据
    Rewriter 返回且经过消息 ID 校验后构造；这里只接受其中的 user 消息。
    assistant、resolved_query 和 Dataset metadata 不参与来源提取。
    """

    user_texts = [request.current_query]
    user_texts.extend(
        item.content for item in request.relevant_history if item.role == "user"
    )

    if any(_requires_direct_web(text) for text in user_texts):
        return ["web_search"]
    return []


def _requires_direct_web(text: str) -> bool:
    candidate = _NEGATED_DIRECT_WEB_PATTERN.sub("", text.strip())
    return any(
        pattern.search(candidate) is not None
        for pattern in _EXPLICIT_DIRECT_WEB_PATTERNS
    )


__all__ = ["resolve_required_source_types"]
