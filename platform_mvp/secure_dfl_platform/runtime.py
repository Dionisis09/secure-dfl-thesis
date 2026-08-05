"""Thread-safe node state and decentralized neighborhood aggregation."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .codec import average_states, decode_state, encode_state, hash_payload
from .crypto import canonical_json_bytes, public_key_b64, public_key_id, sign_b64
from .masking import apply_pairwise_canceling_mask
from .protocol import UpdateEnvelope, verify_envelope


@dataclass
class RoundState:
    round_number: int
    local_state: OrderedDict[str, np.ndarray] | None = None
    local_payload_hash: str | None = None
    peer_states: dict[str, OrderedDict[str, np.ndarray]] = field(default_factory=dict)
    peer_payload_hashes: dict[str, str] = field(default_factory=dict)
    peer_security_modes: dict[str, str] = field(default_factory=dict)
    peer_contributor_sets: dict[str, tuple[str, ...]] = field(default_factory=dict)
    aggregate_state: OrderedDict[str, np.ndarray] | None = None
    aggregate_payload_hash: str | None = None
    finalized_at_unix: float | None = None


class NodeRuntime:
    def __init__(
        self,
        *,
        node_id: str,
        experiment_id: str,
        peer_ids: list[str],
        private_key: Ed25519PrivateKey,
        trusted_keys: Mapping[str, Ed25519PublicKey],
        data_dir: Path,
        max_payload_bytes: int,
        min_peer_updates_to_finalize: int | None = None,
        security_mode: str = "none",
    ) -> None:
        self.node_id = node_id
        self.experiment_id = experiment_id
        self.peer_ids = sorted(peer_ids)
        self.private_key = private_key
        self.trusted_keys = dict(trusted_keys)
        self.data_dir = data_dir
        self.max_payload_bytes = max_payload_bytes
        self.security_mode = security_mode
        self.min_peer_updates_to_finalize = (
            len(self.peer_ids)
            if min_peer_updates_to_finalize is None
            else min_peer_updates_to_finalize
        )
        if not 0 <= self.min_peer_updates_to_finalize <= len(self.peer_ids):
            raise ValueError(
                "min_peer_updates_to_finalize must be between 0 and the number of peers"
            )
        self.started_at_unix = time.time()
        self._rounds: dict[int, RoundState] = {}
        self._seen_message_ids: set[str] = set()
        self._lock = threading.RLock()
        self._metrics = {
            "received_updates_total": 0,
            "rejected_updates_total": 0,
            "sent_updates_total": 0,
            "send_failures_total": 0,
            "finalized_rounds_total": 0,
            "partial_finalizations_total": 0,
            "received_bytes_total": 0,
            "sent_bytes_total": 0,
            "masked_updates_received_total": 0,
            "masked_updates_sent_total": 0,
            "received_masking_overhead_bytes_total": 0,
            "sent_masking_overhead_bytes_total": 0,
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.data_dir / "node_audit.jsonl"
        self._audit_previous_hash = self._recover_last_audit_hash()
        self._append_audit(
            "node_started",
            {
                "node_id": node_id,
                "experiment_id": experiment_id,
                "peer_ids": self.peer_ids,
                "min_peer_updates_to_finalize": self.min_peer_updates_to_finalize,
                "security_mode": self.security_mode,
                "public_key": public_key_b64(private_key.public_key()),
                "public_key_id": public_key_id(private_key.public_key()),
            },
        )

    def _recover_last_audit_hash(self) -> str:
        if not self.audit_path.exists():
            return "GENESIS"
        lines = [line for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return "GENESIS"
        return str(json.loads(lines[-1])["record_hash"])

    def _append_audit(self, event_type: str, details: Mapping[str, Any]) -> None:
        record = {
            "schema_version": "1.0",
            "event_type": event_type,
            "timestamp_unix": time.time(),
            "node_id": self.node_id,
            "experiment_id": self.experiment_id,
            "previous_hash": self._audit_previous_hash,
            "details": details,
        }
        record_hash = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
        signed_record = {
            **record,
            "record_hash": record_hash,
            "public_key_id": public_key_id(self.private_key.public_key()),
            "signature_b64": sign_b64(self.private_key, record_hash.encode("ascii")),
        }
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(signed_record, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        self._audit_previous_hash = record_hash

    def _round(self, round_number: int) -> RoundState:
        if round_number <= 0:
            raise ValueError("round number must be positive")
        return self._rounds.setdefault(round_number, RoundState(round_number))

    def register_local_payload(self, round_number: int, payload: bytes) -> str:
        state = decode_state(payload, self.max_payload_bytes)
        digest = hash_payload(payload)
        with self._lock:
            item = self._round(round_number)
            if item.local_payload_hash and item.local_payload_hash != digest:
                raise ValueError("conflicting local state already registered")
            item.local_state = state
            item.local_payload_hash = digest
            self._append_audit(
                "local_state_registered",
                {"round_number": round_number, "payload_hash": digest, "bytes": len(payload)},
            )
        return digest

    def accept_peer_envelope(self, envelope: UpdateEnvelope) -> dict[str, Any]:
        trusted_key = self.trusted_keys.get(envelope.sender_id)
        if trusted_key is None or envelope.sender_id not in self.peer_ids:
            self.increment_metric("rejected_updates_total")
            raise ValueError("sender is not a trusted configured peer")
        try:
            payload = verify_envelope(
                envelope,
                trusted_key=trusted_key,
                expected_experiment_id=self.experiment_id,
                expected_recipient_id=self.node_id,
                max_payload_bytes=self.max_payload_bytes,
            )
            state = decode_state(payload, self.max_payload_bytes)
            with self._lock:
                item = self._round(envelope.round_number)
                if envelope.message_id in self._seen_message_ids:
                    return {"accepted": True, "duplicate": True, "message_id": envelope.message_id}
                original_payload_hash = envelope.original_payload_hash or envelope.payload_hash
                previous_hash = item.peer_payload_hashes.get(envelope.sender_id)
                if previous_hash and previous_hash != original_payload_hash:
                    raise ValueError("conflicting update from peer for the same round")
                item.peer_states[envelope.sender_id] = state
                item.peer_payload_hashes[envelope.sender_id] = original_payload_hash
                item.peer_security_modes[envelope.sender_id] = envelope.security_mode
                item.peer_contributor_sets[envelope.sender_id] = tuple(
                    sorted(envelope.mask_contributor_ids)
                )
                self._seen_message_ids.add(envelope.message_id)
                self._metrics["received_updates_total"] += 1
                self._metrics["received_bytes_total"] += len(payload)
                if envelope.security_mode in {"masking", "pairwise_masking"}:
                    self._metrics["masked_updates_received_total"] += 1
                    self._metrics["received_masking_overhead_bytes_total"] += (
                        envelope.masking_overhead_bytes
                    )
                self._append_audit(
                    "peer_update_accepted",
                    {
                        "round_number": envelope.round_number,
                        "sender_id": envelope.sender_id,
                        "message_id": envelope.message_id,
                        "payload_hash": envelope.original_payload_hash,
                        "transmitted_payload_hash": envelope.payload_hash,
                        "security_mode": envelope.security_mode,
                        "masking_overhead_bytes": envelope.masking_overhead_bytes,
                        "mask_contributor_ids": list(envelope.mask_contributor_ids),
                        "bytes": len(payload),
                    },
                )
            return {"accepted": True, "duplicate": False, "message_id": envelope.message_id}
        except Exception:
            self.increment_metric("rejected_updates_total")
            raise

    def is_ready(self, round_number: int) -> bool:
        with self._lock:
            item = self._round(round_number)
            return (
                item.local_state is not None
                and len(item.peer_states) >= self.min_peer_updates_to_finalize
            )

    def finalize_round(self, round_number: int) -> tuple[bytes, dict[str, Any]]:
        with self._lock:
            item = self._round(round_number)
            if item.aggregate_state is not None:
                payload = encode_state(item.aggregate_state)
                return payload, self.round_status(round_number)
            missing = sorted(set(self.peer_ids) - set(item.peer_states))
            received_peer_count = len(item.peer_states)
            if (
                item.local_state is None
                or received_peer_count < self.min_peer_updates_to_finalize
            ):
                raise RuntimeError(
                    "round is not ready; "
                    f"local={item.local_state is not None}, "
                    f"received_peer_updates={received_peer_count}, "
                    f"required_peer_updates={self.min_peer_updates_to_finalize}, "
                    f"missing_peers={missing}"
                )
            contributing_peers = sorted(item.peer_states)
            contributors = [self.node_id, *contributing_peers]
            if self.security_mode == "pairwise_masking":
                if missing:
                    raise RuntimeError(
                        "pairwise_masking requires the complete configured contributor set; "
                        f"missing_peers={missing}"
                    )
                expected_contributors = tuple(sorted(contributors))
                for peer_id in contributing_peers:
                    if item.peer_security_modes.get(peer_id) != "pairwise_masking":
                        raise ValueError(f"peer {peer_id} did not use pairwise_masking")
                    if item.peer_contributor_sets.get(peer_id) != expected_contributors:
                        raise ValueError(
                            f"peer {peer_id} used incompatible pairwise contributor set"
                        )
                local_state = apply_pairwise_canceling_mask(
                    item.local_state,
                    experiment_id=self.experiment_id,
                    round_number=round_number,
                    target_id=self.node_id,
                    contributor_id=self.node_id,
                    contributor_ids=list(expected_contributors),
                )
            else:
                local_state = item.local_state
            ordered_states = [local_state] + [item.peer_states[p] for p in contributing_peers]
            aggregate = average_states(ordered_states)
            aggregate_payload = encode_state(aggregate)
            item.aggregate_state = aggregate
            item.aggregate_payload_hash = hash_payload(aggregate_payload)
            item.finalized_at_unix = time.time()
            self._metrics["finalized_rounds_total"] += 1
            if missing:
                self._metrics["partial_finalizations_total"] += 1
            self._append_audit(
                "round_finalized",
                {
                    "round_number": round_number,
                    "contributors": contributors,
                    "missing_peers": missing,
                    "required_peer_updates": self.min_peer_updates_to_finalize,
                    "partial_finalization": bool(missing),
                    "aggregate_payload_hash": item.aggregate_payload_hash,
                    "aggregate_bytes": len(aggregate_payload),
                },
            )
            return aggregate_payload, self.round_status(round_number)

    def round_status(self, round_number: int) -> dict[str, Any]:
        with self._lock:
            item = self._round(round_number)
            missing = sorted(set(self.peer_ids) - set(item.peer_states))
            received_peer_count = len(item.peer_states)
            ready = (
                item.local_state is not None
                and received_peer_count >= self.min_peer_updates_to_finalize
            )
            return {
                "round_number": round_number,
                "local_state_registered": item.local_state is not None,
                "received_peers": sorted(item.peer_states),
                "expected_peers": self.peer_ids,
                "missing_peers": missing,
                "received_peer_count": received_peer_count,
                "required_peer_updates": self.min_peer_updates_to_finalize,
                "ready": ready,
                "partial_ready": ready and bool(missing),
                "finalized": item.aggregate_state is not None,
                "aggregate_payload_hash": item.aggregate_payload_hash,
                "finalized_at_unix": item.finalized_at_unix,
            }

    def node_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok",
                "node_id": self.node_id,
                "experiment_id": self.experiment_id,
                "peer_ids": self.peer_ids,
                "min_peer_updates_to_finalize": self.min_peer_updates_to_finalize,
                "security_mode": self.security_mode,
                "public_key_id": public_key_id(self.private_key.public_key()),
                "uptime_seconds": time.time() - self.started_at_unix,
                "rounds": {str(number): self.round_status(number) for number in sorted(self._rounds)},
                "metrics": dict(self._metrics),
            }

    def increment_metric(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._metrics[name] += amount

    def metrics_text(self) -> str:
        with self._lock:
            lines = []
            for name, value in sorted(self._metrics.items()):
                lines.append(f"secure_dfl_{name}{{node_id=\"{self.node_id}\"}} {value}")
            lines.append(
                f"secure_dfl_uptime_seconds{{node_id=\"{self.node_id}\"}} {time.time() - self.started_at_unix:.3f}"
            )
            return "\n".join(lines) + "\n"
