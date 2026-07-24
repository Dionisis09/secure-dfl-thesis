"""Block representation for the optional DFL audit ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .hashing import sha256_json


@dataclass
class Block:
    block_index: int
    timestamp: str
    experiment_name: str
    round_number: int
    previous_hash: str
    current_hash: str
    security_mode: str
    split_type: str
    topology: str
    num_clients: int
    batch_size: int
    num_rounds: int
    adaptive_policy: str
    adaptive_he_target_ratio: float
    adaptive_selected_targets: Any
    adaptive_risk_scores: Any
    train_loss: float
    test_loss: float
    test_accuracy: float
    communication_bytes: int
    masking_time_seconds: float
    he_total_time_seconds: float
    he_encryption_time_seconds: float
    he_decryption_time_seconds: float
    he_ciphertext_bytes: int
    pairwise_cancellation_error: float
    model_hashes: Dict[str, str]
    client_signatures: Dict[str, Dict[str, str]]
    configuration_hash: str
    block_generation_time_seconds: float
    nonce: int
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "timestamp": self.timestamp,
            "experiment_name": self.experiment_name,
            "round_number": self.round_number,
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "security_mode": self.security_mode,
            "split_type": self.split_type,
            "topology": self.topology,
            "num_clients": self.num_clients,
            "batch_size": self.batch_size,
            "num_rounds": self.num_rounds,
            "adaptive_policy": self.adaptive_policy,
            "adaptive_he_target_ratio": self.adaptive_he_target_ratio,
            "adaptive_selected_targets": self.adaptive_selected_targets,
            "adaptive_risk_scores": self.adaptive_risk_scores,
            "train_loss": self.train_loss,
            "test_loss": self.test_loss,
            "test_accuracy": self.test_accuracy,
            "communication_bytes": self.communication_bytes,
            "masking_time_seconds": self.masking_time_seconds,
            "he_total_time_seconds": self.he_total_time_seconds,
            "he_encryption_time_seconds": self.he_encryption_time_seconds,
            "he_decryption_time_seconds": self.he_decryption_time_seconds,
            "he_ciphertext_bytes": self.he_ciphertext_bytes,
            "pairwise_cancellation_error": self.pairwise_cancellation_error,
            "model_hashes": self.model_hashes,
            "client_signatures": self.client_signatures,
            "configuration_hash": self.configuration_hash,
            "block_generation_time_seconds": self.block_generation_time_seconds,
            "nonce": self.nonce,
            "extra_metadata": self.extra_metadata,
        }


def compute_block_hash(block_data: Dict[str, Any]) -> str:
    """Hash all block fields except current_hash."""

    content = dict(block_data)
    content.pop("current_hash", None)
    return sha256_json(content)


def finalized_block(block_data: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(block_data)
    output["current_hash"] = compute_block_hash(output)
    return output
