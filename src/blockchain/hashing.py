"""Hashing helpers for the optional blockchain audit layer."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

import torch


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object is not JSON serializable: {type(value).__name__}")


def stable_json_dumps(data: Any) -> str:
    """Serialize data deterministically before hashing or saving."""

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(data: Any) -> str:
    return sha256_text(stable_json_dumps(data))


def hash_state_dict(state_dict: Mapping[str, torch.Tensor]) -> str:
    """Create a deterministic SHA256 hash of model tensors.

    The raw tensor values are hashed together with parameter names, shapes and
    dtypes. No model parameters are stored in the blockchain itself.
    """

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
        f"client_{client_id}_hash": hash_state_dict(state_dict)
        for client_id, state_dict in sorted(client_states.items())
    }
