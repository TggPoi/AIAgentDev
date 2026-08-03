"""兼容入口：SubQuestion 执行契约已由 ResearchTaskPlan v2 编排回归覆盖。"""

from __future__ import annotations

import asyncio

from test_agentic_research_orchestration import main as run_research_v2_checks


if __name__ == "__main__":
    asyncio.run(run_research_v2_checks())
    print("agent_task_sub_question_execution=passed")
