"""Compare Secure DFL demo stack result packages."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_summary(path: Path) -> dict[str, Any]:
    summary_path = path / "summary.json" if path.is_dir() else path
    return json.loads(summary_path.read_text(encoding="utf-8"))


def flatten_summary(summary: dict[str, Any]) -> dict[str, Any]:
    dashboard = summary["dashboard_after"]
    audit = summary["audit_report"]
    return {
        "experiment_id": summary["experiment_id"],
        "status": summary["status"],
        "security_mode": summary.get("security_mode", "none"),
        "rounds": summary["rounds"],
        "nodes_total": dashboard["nodes_total"],
        "nodes_online": dashboard["nodes_online"],
        "finalized_node_rounds": dashboard["finalized_rounds"],
        "partial_node_rounds": dashboard["partial_rounds"],
        "network_exchanges": summary["demo_result"]["network_exchanges"],
        "masked_updates_total": dashboard.get("masked_updates_total", 0),
        "masking_overhead_bytes_total": dashboard.get("masking_overhead_bytes_total", 0),
        "send_failures_total": dashboard["send_failures_total"],
        "audit_status": audit["status"],
        "audit_logs_checked": audit["audit_logs_checked"],
        "audit_records_checked": audit["total_records"],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    lines = [
        "# Secure DFL Demo Stack Comparison",
        "",
        "|" + "|".join(columns) + "|",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        lines.append("|" + "|".join(str(row[column]) for column in columns) + "|")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare demo stack summary.json files")
    parser.add_argument("runs", nargs="+", help="Run directories or summary.json files")
    parser.add_argument("--output-dir", default="results/demo_stack/comparison")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = [flatten_summary(load_summary(Path(item))) for item in args.runs]
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "demo_stack_comparison.csv", rows)
    write_markdown(output_dir / "demo_stack_comparison.md", rows)
    print(json.dumps({"status": "PASS", "runs": len(rows), "output_dir": str(output_dir)}, indent=2))


if __name__ == "__main__":
    main()
