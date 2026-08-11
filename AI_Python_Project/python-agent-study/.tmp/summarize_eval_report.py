"""汇总 rag-eval 报告：逐 case 状态、路由与检索指标。"""

from __future__ import annotations

import glob
import json
import sys


def main(directory: str) -> None:
    path = glob.glob(f"{directory}/*.json")[0]
    data = json.loads(open(path, encoding="utf-8").read())
    print(
        "status:", data["status"],
        "| evaluated:", data["evaluated_case_count"],
        "failed:", data["failed_case_count"],
        "skipped:", data["skipped_case_count"],
    )
    for name, summary in data["metric_summaries"].items():
        mean = summary["mean_score"]
        mean_text = "N/A" if mean is None else f"{mean:.4f}"
        print(
            f"  {name:<28} mean={mean_text} passed={summary['passed_count']}"
            f"/{summary['evaluated_count']}"
        )
    for case in data["cases"]:
        error = case.get("error") or {}
        code = error.get("code") or ""
        route = str(case["actual_route"])
        recall = case["metrics"].get("retrieval_recall_at_k")
        if recall is None or recall.get("score") is None:
            recall_text = "N/A"
        else:
            recall_text = f"recall={recall['score']:.2f}"
        print(
            f"{case['case_id']:<40} {case['status']:<10} "
            f"{route:<46} {recall_text:<12} {code}"
        )


if __name__ == "__main__":
    main(sys.argv[1])
