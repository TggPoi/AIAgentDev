from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentToolStep


logger = get_logger(__name__)


TASK_PLANNER_SYSTEM_PROMPT = """你是 Agent 多步骤任务规划器。

你只允许识别白名单任务：knowledge_report_to_document。
这个任务表示：检索知识库资料，生成报告正文，然后保存为知识库文档。

你只能输出 JSON object，不要输出 Markdown。
JSON schema:
{
  "task_kind": "knowledge_report_to_document",
  "goal": "用户目标",
  "source_query": "用于知识库检索的查询",
  "target_path": "知识库内相对路径，例如 development/report.md",
  "report_title": "报告标题",
  "confidence": 0.0-1.0
}

如果用户不是要求“生成报告并保存到知识库文档”，输出 {"confidence": 0.0}。
不要输出报告正文、文档 content、授权结论或确认结论。
"""


class AgentTaskPlanner:
    """把用户目标识别成白名单 AgentTaskPlan。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def plan(
        self,
        query: str,
        history: list[object] | None = None,
        user_id: str | None = None,
    ) -> AgentTaskPlan | None:
        """识别多步骤任务；不执行工具，也不生成报告正文。"""

        if not self._settings.openai_api_key:
            return self._plan_with_rules(query=query, user_id=user_id)

        model = ChatOpenAI(
            model=self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.0,
        ).bind(response_format={"type": "json_object"})

        response = await model.ainvoke(
            [
                SystemMessage(content=TASK_PLANNER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "query": query,
                            "history": [str(item) for item in (history or [])[-6:]],
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        raw = str(getattr(response, "content", ""))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "agent_task_planner %s",
                format_log_fields(
                    event="agent_task_planner.llm.invalid_json",
                    output_preview=raw[:200],
                ),
            )
            return self._plan_with_rules(query=query, user_id=user_id)

        if not isinstance(payload, dict) or _parse_confidence(payload.get("confidence")) < 0.65:
            return self._plan_with_rules(query=query, user_id=user_id)

        return self._plan_from_payload(query=query, payload=payload, user_id=user_id)

    def _plan_with_rules(
        self,
        query: str,
        user_id: str | None,
    ) -> AgentTaskPlan | None:
        """本地兜底：只识别非常明确的“生成报告并保存到文件”请求。"""

        if "报告" not in query or not any(word in query for word in ["保存", "写入", "创建"]):
            return None

        target_path = _extract_target_path(query)
        if target_path is None:
            return None

        source_query = query.split(target_path, 1)[0]
        source_query = re.sub(r"(请你|请|帮我|生成|一份|报告|并|保存|写入|创建|到|为)", " ", source_query)
        source_query = " ".join(source_query.split()) or "知识库资料"
        return self._build_plan(
            user_id=user_id,
            goal=query,
            source_query=source_query,
            target_path=target_path,
            report_title=_build_report_title(source_query),
        )

    def _plan_from_payload(
        self,
        query: str,
        payload: dict[str, Any],
        user_id: str | None = None,
    ) -> AgentTaskPlan | None:
        """把 LLM JSON 收敛成白名单任务计划，忽略任何正文类字段。"""

        if payload.get("task_kind") != "knowledge_report_to_document":
            return None

        target_path = str(payload.get("target_path") or "").strip().replace("\\", "/")
        if not target_path or not target_path.endswith((".md", ".txt")):
            return None

        source_query = str(payload.get("source_query") or "").strip()
        if not source_query:
            return None

        return self._build_plan(
            user_id=user_id,
            goal=str(payload.get("goal") or query).strip() or query,
            source_query=source_query,
            target_path=target_path,
            report_title=str(payload.get("report_title") or _build_report_title(source_query)).strip(),
        )

    def _build_plan(
        self,
        user_id: str | None,
        goal: str,
        source_query: str,
        target_path: str,
        report_title: str,
    ) -> AgentTaskPlan:
        now = datetime.now(UTC)
        task_plan_id = f"task_plan_{now.strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}"
        return AgentTaskPlan(
            task_plan_id=task_plan_id,
            task_kind="knowledge_report_to_document",
            user_id=user_id,
            goal=goal,
            source_query=source_query,
            target_path=target_path,
            report_title=report_title,
            created_at=now,
            updated_at=now,
            steps=[
                AgentToolStep(
                    step_id="step_1_retrieve",
                    tool_name="knowledge_retrieval",
                    input={"query": source_query},
                    risk_level="low",
                ),
                AgentToolStep(
                    step_id="step_2_summarize",
                    tool_name="summarize_report",
                    input={"report_title": report_title},
                    risk_level="low",
                ),
                AgentToolStep(
                    step_id="step_3_create_document",
                    tool_name="knowledge_document_create",
                    input={"target_path": target_path},
                    risk_level="medium",
                    requires_approval=True,
                ),
            ],
        )


def _extract_target_path(query: str) -> str | None:
    match = re.search(r"([A-Za-z0-9_\-./\\]+?\.(?:md|txt))", query)
    if match is None:
        return None
    return match.group(1).replace("\\", "/")


def _build_report_title(source_query: str) -> str:
    return f"{source_query[:40]}报告"


def _parse_confidence(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["AgentTaskPlanner"]
