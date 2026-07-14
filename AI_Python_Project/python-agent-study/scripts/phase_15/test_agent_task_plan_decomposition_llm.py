from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.services.agent_task_planner import AgentTaskPlanner


QUERY = (
    "请对比 RAG 系统中的混合检索、rerank、权限设计和 Prompt Guard "
    "之间的关系，并说明它们如何共同影响回答质量与安全边界"
)


async def main() -> None:
    settings = Settings()
    planner = AgentTaskPlanner(settings=settings)
    # 手动观察真实 LLM 拆解结果：不做断言，避免模型表述变化导致验收脚本不稳定。
    plan = await planner.plan_question_decomposition(
        query=QUERY,
        user_id="manual-llm-test-user",
    )
    if plan is None:
        print("plan=None")
        return

    print(
        json.dumps(
            {
                "llm_model_name": settings.llm_model_name,
                "openai_base_url": settings.openai_base_url,
                "has_openai_api_key": bool(settings.openai_api_key),
                "task_plan_id": plan.task_plan_id,
                "task_kind": plan.task_kind,
                "task_type": plan.task_type,
                "target_path": plan.target_path,
                "steps_count": len(plan.steps),
                "source_query": plan.source_query,
                "sub_questions": [
                    item.model_dump(mode="json") for item in plan.sub_questions
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
