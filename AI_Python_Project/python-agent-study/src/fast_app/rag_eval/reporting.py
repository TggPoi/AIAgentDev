"""轻量 Eval 的稳定 JSON、Markdown 和基线对比输出。"""

from __future__ import annotations

import json
from pathlib import Path

from fast_app.rag_eval.models import RagEvalRunReport


def apply_baseline(
    report: RagEvalRunReport,
    baseline: RagEvalRunReport,
    *,
    baseline_path: str,
) -> RagEvalRunReport:
    """按相同指标机器名写入宏平均变化，不掩盖 provider/dataset 差异。"""

    if report.pipeline_provider != baseline.pipeline_provider:
        raise ValueError("基线报告的 pipeline_provider 与当前运行不一致")
    if (
        report.dataset_id != baseline.dataset_id
        or report.dataset_version != baseline.dataset_version
    ):
        raise ValueError("基线报告的 dataset 身份或版本与当前运行不一致")

    summaries = dict(report.metric_summaries)
    for name, current in report.metric_summaries.items():
        previous = baseline.metric_summaries.get(name)
        delta = None
        if (
            current.mean_score is not None
            and previous is not None
            and previous.mean_score is not None
        ):
            delta = current.mean_score - previous.mean_score
        summaries[name] = current.model_copy(update={"baseline_delta": delta})
    return report.model_copy(
        update={
            "metric_summaries": summaries,
            "baseline_report": baseline_path,
        }
    )


def load_report(path: str | Path) -> RagEvalRunReport:
    return RagEvalRunReport.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_reports(
    report: RagEvalRunReport,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"rag-eval-{report.pipeline_provider}-{report.run_id}"
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    payload = report.model_dump(mode="json")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: RagEvalRunReport) -> str:
    lines = [
        "# 轻量流式 RAG Eval 报告",
        "",
        f"- Run ID: `{report.run_id}`",
        f"- Provider: `{report.pipeline_provider}`",
        f"- Status: `{report.status}`",
        f"- Dataset: `{report.dataset_id}@{report.dataset_version}`",
        f"- Knowledge revision: `{report.source_revision}`",
        f"- Tested model: `{report.tested_model}`",
        f"- Judge model: `{report.judge_model or 'N/A'}`",
        f"- Cases: {report.case_count} (evaluated={report.evaluated_case_count}, failed={report.failed_case_count}, skipped={report.skipped_case_count})",
        f"- Duration: {report.duration_ms:.2f} ms",
    ]
    if report.baseline_report:
        lines.append(f"- Baseline: `{report.baseline_report}`")
    lines.extend(
        [
            "",
            "## 指标汇总",
            "",
            "| Metric | Mean | Evaluated | Passed | Skipped | Errors | Baseline Δ |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name in report.selected_metrics:
        summary = report.metric_summaries[name]
        mean = "N/A" if summary.mean_score is None else f"{summary.mean_score:.4f}"
        delta = (
            "N/A"
            if summary.baseline_delta is None
            else f"{summary.baseline_delta:+.4f}"
        )
        lines.append(
            f"| `{name}` | {mean} | {summary.evaluated_count} | "
            f"{summary.passed_count} | {summary.skipped_count} | "
            f"{summary.error_count} | {delta} |"
        )

    lines.extend(
        [
            "",
            "## Case 明细",
            "",
            "| Case | Status | Actual route | Retrieval | Knowledge version | Latency ms | Error |",
            "|---|---|---|---:|---:|---:|---|",
        ]
    )
    for case in report.cases:
        error = ""
        if case.error is not None:
            error = f"{case.error.code}: {case.error.message}"
        elif case.skipped_reason:
            error = case.skipped_reason
        error = error.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{case.case_id}` | {case.status} | "
            f"`{case.actual_route or 'N/A'}` | "
            f"{'yes' if case.knowledge_retrieval_performed else 'no'} | "
            f"{case.knowledge_version if case.knowledge_version is not None else 'N/A'} | "
            f"{case.latency_ms:.2f} | {error} |"
        )
    lines.extend(
        [
            "",
            "## Case 指标明细",
            "",
            "| Case | Metric | Status | Score | Passed | Reason / Error |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for case in report.cases:
        for name in report.selected_metrics:
            result = case.metrics.get(name)
            if result is None:
                continue
            score = "N/A" if result.score is None else f"{result.score:.4f}"
            passed = "N/A" if result.passed is None else str(result.passed).lower()
            detail = (
                f"{result.error.code}: {result.error.message}"
                if result.error is not None
                else result.short_reason
            )
            detail = detail.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{case.case_id}` | `{name}` | {result.status} | "
                f"{score} | {passed} | {detail} |"
            )
    policies = [
        (case.case_id, case.retrieval_source_policy)
        for case in report.cases
        if case.retrieval_source_policy is not None
    ]
    if policies:
        lines.extend(
            [
                "",
                "## 检索来源策略",
                "",
                "| Case | Passed | Matched authoritative | Missing authoritative | Forbidden retrieved |",
                "|---|---|---|---|---|",
            ]
        )
        for case_id, policy in policies:
            assert policy is not None
            matched = ", ".join(policy.matched_authoritative_logical_ids) or "N/A"
            missing = ", ".join(policy.missing_authoritative_logical_ids) or "N/A"
            forbidden = ", ".join(policy.forbidden_retrieved_logical_ids) or "N/A"
            lines.append(
                f"| `{case_id}` | {str(policy.passed).lower()} | "
                f"{matched} | {missing} | {forbidden} |"
            )
    lines.append("")
    return "\n".join(lines)


__all__ = ["apply_baseline", "load_report", "render_markdown", "write_reports"]
