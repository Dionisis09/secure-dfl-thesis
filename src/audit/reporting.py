"""Reports and CSV exports for the product-style audit package."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from .hashing import stable_json


def build_audit_summary_csv(records: List[Dict[str, Any]], path: Path, verification) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_index",
        "record_type",
        "round",
        "timestamp",
        "security_mode",
        "num_clients",
        "topology",
        "split_type",
        "adaptive_policy",
        "accuracy",
        "loss",
        "communication_bytes",
        "merkle_root",
        "record_hash",
        "previous_hash",
        "signature_count",
        "verification_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            metrics = record.get("metrics", {})
            signatures = record.get("client_signatures", {})
            writer.writerow(
                {
                    "record_index": record.get("record_index", ""),
                    "record_type": record.get("record_type", ""),
                    "round": record.get("round_number", ""),
                    "timestamp": record.get("timestamp", ""),
                    "security_mode": record.get("security_mode", ""),
                    "num_clients": record.get("num_clients", ""),
                    "topology": record.get("topology", ""),
                    "split_type": record.get("split_type", ""),
                    "adaptive_policy": record.get("adaptive_policy", ""),
                    "accuracy": metrics.get("avg_test_accuracy", ""),
                    "loss": metrics.get("avg_test_loss", ""),
                    "communication_bytes": metrics.get("communication_bytes", ""),
                    "merkle_root": record.get("merkle_root", ""),
                    "record_hash": record.get("record_hash", ""),
                    "previous_hash": record.get("previous_hash", ""),
                    "signature_count": len(signatures),
                    "verification_status": verification.status,
                }
            )


def build_audit_report(experiment_name: str, records: List[Dict[str, Any]], verification) -> str:
    round_records = [r for r in records if r.get("record_type") == "round"]
    final_accuracy = ""
    if round_records:
        final_accuracy = f"{round_records[-1]['metrics']['avg_test_accuracy']:.2f}%"
    return "\n".join(
        [
            "Secure Federated Learning Audit Report",
            "",
            f"Experiment: {experiment_name}",
            f"Records: {len(records)}",
            f"Round records: {len(round_records)}",
            f"Verification status: {verification.status}",
            f"Hash chain: {'PASSED' if verification.valid else 'FAILED'}",
            f"Signature verification: {'PASSED' if verification.valid else 'FAILED'}",
            f"Merkle verification: {'PASSED' if verification.valid else 'FAILED'}",
            f"Checked signatures: {verification.checked_signatures}",
            f"Checked Merkle proofs: {verification.checked_merkle_proofs}",
            f"Broken record: {verification.broken_record if verification.broken_record is not None else 'None'}",
            f"Reason: {verification.reason or 'None'}",
            f"Final accuracy: {final_accuracy}",
            "",
            "Interpretation:",
            "The audit package verifies that exported round records, client model hashes, Merkle roots and Ed25519 client signatures are internally consistent.",
            "",
        ]
    )


def build_statistics(records: List[Dict[str, Any]], verification) -> str:
    sizes = [len(stable_json(record).encode("utf-8")) for record in records]
    hashes = [record.get("record_hash", "") for record in records]
    generation = [
        float(record.get("generation_time_seconds", 0.0))
        for record in records
        if record.get("record_type") == "round"
    ]
    return "\n".join(
        [
            "Audit Package Statistics",
            "",
            f"Number of records: {len(records)}",
            f"Round records: {sum(1 for r in records if r.get('record_type') == 'round')}",
            f"Package valid: {'YES' if verification.valid else 'NO'}",
            f"Verification result: {verification.status}",
            f"Average record size: {(sum(sizes) / len(sizes)) if sizes else 0.0:.2f} bytes",
            f"Average hash length: {(sum(len(h) for h in hashes) / len(hashes)) if hashes else 0.0:.2f} characters",
            f"Total audit generation time: {sum(generation):.6f} seconds",
            f"Broken record: {verification.broken_record if verification.broken_record is not None else 'None'}",
            "",
        ]
    )
