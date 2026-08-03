"""Research TaskPlan Candidate 的确定性质量和能力校验。"""

from __future__ import annotations

import re

from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    AgentTaskExpectedEvidence,
    AgentTaskPlannerCandidate,
    AgentTaskPlanValidationIssue,
    ResearchTaskSubQuestion,
)


_EVIDENCE_SOURCE = {
    "knowledge_chunk": "knowledge_retrieval",
    "web_citation": "web_search",
    "sql_query_result": "nl2sql_query",
}
_LOGICAL_FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class AgentTaskPlanValidator:
    """用服务端事实拒绝结构错误、来源错配和注定不可执行的计划。"""

    def validate_candidate(
        self,
        candidate: AgentTaskPlannerCandidate,
        capability: AgentTaskCapabilitySnapshot,
    ) -> list[AgentTaskPlanValidationIssue]:
        """校验 Planner/Reviewer Candidate；返回全部可解释问题。"""

        issues: list[AgentTaskPlanValidationIssue] = []
        requirements = {item.requirement_id: item for item in candidate.requirements}
        sub_questions = {item.sub_question_id: item for item in candidate.sub_questions}

        if len(requirements) != len(candidate.requirements):
            issues.append(_issue("PLAN_REQUIREMENT_ID_DUPLICATED", "Requirement ID 重复"))
        if len(sub_questions) != len(candidate.sub_questions):
            issues.append(_issue("PLAN_SUB_QUESTION_ID_DUPLICATED", "SubQuestion ID 重复"))
        if len({item.order for item in candidate.sub_questions}) != len(candidate.sub_questions):
            issues.append(_issue("PLAN_SUB_QUESTION_ORDER_DUPLICATED", "SubQuestion order 重复"))
        if len(candidate.requirements) > capability.max_requirements:
            issues.append(_issue("PLAN_REQUIREMENT_LIMIT_EXCEEDED", "Requirement 数量超过服务端上限"))
        if len(candidate.sub_questions) > capability.max_sub_questions:
            issues.append(_issue("PLAN_SUB_QUESTION_LIMIT_EXCEEDED", "SubQuestion 数量超过服务端上限"))

        coverage = {item_id: [] for item_id in requirements}
        for sub_question in candidate.sub_questions:
            if not sub_question.covers_requirement_ids:
                issues.append(
                    _issue(
                        "PLAN_SUB_QUESTION_COVERAGE_EMPTY",
                        "SubQuestion 必须覆盖至少一个 Requirement",
                        sub_question_ids=[sub_question.sub_question_id],
                    )
                )
            for requirement_id in sub_question.covers_requirement_ids:
                if requirement_id not in requirements:
                    issues.append(
                        _issue(
                            "PLAN_REQUIREMENT_REFERENCE_NOT_FOUND",
                            "SubQuestion 引用了不存在的 Requirement",
                            requirement_ids=[requirement_id],
                            sub_question_ids=[sub_question.sub_question_id],
                        )
                    )
                    continue
                coverage[requirement_id].append(sub_question.sub_question_id)
                if not _hint_can_cover(
                    sub_question.information_source_hint,
                    requirements[requirement_id].expected_evidence,
                ):
                    issues.append(
                        _issue(
                            "PLAN_SOURCE_COVERAGE_MISMATCH",
                            "SubQuestion 来源不能产生 Requirement 所需 Evidence",
                            requirement_ids=[requirement_id],
                            sub_question_ids=[sub_question.sub_question_id],
                        )
                    )

        for requirement_id, covering in coverage.items():
            if not covering:
                issues.append(
                    _issue(
                        "PLAN_REQUIREMENT_UNCOVERED",
                        "Requirement 没有任何 SubQuestion 覆盖",
                        requirement_ids=[requirement_id],
                    )
                )

        issues.extend(_validate_dependency_graph(candidate.sub_questions))
        for requirement in candidate.requirements:
            issues.extend(_validate_evidence_contract(requirement, capability))

        for sub_question in candidate.sub_questions:
            hint = sub_question.information_source_hint
            if hint == "none" and not sub_question.depends_on:
                issues.append(
                    _issue(
                        "PLAN_DERIVED_DEPENDENCY_REQUIRED",
                        "综合 SubQuestion 必须依赖产生事实证据的前置 SubQuestion",
                        sub_question_ids=[sub_question.sub_question_id],
                    )
                )
            if hint != "none" and hint not in capability.available_source_types:
                issues.append(
                    _issue(
                        "PLAN_SOURCE_UNAVAILABLE",
                        "SubQuestion 请求的来源当前不可用",
                        sub_question_ids=[sub_question.sub_question_id],
                    )
                )
            if hint == "web_search" and not capability.web_direct_allowed:
                issues.append(
                    _issue(
                        "PLAN_DIRECT_WEB_DISABLED",
                        "请求策略不允许明确 Web SubQuestion",
                        sub_question_ids=[sub_question.sub_question_id],
                    )
                )
        return _deduplicate(issues)

    def validate_formal(
        self,
        candidate: AgentTaskPlannerCandidate,
        sub_questions: list[ResearchTaskSubQuestion],
        capability: AgentTaskCapabilitySnapshot,
    ) -> list[AgentTaskPlanValidationIssue]:
        """正式模型转换后复验服务端生成的 WebUsage。"""

        issues = self.validate_candidate(candidate, capability)
        for item in sub_questions:
            if item.information_source_hint == "web_search" and item.web_usage != "direct":
                issues.append(
                    _issue(
                        "PLAN_WEB_USAGE_INVALID",
                        "明确 Web SubQuestion 必须使用 direct",
                        sub_question_ids=[item.sub_question_id],
                    )
                )
            if (
                item.information_source_hint == "knowledge_retrieval"
                and item.web_usage == "direct"
            ):
                issues.append(
                    _issue(
                        "PLAN_WEB_USAGE_INVALID",
                        "知识库 SubQuestion 不允许直接使用 direct Web",
                        sub_question_ids=[item.sub_question_id],
                    )
                )
        return _deduplicate(issues)


