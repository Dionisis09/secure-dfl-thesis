"""Demonstrate that audit-log tampering is detected."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from verify_audit_logs import discover_audit_logs, verify_audit_file


def tamper_first_mutable_record(source: Path, destination: Path) -> None:
    lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line]
    if not lines:
        raise ValueError(f"audit log is empty: {source}")
    records = [json.loads(line) for line in lines]
    target_index = 0
    for index, record in enumerate(records):
        if record.get("event_type") != "node_started":
            target_index = index
            break
    record = records[target_index]
    details = record.setdefault("details", {})
    if not isinstance(details, dict):
        record["details"] = {"tampered": True}
    else:
        details["tampered"] = True
    destination.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy and tamper one audit log, then verify detection")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--trusted-keys", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trusted_keys = Path(args.trusted_keys) if args.trusted_keys else None
    logs = discover_audit_logs(Path(args.runtime_dir))
    if not logs:
        raise SystemExit("No audit logs found")

    original = logs[0]
    original_result = verify_audit_file(original, trusted_keys)
    if not original_result["valid"]:
        raise SystemExit(f"Original log is not valid: {original_result['errors']}")

    with tempfile.TemporaryDirectory(prefix="secure_dfl_tamper_") as tmp:
        tmp_path = Path(tmp)
        tampered = tmp_path / "node_audit_tampered.jsonl"
        shutil.copy2(original, tampered)
        tamper_first_mutable_record(original, tampered)
        tampered_result = verify_audit_file(tampered, trusted_keys)
        report: dict[str, Any] = {
            "status": "PASS" if not tampered_result["valid"] else "FAIL",
            "original_log": str(original),
            "tampered_copy": str(tampered),
            "original_valid": original_result["valid"],
            "tampered_valid": tampered_result["valid"],
            "detected_errors": tampered_result["errors"],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "PASS":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
