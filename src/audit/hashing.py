"""Stable hashing utilities for the federated learning audit package."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import torch


def stable_json(data: Any) -> str:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(data: Any) -> str:
    return sha256_text(stable_json(data))


def hash_state_dict(state_dict: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state_dict.keys()):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(tensor.shape)).encode("utf-8"))
        digest.update(str(tensor.dtype).encode("utf-8"))
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def hash_client_states(client_states: Mapping[int, Mapping[str, torch.Tensor]]) -> dict:
    return {
        f"client_{client_id}": hash_state_dict(state)
        for client_id, state in sorted(client_states.items())
    }


def compute_record_hash(record: Mapping[str, Any]) -> str:
    payload = dict(record)
    payload.pop("record_hash", None)
    return sha256_json(payload)
