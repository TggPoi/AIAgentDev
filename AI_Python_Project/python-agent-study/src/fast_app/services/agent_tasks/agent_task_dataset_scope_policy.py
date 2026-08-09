"""从可信 user 文本解析 Dataset 字段和聚合范围。"""

from __future__ import annotations

import re

from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskDatasetScope,
    DatasetAggregationOperation,
    ResolvedPlanningRequest,
)


_NEGATED_SCOPE_PATTERN = re.compile(
    r"(?:不要|无需|不需要|不看|不比较|排除|忽略)[^，。！？；;\n]{0,32}",
    re.IGNORECASE,
)

_AGGREGATION_PATTERNS: tuple[
    tuple[DatasetAggregationOperation, re.Pattern[str]],
    ...,
] = (
    (
        "average",
        re.compile(r"(?:平均|均值|平均值|\bavg\b|\baverage\b)", re.IGNORECASE),
    ),
    (
        "sum",
        re.compile(r"(?:总计|合计|总和|\bsum\b|\btotal\b)", re.IGNORECASE),
    ),
    (
        "count",
        re.compile(r"(?:数量|个数|多少|\bcount\b)", re.IGNORECASE),
    ),
    (
        "minimum",
        re.compile(r"(?:最低|最小|\bmin(?:imum)?\b)", re.IGNORECASE),
    ),
    (
        "maximum",
        re.compile(r"(?:最高|最大|\bmax(?:imum)?\b)", re.IGNORECASE),
    ),
)


def resolve_dataset_field_scope(
    request: ResolvedPlanningRequest,
    capability: AgentTaskCapabilitySnapshot,
) -> AgentTaskDatasetScope | None:
    """只根据当前 Query 和实际参与改写的历史 user 消息冻结 Dataset 范围。"""

    if not capability.dataset_id:
        return None

    user_texts = [request.current_query]
    user_texts.extend(
        item.content for item in request.relevant_history if item.role == "user"
    )
    normalized_texts = [
        _NEGATED_SCOPE_PATTERN.sub("", item) for item in user_texts
    ]

    explicit_fields = [
        field
        for field in capability.allowed_dataset_fields
        if any(
            _contains_term(
                text,
                field,
                capability.dataset_field_synonyms.get(field, []),
            )
            for text in normalized_texts
        )
    ]
    aggregation_operations = [
        operation
        for operation, pattern in _AGGREGATION_PATTERNS
        if any(pattern.search(text) for text in normalized_texts)
    ]

    return AgentTaskDatasetScope(
        explicit_fields=sorted(set(explicit_fields)),
        aggregation_operations=list(dict.fromkeys(aggregation_operations)),
    )


def _contains_term(text: str, field: str, synonyms: list[str]) -> bool:
    lowered = text.lower()
    logical_pattern = re.compile(
        rf"(?<![a-z0-9_]){re.escape(field.lower())}(?![a-z0-9_])"
    )
    if logical_pattern.search(lowered):
        return True
    return any(
        term.strip() and term.strip().lower() in lowered
        for term in synonyms
    )


__all__ = ["resolve_dataset_field_scope"]
