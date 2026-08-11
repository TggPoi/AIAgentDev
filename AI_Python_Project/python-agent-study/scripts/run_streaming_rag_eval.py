"""对真实 /rag/chat/stream/events 执行独立轻量 RAG Eval。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path


DEFAULT_DATASET = Path(
    "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.0.0.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline-provider",
        required=True,
        choices=("classic", "langgraph", "rag_agent"),
        help="一次运行只选择一个真实 RAG provider。",
    )
    parser.add_argument(
        "--mode",
        choices=("retrieval", "generation", "all"),
        default="all",
        help="执行检索层、生成层或全部指标。",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="只执行指定 case；可以重复传入。",
    )
    parser.add_argument("--max-cases", type=int)
    parser.add_argument(
        "--eval-principal",
        help=(
            "只执行 eval_principal_id 等于该值的 case；"
            "一次运行只能用一个 API Key/Bearer 身份，多身份数据集需按身份分别运行。"
        ),
    )
    parser.add_argument(
        "--metrics",
        help="逗号分隔的指标机器名；默认执行当前 mode 的全部指标。",
    )
    parser.add_argument("--include-judge-reason", action="store_true")
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/rag-eval"))
    return parser.parse_args()


async def run(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.max_cases is not None and args.max_cases < 1:
        raise ValueError("--max-cases 必须大于等于 1")

    os.environ["RAG_PIPELINE_PROVIDER"] = args.pipeline_provider

    # provider 环境必须在导入 fast_app.main 和构造全局依赖前固定。
    from fast_app.core.config import get_settings
    from fast_app.evaluation.cases.loader import load_eval_dataset
    from fast_app.main import app
    from fast_app.rag_eval.generation import SubprocessGenerationEvaluator
    from fast_app.rag_eval.reporting import apply_baseline, load_report, write_reports
    from fast_app.rag_eval.runner import (
        GENERATION_METRIC_NAMES,
        LightweightRagEvalRunner,
        metrics_for_mode,
    )
    from fast_app.rag_eval.target import InProcessStructuredStreamTarget, RagEvalAuth

    settings = get_settings()
    # load_eval_dataset 已校验 content_sha256 与 source_revision；
    # candidate 数据集允许先跑检索层试跑，golden 门禁由数据集文件 lifecycle 表达。
    dataset = load_eval_dataset(
        args.dataset,
        verify_source_revision=True,
        repository_root=Path.cwd(),
    )
    cases = dataset.cases
    if args.eval_principal:
        cases = [
            case for case in cases if case.eval_principal_id == args.eval_principal
        ]
        if not cases:
            raise ValueError(
                f"数据集中没有 eval_principal_id={args.eval_principal} 的 case"
            )
    if args.case_id:
        requested = set(args.case_id)
        known = {case.case_id for case in cases}
        missing = sorted(requested - known)
        if missing:
            raise ValueError(f"未知 --case-id: {missing}")
        cases = [case for case in cases if case.case_id in requested]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    dataset = dataset.model_copy(update={"cases": cases})

    allowed = metrics_for_mode(args.mode)
    if args.metrics:
        selected = [value.strip() for value in args.metrics.split(",") if value.strip()]
        invalid = [name for name in selected if name not in allowed]
        if invalid:
            raise ValueError(f"--metrics 与 mode 不匹配或名称未知: {invalid}")
    else:
        selected = list(allowed)

    generation_evaluator = None
    if any(name in GENERATION_METRIC_NAMES for name in selected):
        generation_evaluator = SubprocessGenerationEvaluator(project_root=Path.cwd())

    auth = RagEvalAuth.from_environment(settings)
    target = InProcessStructuredStreamTarget(
        app=app,
        settings=settings,
        pipeline_provider=args.pipeline_provider,
        auth=auth,
    )
    runner = LightweightRagEvalRunner(
        target=target,
        settings=settings,
        pipeline_provider=args.pipeline_provider,
        mode=args.mode,
        selected_metrics=selected,
        generation_evaluator=generation_evaluator,
        include_judge_reason=args.include_judge_reason,
        # candidate 数据集允许试跑；正式回归仍以 golden lifecycle 为门禁。
        allow_candidate=dataset.lifecycle != "golden",
    )

    async with app.router.lifespan_context(app):
        report = await runner.run(dataset)
    if args.baseline_report:
        report = apply_baseline(
            report,
            load_report(args.baseline_report),
            baseline_path=str(args.baseline_report),
        )
    return write_reports(report, args.output_dir)


def main() -> int:
    args = parse_args()
    try:
        json_path, markdown_path = asyncio.run(run(args))
    except Exception as exc:
        print(f"RAG Eval 失败: {type(exc).__name__}: {exc}")
        return 1
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
