"""Typed Evidence 转换、校验和 Requirement 级聚合。"""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from fast_app.domain.research_task_plan import (
    AgentTaskEvidenceRef,
    AgentTaskEvidenceRegistry,
    AgentTaskRequirement,
    AgentTaskRequirementEvidenceStatus,
    AgentTaskSubQuestionEvidenceValidation,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionResult,
)
from fast_app.services.exceptions import AgentTaskEvidenceStateInvalidError


_TOOL_SOURCE = {
    "knowledge_retrieval": "knowledge_retrieval",
    "web_search": "web_search",
    "nl2sql_query": "nl2sql_query",
}
_EVIDENCE_SOURCE = {
    "knowledge_chunk": "knowledge_retrieval",
    "web_citation": "web_search",
    "sql_query_result": "nl2sql_query",
}
_TERMINAL_SUB_STATUSES = {"completed", "partial", "failed", "skipped"}
_SECURITY_FAILURES = {
    "TOOL_PERMISSION_DENIED",
    "NL2SQL_PERMISSION_DENIED",
    "PROMPT_INJECTION_BLOCKED",
    "AGENT_TASK_SOURCE_UNAVAILABLE",
}


class AgentTaskRequirementEvidenceService:
    """作为 Wave 合并阶段唯一的 Evidence Validator 和 Aggregator。"""

    def build_candidates(
        self,
        *,
        task_plan_id: str,
        sub_question: ResearchTaskSubQuestion,
        answer: str | None,
        legacy_evidence: list[dict[str, object]],
        successful_tool_calls: dict[str, str],
    ) -> tuple[list[AgentTaskEvidenceRef], list[str], list[str]]:
        """把现有 ToolLoop 摘要转换成稳定 Typed Evidence。"""

        candidates: list[AgentTaskEvidenceRef] = []
        invalid_refs: list[str] = []
        reason_codes: list[str] = []
        for index, item in enumerate(legacy_evidence):
            call_id = str(item.get("tool_call_id") or "")
            tool_name = successful_tool_calls.get(call_id)
            reference_id = str(item.get("id") or "").strip()
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            try:
                if tool_name == "knowledge_retrieval":
                    candidates.append(
                        self._make_ref(
                            task_plan_id,
                            sub_question.sub_question_id,
                            "knowledge_chunk",
                            reference_id,
                            source_type="knowledge_retrieval",
                        )
                    )
                elif tool_name == "web_search":
                    candidates.append(
                        self._make_ref(
                            task_plan_id,
                            sub_question.sub_question_id,
                            "web_citation",
                            reference_id,
                            source_type="web_search",
                            url=str(metadata.get("url") or ""),
                        )
                    )
                elif tool_name == "nl2sql_query":
                    query_id = str(metadata.get("query_id") or reference_id)
                    columns = metadata.get("columns")
                    candidates.append(
                        self._make_ref(
                            task_plan_id,
                            sub_question.sub_question_id,
                            "sql_query_result",
                            query_id,
                            source_type="nl2sql_query",
                            query_id=query_id,
                            provided_attributes=(
                                [str(value) for value in columns]
                                if isinstance(columns, list)
                                else []
                            ),
                        )
                    )
            except (ValidationError, ValueError):
                invalid_refs.append(reference_id or f"legacy_evidence_{index}")
                reason_codes.append("EVIDENCE_SCHEMA_INVALID")

        if (
            sub_question.information_source_hint == "none"
            and answer
            and sub_question.depends_on
        ):
            candidates.append(
                self._make_ref(
                    task_plan_id,
                    sub_question.sub_question_id,
                    "derived_synthesis",
                    sub_question.sub_question_id,
                    dependency_sub_question_ids=list(sub_question.depends_on),
                )
            )
        return candidates, invalid_refs, list(dict.fromkeys(reason_codes))

    def validate_sub_question_evidence(
        self,
        *,
        sub_question: ResearchTaskSubQuestion,
        candidates: list[AgentTaskEvidenceRef],
        successful_tool_calls: dict[str, str],
        completed_result_ids: set[str],
        invalid_evidence_refs: list[str] | None = None,
        initial_reason_codes: list[str] | None = None,
    ) -> tuple[AgentTaskSubQuestionEvidenceValidation, list[AgentTaskEvidenceRef]]:
        """验证 Evidence 归属和真实 Tool provenance，不评估 Requirement。"""

        valid: list[AgentTaskEvidenceRef] = []
        invalid_ids: list[str] = list(invalid_evidence_refs or [])
        reasons: list[str] = list(initial_reason_codes or [])
        successful_sources = {
            _TOOL_SOURCE[name]
            for name in successful_tool_calls.values()
            if name in _TOOL_SOURCE
        }
        for evidence in candidates:
            reason = None
            if evidence.sub_question_id != sub_question.sub_question_id:
                reason = "EVIDENCE_SUB_QUESTION_MISMATCH"
            elif evidence.evidence_type == "derived_synthesis":
                dependencies = set(evidence.dependency_sub_question_ids)
                if dependencies != set(sub_question.depends_on):
                    reason = "EVIDENCE_DEPENDENCY_INVALID"
                elif not dependencies.issubset(completed_result_ids):
                    reason = "EVIDENCE_DEPENDENCY_NOT_COMPLETED"
            elif evidence.source_type not in successful_sources:
                reason = "EVIDENCE_TOOL_PROVENANCE_INVALID"
            if reason:
                invalid_ids.append(evidence.evidence_id)
                reasons.append(reason)
            else:
                valid.append(evidence)
        validation = AgentTaskSubQuestionEvidenceValidation(
            sub_question_id=sub_question.sub_question_id,
            valid_evidence_refs=[item.evidence_id for item in valid],
            invalid_evidence_refs=invalid_ids,
            reason_codes=list(dict.fromkeys(reasons)),
        )
        return validation, valid

    def merge_registry(
        self,
        registry: AgentTaskEvidenceRegistry,
        evidence: list[AgentTaskEvidenceRef],
    ) -> AgentTaskEvidenceRegistry:
        """幂等合并 Evidence；同 ID 不同内容表示 Registry 损坏。"""

        merged = dict(registry.evidence_by_id)
        for item in evidence:
            current = merged.get(item.evidence_id)
            if current is not None and current != item:
                raise AgentTaskEvidenceStateInvalidError(
                    "同一 Evidence ID 对应了不同内容"
                )
            merged[item.evidence_id] = item
        return AgentTaskEvidenceRegistry(evidence_by_id=merged)

    def aggregate(
        self,
        *,
        requirements: list[AgentTaskRequirement],
        sub_questions: list[ResearchTaskSubQuestion],
        results: list[ResearchTaskSubQuestionResult],
        registry: AgentTaskEvidenceRegistry,
    ) -> list[AgentTaskRequirementEvidenceStatus]:
        """按 Requirement 独立计算状态，LLM 无权声明已满足。"""

        result_by_id = {item.sub_question_id: item for item in results}
        result_evidence_ids = {
            item.sub_question_id: set(item.evidence_ids) for item in results
        }
        output: list[AgentTaskRequirementEvidenceStatus] = []
        for requirement in requirements:
            covering = [
                item.sub_question_id
                for item in sub_questions
                if requirement.requirement_id in item.covers_requirement_ids
            ]
            # Registry 是追加式事实库；只有当前 Result 明确引用的 Evidence
            # 才能参与当前状态判断，避免 resume 后复用已经失效的历史证据。
            current_evidence = [
                item
                for item in registry.evidence_by_id.values()
                if item.sub_question_id in covering
                and item.evidence_id
                in result_evidence_ids.get(item.sub_question_id, set())
            ]
            # strict/full satisfaction 只能由 completed Worker 贡献。
            # partial Evidence 仍保留给 allow_partial 分支。
            completed_evidence = [
                item
                for item in current_evidence
                if result_by_id[item.sub_question_id].status == "completed"
            ]
            satisfied_sources = self._satisfied_sources(
                requirement,
                completed_evidence,
            )
            contract_satisfied = self._contract_satisfied(
                requirement,
                completed_evidence,
                satisfied_sources,
            )
            unfinished = any(
                result_by_id.get(item_id) is None
                or result_by_id[item_id].status not in _TERMINAL_SUB_STATUSES
                for item_id in covering
            )
            security_blocked = any(
                result_by_id.get(item_id) is not None
                and result_by_id[item_id].error_code in _SECURITY_FAILURES
                for item_id in covering
            )
            if contract_satisfied:
                status = "satisfied"
            elif unfinished:
                status = "pending"
            elif (
                requirement.completion_policy == "allow_partial"
                and current_evidence
                and not security_blocked
            ):
                status = "partially_satisfied"
            else:
                status = "failed"
            # satisfied Requirement 只向最终综合开放 completed Evidence。
            # partially_satisfied 则开放当前合法的部分证据，并由最终答案说明限制。
            accepted_evidence = (
                completed_evidence if status == "satisfied" else current_evidence
            )
            missing = [
                source
                for source in requirement.source_policy.source_types
                if source not in satisfied_sources
            ]
            output.append(
                AgentTaskRequirementEvidenceStatus(
                    requirement_id=requirement.requirement_id,
                    status=status,
                    satisfied_source_types=satisfied_sources,
                    missing_source_types=missing,
                    evidence_refs=sorted(
                        {item.evidence_id for item in accepted_evidence}
                    ),
                    covering_sub_question_ids=covering,
                    reason_codes=(
                        []
                        if status == "satisfied"
                        else [
                            "REQUIREMENT_EVIDENCE_PENDING"
                            if status == "pending"
                            else "REQUIREMENT_EVIDENCE_INSUFFICIENT"
                        ]
                    ),
                )
            )
        return output

    @staticmethod
    def _make_ref(
        task_plan_id,
        sub_question_id,
        evidence_type,
        reference_id,
        **values,
    ):
        payload = {
            "task_plan_id": task_plan_id,
            "sub_question_id": sub_question_id,
            "evidence_type": evidence_type,
            "reference_id": reference_id,
            **values,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        return AgentTaskEvidenceRef(
            evidence_id=f"ev_{digest}",
            sub_question_id=sub_question_id,
            evidence_type=evidence_type,
            reference_id=reference_id,
            **values,
        )

    @staticmethod
    def _satisfied_sources(requirement, evidence):
        satisfied = []
        for source in requirement.source_policy.source_types:
            expected = [
                item
                for item in requirement.expected_evidence
                if _EVIDENCE_SOURCE.get(item.evidence_type) == source
            ]
            if expected and all(_expected_satisfied(item, evidence) for item in expected):
                satisfied.append(source)
        return satisfied

    @staticmethod
    def _contract_satisfied(requirement, evidence, satisfied_sources):
        if requirement.source_policy.mode == "none":
            return all(
                _expected_satisfied(item, evidence)
                for item in requirement.expected_evidence
            )
        if requirement.source_policy.mode == "all_of":
            return set(requirement.source_policy.source_types).issubset(satisfied_sources)
        return bool(satisfied_sources)


def _expected_satisfied(expected, evidence):
    matches = []
    required = set(expected.required_attributes)
    for item in evidence:
        if item.evidence_type != expected.evidence_type:
            continue
        if expected.requires_query_id and not item.query_id:
            continue
        if required and not required.issubset(item.provided_attributes):
            continue
        matches.append(item.evidence_id)
    return len(set(matches)) >= expected.minimum_count


__all__ = ["AgentTaskRequirementEvidenceService"]
