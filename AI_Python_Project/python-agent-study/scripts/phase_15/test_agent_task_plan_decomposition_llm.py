"""使用当前真实模型人工观察 ResearchTaskPlan v2。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.domain.research_task_plan import (
    AgentTaskCapabilitySnapshot,
    ResolvedPlanningRequest,
    ResearchTaskPolicy,
)
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner


QUERY = (
    "根据当前知识库，分别说明混合检索、Rerank 和 Prompt Guard 的职责，"
    "并分析它们在一次 RAG 请求中的先后关系与协作边界。"
)


async def main() -> None:
    settings = Settings()
    planner = AgentTaskPlanner(settings=settings)
    plan = await planner.plan_question_decomposition(
        request=ResolvedPlanningRequest(
            current_query=QUERY,
            relevant_history=[],
            resolved_query=QUERY,
        ),
        user_id="manual-llm-test-user",
        capability_snapshot=AgentTaskCapabilitySnapshot(
            available_source_types=["knowledge_retrieval"],
            knowledge_retrieval_available=True,
            web_direct_allowed=False,
            web_fallback_allowed=False,
            nl2sql_query_available=False,
            max_requirements=10,
            max_sub_questions=6,
        ),
        research_policy=ResearchTaskPolicy(
            mode="hybrid",
            top_k=5,
            min_score=0.0,
            allow_direct_web=False,
            allow_web_fallback=False,
        ),
    )
    print(
        json.dumps(
            {
                "llm_model_name": settings.llm_model_name,
                "task_plan_id": plan.task_plan_id,
                "schema_version": plan.schema_version,
                "requirements": [item.model_dump(mode="json") for item in plan.requirements],
                "sub_questions": [item.model_dump(mode="json") for item in plan.sub_questions],
                "quality_review": plan.quality_review.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
