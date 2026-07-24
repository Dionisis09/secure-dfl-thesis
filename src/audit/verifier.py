"""Verification for product-style federated learning audit packages."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .hashing import compute_record_hash, stable_json
from .merkle import merkle_root, verify_merkle_proof
from .schema import configuration_hash
from .signing import key_manifest_hash, signing_payload, verify_signature


@dataclass
class AuditVerificationResult:
    status: str
    valid: bool
    broken_record: Optional[int] = None
    reason: str = ""
    checked_records: int = 0
    checked_signatures: int = 0
    checked_merkle_proofs: int = 0
    errors: List[str] = field(default_factory=list)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_public_keys(path: Path) -> Dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_records(
    records: List[Dict[str, Any]], public_keys: Dict[str, dict]
) -> AuditVerificationResult:
    if not records:
        return AuditVerificationResult(
            status="INVALID_EMPTY_LEDGER",
            valid=False,
            reason="ledger contains no records",
        )

    previous_hash = "GENESIS"
    start_record = records[0]
    expected_config_hash = start_record.get("configuration_hash", "")
    expected_public_keys_hash = start_record.get("public_keys_hash", "")
    actual_public_keys_hash = key_manifest_hash(public_keys)
    checked_signatures = 0
    checked_merkle = 0

    if start_record.get("record_type") != "experiment_start":
        return AuditVerificationResult(
            status="INVALID_SCHEMA",
            valid=False,
            broken_record=0,
            reason="first record is not experiment_start",
        )
    if configuration_hash(start_record.get("configuration", {})) != expected_config_hash:
        return AuditVerificationResult(
            status="INVALID_CONFIGURATION_HASH",
            valid=False,
            broken_record=0,
            reason="configuration hash mismatch",
        )
    if actual_public_keys_hash != expected_public_keys_hash:
        return AuditVerificationResult(
            status="INVALID_PUBLIC_KEYS",
            valid=False,
            broken_record=0,
            reason="public key manifest hash mismatch",
        )

    for index, record in enumerate(records):
        record_index = int(record.get("record_index", index))
        if record.get("previous_hash") != previous_hash:
            return AuditVerificationResult(
                status="INVALID_HASH_CHAIN",
                valid=False,
                broken_record=record_index,
                reason="previous_hash does not match prior record hash",
                checked_records=index,
                checked_signatures=checked_signatures,
                checked_merkle_proofs=checked_merkle,
            )
        expected_hash = compute_record_hash(record)
        if record.get("record_hash") != expected_hash:
            return AuditVerificationResult(
                status="INVALID_HASH_CHAIN",
                valid=False,
                broken_record=record_index,
                reason="record_hash mismatch",
                checked_records=index,
                checked_signatures=checked_signatures,
                checked_merkle_proofs=checked_merkle,
            )
        if record.get("configuration_hash") != expected_config_hash:
            return AuditVerificationResult(
                status="INVALID_CONFIGURATION_HASH",
                valid=False,
                broken_record=record_index,
                reason="record configuration hash mismatch",
                checked_records=index,
                checked_signatures=checked_signatures,
                checked_merkle_proofs=checked_merkle,
            )
        if record.get("public_keys_hash") != expected_public_keys_hash:
            return AuditVerificationResult(
                status="INVALID_PUBLIC_KEYS",
                valid=False,
                broken_record=record_index,
                reason="record public keys hash mismatch",
                checked_records=index,
                checked_signatures=checked_signatures,
                checked_merkle_proofs=checked_merkle,
            )

        if record.get("record_type") == "round":
            client_hashes = record.get("client_model_hashes", {})
            root = record.get("merkle_root", "")
            if merkle_root(client_hashes) != root:
                return AuditVerificationResult(
                    status="INVALID_MERKLE_ROOT",
                    valid=False,
                    broken_record=record_index,
                    reason="merkle root mismatch",
                    checked_records=index,
                    checked_signatures=checked_signatures,
                    checked_merkle_proofs=checked_merkle,
                )

            for client_key, model_hash in sorted(client_hashes.items()):
                proof = record.get("merkle_proofs", {}).get(client_key, [])
                if not verify_merkle_proof(client_key, model_hash, proof, root):
                    return AuditVerificationResult(
                        status="INVALID_MERKLE_PROOF",
                        valid=False,
                        broken_record=record_index,
                        reason=f"invalid merkle proof for {client_key}",
                        checked_records=index,
                        checked_signatures=checked_signatures,
                        checked_merkle_proofs=checked_merkle,
                    )
                checked_merkle += 1

                signature = record.get("client_signatures", {}).get(client_key, {})
                public_key_info = public_keys.get(client_key, {})
                client_id = int(client_key.replace("client_", ""))
                payload = signing_payload(
                    experiment_name=record["experiment_name"],
                    client_id=client_id,
                    round_number=int(record["round_number"]),
                    model_hash=model_hash,
                    security_mode=record["security_mode"],
                    merkle_root=root,
                )
                if signature.get("public_key_id") != public_key_info.get("public_key_id"):
                    return AuditVerificationResult(
                        status="INVALID_SIGNATURE",
                        valid=False,
                        broken_record=record_index,
                        reason=f"public key id mismatch for {client_key}",
                        checked_records=index,
                        checked_signatures=checked_signatures,
                        checked_merkle_proofs=checked_merkle,
                    )
                if not verify_signature(
                    public_key_b64=public_key_info.get("public_key", ""),
                    payload=payload,
                    signature_b64=signature.get("signature", ""),
                ):
                    return AuditVerificationResult(
                        status="INVALID_SIGNATURE",
                        valid=False,
                        broken_record=record_index,
                        reason=f"signature verification failed for {client_key}",
                        checked_records=index,
                        checked_signatures=checked_signatures,
                        checked_merkle_proofs=checked_merkle,
                    )
                checked_signatures += 1

        previous_hash = record["record_hash"]

    return AuditVerificationResult(
        status="VALID",
        valid=True,
        checked_records=len(records),
        checked_signatures=checked_signatures,
        checked_merkle_proofs=checked_merkle,
    )


def verify_ledger_file(ledger_path: str | Path, public_keys_path: str | Path):
    return verify_records(
        records=load_jsonl(Path(ledger_path)),
        public_keys=load_public_keys(Path(public_keys_path)),
    )


def verify_audit_package(package_dir: str | Path):
    package = Path(package_dir)
    return verify_ledger_file(package / "ledger.jsonl", package / "public_keys.json")
