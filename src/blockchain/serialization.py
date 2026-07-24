"""Serialization helpers for blockchain audit artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .hashing import stable_json_dumps


def save_chain_json(chain_data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(chain_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_chain_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_summary_csv(
    blocks: Iterable[Dict[str, Any]], path: Path, verification_status: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "block",
        "round",
        "timestamp",
        "experiment_name",
        "security_mode",
        "num_clients",
        "topology",
        "split_type",
        "adaptive_policy",
        "accuracy",
        "loss",
        "communication",
        "hash",
        "previous_hash",
        "model_hashes",
        "client_signatures",
        "block_generation_time_seconds",
        "verification_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for block in blocks:
            writer.writerow(
                {
                    "block": block.get("block_index", ""),
                    "round": block.get("round_number", ""),
                    "timestamp": block.get("timestamp", ""),
                    "experiment_name": block.get("experiment_name", ""),
                    "security_mode": block.get("security_mode", ""),
                    "num_clients": block.get("num_clients", ""),
                    "topology": block.get("topology", ""),
                    "split_type": block.get("split_type", ""),
                    "adaptive_policy": block.get("adaptive_policy", ""),
                    "accuracy": block.get("test_accuracy", ""),
                    "loss": block.get("test_loss", ""),
                    "communication": block.get("communication_bytes", ""),
                    "hash": block.get("current_hash", ""),
                    "previous_hash": block.get("previous_hash", ""),
                    "model_hashes": stable_json_dumps(block.get("model_hashes", {})),
                    "client_signatures": stable_json_dumps(
                        block.get("client_signatures", {})
                    ),
                    "block_generation_time_seconds": block.get(
                        "block_generation_time_seconds", ""
                    ),
                    "verification_status": verification_status,
                }
            )


def canonical_config_hash(configuration: Dict[str, Any]) -> str:
    from .hashing import sha256_text

    return sha256_text(stable_json_dumps(configuration))


def blocks_from_chain_data(chain_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(chain_data.get("blocks", []))
