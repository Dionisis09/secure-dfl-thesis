"""Run a compact validation matrix for the Secure DFL Platform MVP."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": time.time() - started,
        "output_tail": completed.stdout[-4000:],
        "passed": completed.returncode == 0,
    }


def write_report(output_dir: Path, results: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for item in results if item["passed"])
    summary = {
        "status": "PASS" if passed == len(results) else "FAIL",
        "checks_total": len(results),
        "checks_passed": passed,
        "checks_failed": len(results) - passed,
        "duration_seconds": sum(float(item["duration_seconds"]) for item in results),
        "results": results,
    }
    (output_dir / "platform_validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# Secure DFL Platform Validation Summary",
        "",
        f"Status: `{summary['status']}`",
        f"Checks passed: `{passed}/{len(results)}`",
        f"Total command duration: `{summary['duration_seconds']:.2f}s`",
        "",
        "|Check|Status|Duration (s)|",
        "|---|---|---|",
    ]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"|{index}. `{Path(item['command'][1]).name if len(item['command']) > 1 else item['command'][0]}`|"
            f"{'PASS' if item['passed'] else 'FAIL'}|{item['duration_seconds']:.2f}|"
        )
    lines.append("")
    (output_dir / "platform_validation_summary.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] != "PASS":
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Secure DFL platform validation matrix")
    parser.add_argument("--output-dir", default="results/platform_validation")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    baseline_id = f"validation_baseline_{stamp}"
    masking_id = f"validation_masking_{stamp}"
    pairwise_id = f"validation_pairwise_{stamp}"
    quorum_id = f"validation_quorum_{stamp}"

    py = sys.executable
    commands = [
        [py, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ["docker-compose", "-f", "docker-compose.real-keys.yml", "config"],
        [py, "demo_stack.py", "--experiment-id", baseline_id, "--rounds", "1", "--security-mode", "none", "--keep-alive-seconds", "0"],
        [py, "demo_stack.py", "--experiment-id", masking_id, "--rounds", "1", "--security-mode", "masking", "--keep-alive-seconds", "0"],
        [py, "demo_stack.py", "--experiment-id", pairwise_id, "--rounds", "1", "--security-mode", "pairwise_masking", "--keep-alive-seconds", "0"],
        [py, "demo_stack.py", "--experiment-id", quorum_id, "--rounds", "1", "--security-mode", "masking", "--min-peer-updates-to-finalize", "1", "--keep-alive-seconds", "0"],
        [py, "tamper_audit_demo.py", "--runtime-dir", f"results/demo_stack/{masking_id}/runtime", "--trusted-keys", f"results/demo_stack/{masking_id}/deployment_keys/trusted_keys.json"],
        [py, "compare_demo_stack_results.py", f"results/demo_stack/{baseline_id}", f"results/demo_stack/{masking_id}", "--output-dir", f"results/platform_validation/comparison_{stamp}"],
    ]
    results = [run_command(command, root) for command in commands]
    write_report(Path(args.output_dir) / stamp, results)


if __name__ == "__main__":
    main()
