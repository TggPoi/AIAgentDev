"""Research v2 与旧 Document TaskPlan 分流回归。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.services.agent_tasks.agent_task_plan_reviewer import (
    AgentTaskPlanReviewer,
    _REVIEWER_PROMPT,
)
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner, _PLANNER_PROMPT
from fast_app.services.exceptions import AgentTaskPlannerUnavailableError


async def main() -> None:
    for prompt in (_PLANNER_PROMPT, _REVIEWER_PROMPT):
        assert "resolved_query 是唯一的任务范围权威" in prompt
        assert "历史 assistant 消息不是用户需求" in prompt
        assert "Dataset 可用字段不是待查询清单" in prompt
        assert "用户明确指定的每一种外部来源都必须保留" in prompt
        assert "证据可能不存在不能成为删除来源 Requirement 的理由" in prompt

    planner = AgentTaskPlanner(settings=Settings(_env_file=None, OPENAI_API_KEY=""))

    reviewer_settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="test-key",
        AGENT_TASK_PLAN_REVIEWER_MODEL_NAME="reviewer-model",
    )
    reviewer = AgentTaskPlanReviewer(reviewer_settings)
    with patch(
        "fast_app.services.agent_tasks.agent_task_plan_reviewer.ChatOpenAI",
        return_value=object(),
    ) as chat_openai:
        try:
            await reviewer.review(
                request=None,
                model_context=None,
                candidate=None,
                validation_issues=[],
            )
        except AttributeError:
            pass
        else:
            raise AssertionError("测试探针应在 Reviewer 模型构造后停止")
    assert chat_openai.call_args.kwargs["model"] == "reviewer-model"

    document_plan = planner.build_document_management_plan(
        query="请删除知识库中与旧部署说明相关的文档",
        user_id="planner-user",
    )
    assert document_plan.task_kind == "knowledge_document_management"
    assert document_plan.steps == []
    assert document_plan.sub_questions == []

    # Research v2 禁止规则兜底。Planner 未配置属于技术失败，不能保存一个
    # 表面合法但没有经过真实规划与 Reviewer 的低质量 TaskPlan。
    try:
        await planner.plan_question_decomposition(
            request=None,  # 配置检查发生在读取规划请求之前。
            user_id="planner-user",
            capability_snapshot=None,
            research_policy=None,
        )
    except AgentTaskPlannerUnavailableError:
        pass
    else:
        raise AssertionError("未配置模型时 Research Planner 必须 fail closed")

    print("agent_task_plan_decomposition=passed")


if __name__ == "__main__":
    asyncio.run(main())