def _validate_evidence_contract(requirement, capability):
    issues: list[AgentTaskPlanValidationIssue] = []
    policy = requirement.source_policy
    evidence_sources = {
        _EVIDENCE_SOURCE[item.evidence_type]
        for item in requirement.expected_evidence
        if item.evidence_type in _EVIDENCE_SOURCE
    }
    if policy.mode == "none":
        if not any(item.evidence_type == "derived_synthesis" for item in requirement.expected_evidence):
            issues.append(
                _issue(
                    "PLAN_DERIVED_EVIDENCE_REQUIRED",
                    "mode=none Requirement 必须声明 derived_synthesis",
                    requirement_ids=[requirement.requirement_id],
                )
            )
        if evidence_sources:
            issues.append(
                _issue(
                    "PLAN_SOURCE_POLICY_MISMATCH",
                    "mode=none Requirement 不允许外部 Evidence",
                    requirement_ids=[requirement.requirement_id],
                )
            )
    else:
        missing = set(policy.source_types) - evidence_sources
        unexpected = evidence_sources - set(policy.source_types)
        if missing or unexpected or any(
            item.evidence_type == "derived_synthesis" for item in requirement.expected_evidence
        ):
            issues.append(
                _issue(
                    "PLAN_SOURCE_POLICY_MISMATCH",
                    "SourcePolicy 与 ExpectedEvidence 不一致",
                    requirement_ids=[requirement.requirement_id],
                )
            )

    for expected in requirement.expected_evidence:
        if expected.evidence_type != "sql_query_result":
            continue
        if not capability.dataset_id or not capability.nl2sql_query_available:
            issues.append(
                _issue(
                    "PLAN_DATASET_REQUIRED",
                    "NL2SQL Evidence 需要服务端绑定可用 Dataset",
                    requirement_ids=[requirement.requirement_id],
                )
            )
        invalid = [
            field
            for field in expected.required_attributes
            if not _LOGICAL_FIELD_RE.fullmatch(field)
            or field not in capability.allowed_dataset_fields
        ]
        if invalid:
            issues.append(
                _issue(
                    "PLAN_DATASET_FIELD_UNAVAILABLE",
                    "required_attributes 包含不存在或非白名单逻辑字段",
                    requirement_ids=[requirement.requirement_id],
                )
            )
    return issues


def _hint_can_cover(hint: str, expected: list[AgentTaskExpectedEvidence]) -> bool:
    if hint == "none":
        return any(item.evidence_type == "derived_synthesis" for item in expected)
    return any(_EVIDENCE_SOURCE.get(item.evidence_type) == hint for item in expected)


def _validate_dependency_graph(sub_questions):
    issues: list[AgentTaskPlanValidationIssue] = []
    by_id = {item.sub_question_id: item for item in sub_questions}
    indegree = {item_id: 0 for item_id in by_id}
    children = {item_id: [] for item_id in by_id}
    for item in sub_questions:
        for dependency_id in item.depends_on:
            if dependency_id == item.sub_question_id:
                issues.append(
                    _issue(
                        "PLAN_DEPENDENCY_SELF_REFERENCE",
                        "SubQuestion 不能依赖自身",
                        sub_question_ids=[item.sub_question_id],
                    )
                )
            elif dependency_id not in by_id:
                issues.append(
                    _issue(
                        "PLAN_DEPENDENCY_NOT_FOUND",
                        "SubQuestion 依赖不存在",
                        sub_question_ids=[item.sub_question_id, dependency_id],
                    )
                )
            else:
                indegree[item.sub_question_id] += 1
                children[dependency_id].append(item.sub_question_id)
    ready = [item_id for item_id, count in indegree.items() if count == 0]
    visited = 0
    while ready:
        item_id = ready.pop()
        visited += 1
        for child in children[item_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(by_id):
        issues.append(_issue("PLAN_DEPENDENCY_CYCLE", "SubQuestion 依赖图存在循环"))
    return issues


def _issue(code, message, *, requirement_ids=None, sub_question_ids=None):
    return AgentTaskPlanValidationIssue(
        code=code,
        message=message,
        requirement_ids=requirement_ids or [],
        sub_question_ids=sub_question_ids or [],
        severity="error",
    )


def _deduplicate(issues):
    result = []
    seen = set()
    for issue in issues:
        key = (
            issue.code,
            tuple(issue.requirement_ids),
            tuple(issue.sub_question_ids),
        )
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


__all__ = ["AgentTaskPlanValidator"]
