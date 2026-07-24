"""CLI for the product-style secure FL audit package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from audit.hashing import compute_record_hash
from audit.reporting import build_audit_report
from audit.verifier import load_jsonl, load_public_keys, verify_audit_package, verify_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify and inspect secure federated learning audit packages."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="Verify an audit package")
    verify.add_argument("--package", required=True, type=Path)

    report = subparsers.add_parser("report", help="Print a verification report")
    report.add_argument("--package", required=True, type=Path)

    inspect_round = subparsers.add_parser("inspect-round", help="Inspect one round")
    inspect_round.add_argument("--package", required=True, type=Path)
    inspect_round.add_argument("--round", required=True, type=int)

    tamper = subparsers.add_parser(
        "tamper-demo", help="Modify one record in memory and show verification failure"
    )
    tamper.add_argument("--package", required=True, type=Path)
    tamper.add_argument("--record-index", type=int, default=1)
    tamper.add_argument(
        "--mode",
        choices=["hash", "signature"],
        default="hash",
        help="Tamper mode. hash changes data without recomputing hash. signature changes signature and recomputes record hash.",
    )
    return parser.parse_args()


def package_paths(package: Path):
    return package / "ledger.jsonl", package / "public_keys.json"


def command_verify(package: Path) -> int:
    result = verify_audit_package(package)
    print(f"Status: {result.status}")
    print(f"Valid: {result.valid}")
    print(f"Checked records: {result.checked_records}")
    print(f"Checked signatures: {result.checked_signatures}")
    print(f"Checked Merkle proofs: {result.checked_merkle_proofs}")
    print(f"Broken record: {result.broken_record}")
    print(f"Reason: {result.reason}")
    return 0 if result.valid else 1


def command_report(package: Path) -> int:
    ledger_path, public_keys_path = package_paths(package)
    records = load_jsonl(ledger_path)
    result = verify_records(records, load_public_keys(public_keys_path))
    experiment_name = records[0].get("experiment_name", package.name) if records else package.name
    print(build_audit_report(experiment_name, records, result))
    return 0 if result.valid else 1


def command_inspect_round(package: Path, round_number: int) -> int:
    records = load_jsonl(package / "ledger.jsonl")
    matches = [
        record
        for record in records
        if record.get("record_type") == "round"
        and int(record.get("round_number", -1)) == round_number
    ]
    if not matches:
        print(f"Round not found: {round_number}")
        return 1
    record = matches[0]
    summary = {
        "record_index": record.get("record_index"),
        "round_number": record.get("round_number"),
        "timestamp": record.get("timestamp"),
        "security_mode": record.get("security_mode"),
        "topology": record.get("topology"),
        "split_type": record.get("split_type"),
        "adaptive_policy": record.get("adaptive_policy"),
        "adaptive_selected_targets": record.get("adaptive_selected_targets"),
        "metrics": record.get("metrics"),
        "merkle_root": record.get("merkle_root"),
        "signature_count": len(record.get("client_signatures", {})),
        "record_hash": record.get("record_hash"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def command_tamper_demo(package: Path, record_index: int, mode: str) -> int:
    ledger_path, public_keys_path = package_paths(package)
    records = load_jsonl(ledger_path)
    public_keys = load_public_keys(public_keys_path)
    if not records:
        print("No records found")
        return 1
    target = min(max(record_index, 0), len(records) - 1)
    record = records[target]
    if mode == "hash":
        if record.get("record_type") == "round":
            record["metrics"]["avg_test_accuracy"] = (
                float(record["metrics"].get("avg_test_accuracy", 0.0)) + 1.0
            )
        else:
            record["timestamp"] = "tampered"
    else:
        if record.get("record_type") != "round":
            print("Signature tamper demo needs a round record")
            return 1
        first_client = sorted(record["client_signatures"])[0]
        record["client_signatures"][first_client]["signature"] = "tampered_signature"
        record["record_hash"] = compute_record_hash(record)

    result = verify_records(records, public_keys)
    print(f"Status: {result.status}")
    print(f"Valid: {result.valid}")
    print(f"Broken record: {result.broken_record}")
    print(f"Reason: {result.reason}")
    return 0 if not result.valid else 1


def main() -> int:
    args = parse_args()
    if args.command == "verify":
        return command_verify(args.package)
    if args.command == "report":
        return command_report(args.package)
    if args.command == "inspect-round":
        return command_inspect_round(args.package, args.round)
    if args.command == "tamper-demo":
        return command_tamper_demo(args.package, args.record_index, args.mode)
    raise ValueError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
