"""Verification utilities for blockchain audit ledgers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .block import compute_block_hash
from .serialization import canonical_config_hash, load_chain_json
from .signatures import verify_round_signatures


@dataclass
class VerificationResult:
    status: str
    broken_block: Optional[int] = None
    reason: str = ""

    @property
    def valid(self) -> bool:
        return self.status == "VALID"


def verify_chain_data(chain_data: Dict[str, Any]) -> VerificationResult:
    blocks = chain_data.get("blocks", [])
    if not blocks:
        return VerificationResult("INVALID_HASH_CHAIN", None, "chain has no blocks")

    configuration = chain_data.get("configuration", {})
    expected_config_hash = chain_data.get("configuration_hash", "")
    actual_config_hash = canonical_config_hash(configuration)
    if expected_config_hash != actual_config_hash:
        return VerificationResult(
            "INVALID_HASH_CHAIN", None, "top-level configuration hash mismatch"
        )

    public_keys = chain_data.get("client_public_keys", {})
    signatures_required = bool(public_keys)

    for position, block in enumerate(blocks):
        block_index = block.get("block_index", position)
        if block.get("configuration_hash") != expected_config_hash:
            return VerificationResult(
                "INVALID_HASH_CHAIN", block_index, "block configuration hash mismatch"
            )

        expected_hash = compute_block_hash(block)
        if block.get("current_hash") != expected_hash:
            return VerificationResult(
                "INVALID_HASH_CHAIN", block_index, "block current_hash mismatch"
            )

        if position == 0:
            if block.get("previous_hash") != "GENESIS":
                return VerificationResult(
                    "INVALID_HASH_CHAIN",
                    block_index,
                    "genesis previous_hash is not GENESIS",
                )
            continue

        previous_block = blocks[position - 1]
        if block.get("previous_hash") != previous_block.get("current_hash"):
            return VerificationResult(
                "INVALID_HASH_CHAIN",
                block_index,
                "previous_hash does not match prior block",
            )

        if signatures_required and not verify_round_signatures(
            round_number=int(block.get("round_number", 0)),
            model_hashes=block.get("model_hashes", {}),
            signatures=block.get("client_signatures", {}),
            public_keys=public_keys,
        ):
            return VerificationResult(
                "INVALID_SIGNATURE",
                block_index,
                "client signature verification failed",
            )

    return VerificationResult("VALID")


def verify_chain(path: str | Path) -> VerificationResult:
    return verify_chain_data(load_chain_json(Path(path)))


def build_verification_report(
    chain_data: Dict[str, Any],
    result: VerificationResult,
    in_memory_result: Optional[VerificationResult] = None,
    exported_result: Optional[VerificationResult] = None,
) -> str:
    blocks = chain_data.get("blocks", [])
    experiment = chain_data.get("experiment_name", "")
    genesis_ok = bool(blocks and blocks[0].get("previous_hash") == "GENESIS")
    continuity_ok = result.status != "INVALID_HASH_CHAIN"
    signature_ok = result.status != "INVALID_SIGNATURE"
    tampering = "NOT DETECTED" if result.valid else "DETECTED"

    lines = [
        "Blockchain Verification Report",
        "",
        f"Experiment: {experiment}",
        "",
        f"Blocks: {len(blocks)}",
        "",
        f"Status: {result.status}",
        "",
        f"In-memory verification: {(in_memory_result or result).status}",
        "",
        f"Reloaded export verification: {(exported_result or result).status}",
        "",
        f"Genesis: {'OK' if genesis_ok else 'FAILED'}",
        "",
        f"Hash continuity: {'OK' if continuity_ok else 'FAILED'}",
        "",
        f"Signatures: {'OK' if signature_ok else 'FAILED'}",
        "",
        f"Tampering: {tampering}",
    ]
    if not result.valid:
        lines.extend(
            [
                "",
                f"Broken block: {result.broken_block}",
                "",
                f"Reason: {result.reason}",
            ]
        )
    return "\n".join(lines) + "\n"
