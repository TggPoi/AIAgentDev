from __future__ import annotations

"""把旧 runtime JSON TaskPlan 快照导入 PostgreSQL 事实表。

默认只 dry-run；只有显式 --apply 才写数据库。导入前必须停止旧版本应用，
防止维护窗口中 JSON 继续变化。切换后应用只读 PostgreSQL，旧 JSON 目录
保留一个观察周期即可归档。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.agent_task_plan import AgentTaskPlan
from fast_app.domain.research_task_plan import ResearchTaskPlan
from fast_app.services.agent_tasks.agent_task_plan_repository import (
    AgentTaskPlanRepository,
)
from fast_app.services.exceptions import AgentTaskPlanVersionConflictError


def parse_plan(path: Path) -> AgentTaskPlan | ResearchTaskPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("task_kind") == "question_decomposition":
        if payload.get("schema_version") != 2:
            raise ValueError(f"{path}: Research schema_version 不受支持")
        return ResearchTaskPlan.model_validate(payload)
    return AgentTaskPlan.model_validate(payload)


async def run(*, apply: bool) -> None:
    settings = get_settings()
    directory = Path(settings.agent_task_plan_dir)
    paths = sorted(directory.glob("*_task_plan_*.json"))
    plans = [parse_plan(path) for path in paths]
    ids = [plan.task_plan_id for plan in plans]
    if len(ids) != len(set(ids)):
        raise RuntimeError("发现重复 task_plan_id，必须先人工选择唯一最新快照")

    print(f"snapshot_count={len(plans)}")
    if not apply:
        print("dry_run=passed; use --apply inside maintenance window")
        return

    engine = create_database_engine(settings)
    repository = AgentTaskPlanRepository(create_session_factory(engine))
    imported = 0
    skipped = 0
    try:
        for plan in plans:
            try:
                await repository.create_plan(plan.model_dump(mode="json"))
                imported += 1
            except AgentTaskPlanVersionConflictError:
                existing, _version = await repository.load_snapshot(plan.task_plan_id)
                if existing != plan.model_dump(mode="json"):
                    raise RuntimeError(
                        f"数据库已有不同快照: {plan.task_plan_id}"
                    )
                skipped += 1
    finally:
        await engine.dispose()

    print(f"imported={imported}")
    print(f"identical_skipped={skipped}")
    print("import_agent_task_plan_snapshots=passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
