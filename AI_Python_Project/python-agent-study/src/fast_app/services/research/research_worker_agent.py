"""显式 Research Worker Agent：一个实例调用处理一个子问题。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskSubQuestion,
    AgentTaskSubQuestionResult,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.research_task_plan import ResearchTaskPlan, ResearchTaskSubQuestion
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.graph.research.agentic_research_graph import ResearchExecutionCancelled
from fast_app.graph.research.research_worker_graph import (
    ResearchWorkerGraphState,
    build_research_worker_graph,
)
from fast_app.services.research.research_evidence_evaluator import ResearchEvidenceEvaluator
from fast_app.services.research.research_tool_loop import (
    ResearchToolLoop,
    build_public_web_query,
    merge_evidence,
)


LangChainConfigFactory = Callable[[str], RunnableConfig]
ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ResearchWorkerRequest:
    """父级调度器派给一个 Worker 的完整、隔离输入。"""

    plan: ResearchTaskPlan
    sub_question: ResearchTaskSubQuestion
    dependency_results: list[AgentTaskSubQuestionResult]
    policy: AgentResearchPolicy
    filters: RetrievalFilters
    wave: int
    on_progress: ProgressCallback
    should_stop: Callable[[], bool]
    langchain_config_factory: LangChainConfigFactory | None = None
    user: CurrentUserContext | None = None


class ResearchWorkerAgent:
    """通过独立 LangGraph 执行工具、评估证据并进行有限纠正。"""

    def __init__(
        self,
        settings: Settings,
        tool_loop: ResearchToolLoop,
        evaluator: ResearchEvidenceEvaluator,
    ) -> None:
        self._settings = settings
        self._tool_loop = tool_loop
        self._evaluator = evaluator
        self._graph = build_research_worker_graph(
            run_attempt=self._run_attempt,
            evaluate_evidence=self._evaluate_evidence,
            route_evaluation=self._route_evaluation,
            choose_route=lambda state: state["next_action"],
            prepare_retry=self._prepare_retry,
            complete=self._complete,
            finalize_limited=self._finalize_limited,
        )

    async def run(
        self,
        request: ResearchWorkerRequest,
    ) -> AgentTaskSubQuestionResult:
        """运行一个隔离 Worker，并返回唯一的结构化子问题结果。"""

        initial = _failed_result(request.sub_question, "NOT_STARTED")
        graph_config = (
            request.langchain_config_factory(
                f"research.wave_{request.wave}.worker."
                f"{request.sub_question.sub_question_id}.graph"
            )
            if request.langchain_config_factory is not None
            else None
        )
        result = await self._graph.ainvoke(
            {
                "request": request,
                "attempt": 1,
                "used_tool_calls": 0,
                "all_tool_calls": [],
                "all_evidence": [],
                "all_context_doc_groups": [],
                "force_web": request.policy.web_policy == "required",
                "retry_missing_points": [],
                "attempts": [],
                "last_result": initial,
                "evaluation": None,
                "evaluator_error": None,
                "next_action": "limited",
                "final_warning": None,
                "final_result": None,
            },
            config=graph_config,
        )
        final_result = result.get("final_result")
        if final_result is None:
            return _failed_result(request.sub_question, "WORKER_RESULT_MISSING")
        return final_result

    async def _run_attempt(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        request: ResearchWorkerRequest = state["request"]
        if request.should_stop():
            raise ResearchExecutionCancelled("TaskPlan 已取消")
        attempt = state["attempt"]
        remaining_calls = max(
            self._settings.agent_research_max_tool_calls_per_worker
            - state["used_tool_calls"],
            0,
        )
        attempt_question = (
            request.sub_question.model_copy(
                update={"information_source_hint": "web_search"}
            )
            if state["force_web"]
            else request.sub_question
        )

        def build_worker_config(child_name: str) -> RunnableConfig:
            if request.langchain_config_factory is None:
                return {}
            tool_match = re.search(r"\.tool\.([^.]+)", child_name)
            if tool_match is not None:
                name = (
                    f"research.worker.{request.sub_question.sub_question_id}."
                    f"attempt_{attempt}.tool.{tool_match.group(1)}"
                )
            else:
                leaf = child_name.rsplit(".", 1)[-1]
                name = (
                    f"research.wave_{request.wave}.worker."
                    f"{request.sub_question.sub_question_id}.attempt_{attempt}.{leaf}"
                )
            return request.langchain_config_factory(name)

        attempt_outcome = await self._tool_loop.run_attempt(
            plan=request.plan,
            sub_question=attempt_question,
            dependency_results=request.dependency_results,
            mode=request.policy.mode,
            top_k=request.policy.top_k,
            candidate_k=request.policy.candidate_k,
            min_score=request.policy.min_score,
            filters=request.filters,
            langchain_config_factory=(
                build_worker_config
                if request.langchain_config_factory is not None
                else None
            ),
            max_tool_calls_override=remaining_calls,
            allow_web_search=state["force_web"],
            attempt=attempt,
            prior_tool_calls=state["all_tool_calls"],
            prior_evidence=state["all_evidence"],
            prior_context_doc_groups=state["all_context_doc_groups"],
            retry_missing_points=state["retry_missing_points"],
            safe_web_query=build_public_web_query(
                request.plan.original_query,
                request.sub_question.question,
                state["retry_missing_points"],
            ),
            user=request.user,
        )
        last_result = attempt_outcome.result
        return {
            "last_result": last_result,
            "used_tool_calls": state["used_tool_calls"] + len(last_result.tool_calls),
            "all_tool_calls": [*state["all_tool_calls"], *last_result.tool_calls],
            "all_evidence": merge_evidence(
                state["all_evidence"], last_result.evidence
            ),
            "all_context_doc_groups": [
                *state["all_context_doc_groups"],
                *attempt_outcome.context_doc_groups,
            ],
            "evaluation": None,
            "evaluator_error": None,
            "final_warning": None,
        }

    async def _evaluate_evidence(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        request: ResearchWorkerRequest = state["request"]
        if request.should_stop():
            raise ResearchExecutionCancelled("TaskPlan 已取消")
        try:
            requirements = None
            if isinstance(request.plan, ResearchTaskPlan) and isinstance(
                request.sub_question,
                ResearchTaskSubQuestion,
            ):
                covered_ids = set(request.sub_question.covers_requirement_ids)
                requirements = [
                    requirement
                    for requirement in request.plan.requirements
                    if requirement.requirement_id in covered_ids
                ]
            evaluation = await self._evaluator.evaluate(
                sub_question=request.sub_question,
                requirements=requirements,
                answer=state["last_result"].answer,
                evidence=state["all_evidence"],
                langchain_config=(
                    request.langchain_config_factory(
                        f"research.worker.{request.sub_question.sub_question_id}."
                        f"attempt_{state['attempt']}.evaluator"
                    )
                    if request.langchain_config_factory is not None
                    else None
                ),
            )
        except ResearchExecutionCancelled:
            raise
        except Exception as exc:
            warning = f"Evaluator 不可用: {type(exc).__name__}"
            attempts = [
                *state["attempts"],
                {
                    "attempt": state["attempt"],
                    "selected_tool": state["last_result"].selected_tool,
                    "status": state["last_result"].status,
                    "tool_call_count": len(state["last_result"].tool_calls),
                    "evaluation_error": warning,
                },
            ]
            status = "partial" if state["all_evidence"] else "failed"
            await request.on_progress(
                "agent_task_evidence_evaluated",
                {
                    "sub_question_id": request.sub_question.sub_question_id,
                    "wave": request.wave,
                    "attempt": state["attempt"],
                    "status": status,
                    "evaluation": {"error": warning},
                },
            )
            return {
                "attempts": attempts,
                "evaluator_error": warning,
                "evaluation": None,
            }

        attempts = [
            *state["attempts"],
            {
                "attempt": state["attempt"],
                "selected_tool": state["last_result"].selected_tool,
                "status": state["last_result"].status,
                "tool_call_count": len(state["last_result"].tool_calls),
                "evaluation": evaluation.model_dump(mode="json"),
            },
        ]
        await request.on_progress(
            "agent_task_evidence_evaluated",
            {
                "sub_question_id": request.sub_question.sub_question_id,
                "wave": request.wave,
                "attempt": state["attempt"],
                "status": state["last_result"].status,
                "evaluation": evaluation.model_dump(mode="json"),
            },
        )
        return {"attempts": attempts, "evaluation": evaluation}

    async def _route_evaluation(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        request: ResearchWorkerRequest = state["request"]
        if state["evaluator_error"]:
            return {
                "next_action": "limited",
                "final_warning": state["evaluator_error"],
            }
        evaluation = state["evaluation"]
        if evaluation is None:
            return {"next_action": "limited", "final_warning": "证据评估结果缺失。"}
        if evaluation.verdict == "sufficient" and evaluation.confidence >= 0.65:
            return {"next_action": "complete"}
        wants_web = evaluation.recommended_action in {
            "search_web",
            "combine_local_and_web",
        }
        if wants_web and request.policy.web_policy == "disabled":
            return {
                "next_action": "limited",
                "final_warning": "证据不足，但本次请求未授权 WebSearch。",
            }
        can_retry = (
            state["attempt"]
            < self._settings.agent_research_max_correction_rounds + 1
            and state["used_tool_calls"]
            < self._settings.agent_research_max_tool_calls_per_worker
        )
        if can_retry and evaluation.recommended_action in {
            "rewrite_local_query",
            "search_web",
            "combine_local_and_web",
        }:
            return {"next_action": "retry"}
        return {
            "next_action": "limited",
            "final_warning": evaluation.reason or "达到纠正预算，证据仍不充分。",
        }

    async def _prepare_retry(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        request: ResearchWorkerRequest = state["request"]
        evaluation = state["evaluation"]
        assert evaluation is not None
        wants_web = evaluation.recommended_action in {
            "search_web",
            "combine_local_and_web",
        }
        force_web = request.policy.web_policy == "required" or (
            wants_web and request.policy.web_policy == "fallback"
        )
        next_attempt = state["attempt"] + 1
        await request.on_progress(
            "agent_task_sub_question_retrying",
            {
                "sub_question_id": request.sub_question.sub_question_id,
                "wave": request.wave,
                "attempt": next_attempt,
                "status": "retrying",
                "retry_reason": evaluation.reason,
            },
        )
        return {
            "attempt": next_attempt,
            "force_web": force_web,
            # 本地 query 改写和 Web 补充都必须看到 Evaluator 指出的缺失点。
            "retry_missing_points": list(evaluation.missing_points),
        }

    async def _complete(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        return {"final_result": self._build_result(state, status="completed")}

    async def _finalize_limited(
        self,
        state: ResearchWorkerGraphState,
    ) -> dict[str, Any]:
        status = "partial" if state["all_evidence"] else "failed"
        return {
            "final_result": self._build_result(
                state,
                status=status,
                warning=state["final_warning"],
            )
        }

    @staticmethod
    def _build_result(
        state: ResearchWorkerGraphState,
        *,
        status: str,
        warning: str | None = None,
    ) -> AgentTaskSubQuestionResult:
        source_types = sorted(
            {
                str(item.get("source"))
                for item in state["all_evidence"]
                if item.get("source")
            }
        )
        has_evidence = bool(state["all_evidence"])
        return state["last_result"].model_copy(
            update={
                "status": status,
                "evidence": state["all_evidence"],
                "tool_calls": state["all_tool_calls"],
                "attempt_count": state["attempt"],
                "attempts": state["attempts"],
                "evaluation": state["evaluation"],
                "source_types": source_types,
                "warnings": (
                    [warning]
                    if warning and (has_evidence or state["evaluator_error"])
                    else []
                ),
                "error": (
                    None
                    if status in {"completed", "partial"}
                    else (state["last_result"].error or warning)
                ),
            }
        )


def _failed_result(
    sub_question: AgentTaskSubQuestion,
    error: str,
    warning: str | None = None,
) -> AgentTaskSubQuestionResult:
    return AgentTaskSubQuestionResult(
        sub_question_id=sub_question.sub_question_id,
        question=sub_question.question,
        selected_tool="none",
        status="failed",
        error=error,
        warnings=[warning] if warning else [],
    )


__all__ = ["ResearchWorkerAgent", "ResearchWorkerRequest"]
