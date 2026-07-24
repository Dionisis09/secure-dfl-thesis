"""Fast self-check for the advanced audit layer.

This script does not run federated learning. It creates a tiny synthetic audit
package with two clients and verifies the cryptographic/integrity mechanisms:

- append-only hash chain
- Ed25519 signatures
- Merkle root and proofs
- tamper detection
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import torch

from audit import FederatedAuditLedger, verify_audit_package
from audit.hashing import compute_record_hash
from audit.verifier import load_jsonl, load_public_keys, verify_records


def synthetic_state(value: float):
    return OrderedDict(
        {
            "layer.weight": torch.tensor([[value, value + 1.0]], dtype=torch.float32),
            "layer.bias": torch.tensor([value], dtype=torch.float32),
        }
    )


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    output_root = project_root / "results" / "audit_self_check"
    experiment_name = "audit_self_check"
    config = {
        "experiment_name": experiment_name,
        "security_mode": "adaptive_hybrid",
        "seed": 123,
        "num_clients": 2,
        "num_rounds": 2,
        "batch_size": 8,
        "topology": "ring",
        "split_type": "iid",
        "adaptive_policy": "topk_risk",
        "adaptive_he_target_ratio": 0.5,
    }
    ledger = FederatedAuditLedger(
        experiment_name=experiment_name,
        configuration=config,
        output_root=output_root,
    )
    for round_number in (1, 2):
        metrics = {
            "avg_train_loss": 1.0 / round_number,
            "avg_test_loss": 0.8 / round_number,
            "avg_test_accuracy": 70.0 + round_number,
            "total_communication_bytes": 1024 * round_number,
            "masking_time_seconds": 0.001,
            "he_total_time_seconds": 0.002,
            "he_ciphertext_bytes": 256,
            "pairwise_masking_cancellation_error": 0.0,
        }
        client_states = {
            0: synthetic_state(float(round_number)),
            1: synthetic_state(float(round_number + 10)),
        }
        ledger.record_round(
            round_number=round_number,
            metrics=metrics,
            client_states=client_states,
            adaptive_risk_scores={0: 0.1 * round_number, 1: 0.2 * round_number},
            adaptive_selected_targets=[1],
        )
    artifacts = ledger.finalize()
    result = verify_audit_package(artifacts["package"])
    print(f"Verification status: {result.status}")
    print(f"Checked records: {result.checked_records}")
    print(f"Checked signatures: {result.checked_signatures}")
    print(f"Checked Merkle proofs: {result.checked_merkle_proofs}")

    records = load_jsonl(artifacts["ledger"])
    public_keys = load_public_keys(artifacts["public_keys"])

    tampered_hash_records = [dict(record) for record in records]
    tampered_hash_records[1] = dict(tampered_hash_records[1])
    tampered_hash_records[1]["metrics"] = dict(tampered_hash_records[1]["metrics"])
    tampered_hash_records[1]["metrics"]["avg_test_accuracy"] += 1.0
    tampered_hash = verify_records(tampered_hash_records, public_keys)
    print(f"Hash tamper status: {tampered_hash.status}")

    tampered_signature_records = [dict(record) for record in records]
    tampered_signature_records[1] = dict(tampered_signature_records[1])
    tampered_signature_records[1]["client_signatures"] = dict(
        tampered_signature_records[1]["client_signatures"]
    )
    tampered_signature_records[1]["client_signatures"]["client_0"] = dict(
        tampered_signature_records[1]["client_signatures"]["client_0"]
    )
    tampered_signature_records[1]["client_signatures"]["client_0"][
        "signature"
    ] = "tampered"
    tampered_signature_records[1]["record_hash"] = compute_record_hash(
        tampered_signature_records[1]
    )
    tampered_signature = verify_records(tampered_signature_records, public_keys)
    print(f"Signature tamper status: {tampered_signature.status}")

    if (
        result.status == "VALID"
        and tampered_hash.status == "INVALID_HASH_CHAIN"
        and tampered_signature.status == "INVALID_SIGNATURE"
    ):
        print("Audit self-check passed")
        return 0

    print("Audit self-check failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
