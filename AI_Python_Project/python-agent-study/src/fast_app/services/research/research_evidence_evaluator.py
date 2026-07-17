"""Agentic Research 的证据充分性评估器。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.agent_task_plan import (
    AgentTaskSubQuestion,
    ResearchEvidenceEvaluation,
)


logger = get_logger(__name__)

EVALUATOR_PROMPT = """你是研究证据评估器。只评估证据，不补写事实。
根据当前子问题、期望证据、候选回答和证据摘要，返回结构化判断。
没有证据时必须判为 insufficient。存在互相矛盾且无法消解的证据时判为 conflict。
recommended_action 只能是 accept、rewrite_local_query、search_web、
combine_local_and_web、clarify、stop_with_limitation 之一。
missing_points 只写仍需查证的公开主题，不复制私有文档正文、内部路径或 ACL 信息。
"""


class ResearchEvidenceEvaluator:
    """优先使用结构化输出，失败时兼容普通 JSON，并执行保守降级。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def evaluate(
        self,
        *,
        sub_question: AgentTaskSubQuestion,
        answer: str,
        evidence: list[dict[str, Any]],
        langchain_config: RunnableConfig | None = None,
    ) -> ResearchEvidenceEvaluation:
        """评估一次 Worker 结果；低置信度和零证据都收敛为 insufficient。"""

        if not evidence:
            return _insufficient("当前轮次没有获得可核验证据。")
        # 离线测试不伪造模型调用，但仍给已有证据一个确定性、可回归的判断。
        if not self._settings.openai_api_key:
            return ResearchEvidenceEvaluation(
                verdict="sufficient",
                confidence=0.8,
                relevance=0.8,
                coverage=0.7,
                authority=0.6,
                recommended_action="accept",
                reason="离线模式按存在结构化证据执行确定性评估。",
            )

        payload = {
            "question": sub_question.question,
            "expected_evidence": sub_question.expected_evidence,
            "candidate_answer": answer,
            # 只给 Evaluator 证据摘要；它不需要工具的完整原始消息。
            "evidence": evidence,
        }
        model = ChatOpenAI(
            model=self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.0,
        )
        evaluation = await self._try_structured(model, payload, langchain_config)
        if evaluation is None:
            evaluation = await self._try_json(model, payload, langchain_config)
        if evaluation is None:
            raise ValueError("Evidence Evaluator 未返回有效结构化结果")
        if evaluation.confidence < 0.65:
            return evaluation.model_copy(
                update={
                    "verdict": "insufficient",
                    "recommended_action": "rewrite_local_query",
                    "reason": evaluation.reason or "Evaluator 置信度低于 0.65。",
                }
            )
        return evaluation

    async def _try_structured(
        self,
        model: ChatOpenAI,
        payload: dict[str, Any],
        config: RunnableConfig | None,
    ) -> ResearchEvidenceEvaluation | None:
        for method in ("json_schema", "function_calling"):
            try:
                response = await asyncio.wait_for(
                    model.with_structured_output(
                        ResearchEvidenceEvaluation,
                        method=method,  # type: ignore[arg-type]
                    ).ainvoke(_messages(payload), config=config),
                    timeout=min(self._settings.agent_research_worker_timeout_seconds, 30.0),
                )
                return ResearchEvidenceEvaluation.model_validate(response)
            except Exception as exc:
                logger.warning(
                    "research_evaluator %s",
                    format_log_fields(
                        event="research.evaluator.structured_failed",
                        method=method,
                        error_type=type(exc).__name__,
                    ),
                )
        return None

    async def _try_json(
        self,
        model: ChatOpenAI,
        payload: dict[str, Any],
        config: RunnableConfig | None,
    ) -> ResearchEvidenceEvaluation | None:
        try:
            response = await asyncio.wait_for(
                model.bind(response_format={"type": "json_object"}).ainvoke(
                    _messages(payload), config=config
                ),
                timeout=min(self._settings.agent_research_worker_timeout_seconds, 30.0),
            )
            raw = str(getattr(response, "content", ""))
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if match is None:
                return None
            return ResearchEvidenceEvaluation.model_validate(json.loads(match.group(0)))
        except Exception:
            return None


def _messages(payload: dict[str, Any]) -> list[SystemMessage | HumanMessage]:
    return [
        SystemMessage(content=EVALUATOR_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]


def _insufficient(reason: str) -> ResearchEvidenceEvaluation:
    return ResearchEvidenceEvaluation(
        verdict="insufficient",
        confidence=1.0,
        relevance=0.0,
        coverage=0.0,
        authority=0.0,
        missing_points=["需要取得可核验的证据"],
        recommended_action="rewrite_local_query",
        reason=reason,
    )


__all__ = ["ResearchEvidenceEvaluator"]
