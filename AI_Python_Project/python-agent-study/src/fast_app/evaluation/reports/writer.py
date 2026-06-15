import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fast_app.evaluation.pipeline.models import OfflineRagEvalReport
from fast_app.evaluation.reports.rendering import render_offline_eval_markdown
from fast_app.evaluation.reports.serialization import to_jsonable


@dataclass(frozen=True)
class WrittenEvalReportPaths:
    json_path: Path
    markdown_path: Path


def build_report_file_stem(
    dataset_name: str,
    timestamp: datetime | None = None,
) -> str:
    current = timestamp or datetime.now()
    formatted = current.strftime("%Y%m%d-%H%M%S")
    safe_dataset_name = dataset_name.replace("/", "_").replace("\\", "_")

    return f"{safe_dataset_name}-{formatted}"


def write_offline_eval_report(
    report: OfflineRagEvalReport,
    output_dir: str | Path = "reports/evaluation",
    timestamp: datetime | None = None,
) -> WrittenEvalReportPaths:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    file_stem = build_report_file_stem(
        dataset_name=report.dataset_name,
        timestamp=timestamp,
    )
    json_path = root / f"{file_stem}.json"
    markdown_path = root / f"{file_stem}.md"

    json_path.write_text(
        json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_offline_eval_markdown(report),
        encoding="utf-8",
    )

    return WrittenEvalReportPaths(
        json_path=json_path,
        markdown_path=markdown_path,
    )

