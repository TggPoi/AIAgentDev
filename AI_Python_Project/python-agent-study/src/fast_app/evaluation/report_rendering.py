from fast_app.evaluation.offline_eval_models import OfflineRagEvalReport


def escape_markdown_table_cell(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def format_bool(value: bool) -> str:
    return "PASS" if value else "FAIL"


def render_offline_eval_summary(report: OfflineRagEvalReport) -> list[str]:
    retrieval = report.retrieval_report
    generation = report.generation_report

    return [
        "# RAG Offline Evaluation Report",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| dataset | {escape_markdown_table_cell(report.dataset_name)} |",
        f"| case_count | {report.case_count} |",
        f"| response_count | {report.response_count} |",
        f"| retrieval_mean_recall_at_k | {retrieval.mean_recall_at_k:.4f} |",
        f"| retrieval_mean_mrr | {retrieval.mean_mrr:.4f} |",
        f"| retrieval_passed | {retrieval.passed_case_count}/{retrieval.evaluated_case_count} |",
        f"| generation_pass_rate | {generation.pass_rate:.4f} |",
        f"| generation_passed | {generation.passed_case_count}/{generation.evaluated_case_count} |",
        "",
    ]


def render_retrieval_results(report: OfflineRagEvalReport) -> list[str]:
    lines = [
        "## Retrieval Results",
        "",
        "| Case | Passed | Recall@K | MRR | First Hit Rank | Hits |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]

    for result in report.retrieval_report.results:
        hit_ids = ", ".join(hit.doc_id for hit in result.hits)
        lines.append(
            "| "
            f"{escape_markdown_table_cell(result.case_id)} | "
            f"{format_bool(result.passed)} | "
            f"{result.recall_at_k:.4f} | "
            f"{result.reciprocal_rank:.4f} | "
            f"{result.first_hit_rank or ''} | "
            f"{escape_markdown_table_cell(hit_ids)} |"
        )

    lines.append("")
    return lines


def render_generation_results(report: OfflineRagEvalReport) -> list[str]:
    lines = [
        "## Generation Results",
        "",
        "| Case | Type | Passed | Answer Length | Source Count | Failed Checks |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]

    for result in report.generation_report.results:
        failed_checks = [
            check.name
            for check in result.checks
            if not check.passed
        ]
        lines.append(
            "| "
            f"{escape_markdown_table_cell(result.case_id)} | "
            f"{result.case_type} | "
            f"{format_bool(result.passed)} | "
            f"{result.answer_length} | "
            f"{result.source_count} | "
            f"{escape_markdown_table_cell(', '.join(failed_checks))} |"
        )

    lines.append("")
    return lines


def render_failed_generation_details(report: OfflineRagEvalReport) -> list[str]:
    lines = [
        "## Failed Generation Details",
        "",
    ]

    failed_results = [
        result
        for result in report.generation_report.results
        if not result.passed
    ]

    if not failed_results:
        lines.append("No failed generation cases.")
        lines.append("")
        return lines

    for result in failed_results:
        lines.append(f"### {result.case_id}")
        lines.append("")
        lines.append(f"- question: {result.question}")
        lines.append(f"- case_type: {result.case_type}")
        lines.append("")

        for check in result.checks:
            if check.passed:
                continue

            lines.append(
                f"- {check.name}: {check.message}; detail={check.detail}"
            )

        lines.append("")

    return lines


def render_offline_eval_markdown(report: OfflineRagEvalReport) -> str:
    lines: list[str] = []
    lines.extend(render_offline_eval_summary(report))
    lines.extend(render_retrieval_results(report))
    lines.extend(render_generation_results(report))
    lines.extend(render_failed_generation_details(report))

    return "\n".join(lines).rstrip() + "\n"
