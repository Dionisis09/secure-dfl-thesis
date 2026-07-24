"""Adapters between PyTorch model states and the network transport format.

The platform node runtime deliberately transports NumPy arrays instead of
framework-specific objects. This module keeps that boundary explicit: training
code can stay in PyTorch, while the node process only sees safe NPZ payloads.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Mapping

import numpy as np
import torch

from .codec import decode_state, encode_state


def torch_state_to_numpy(
    state_dict: Mapping[str, torch.Tensor],
) -> OrderedDict[str, np.ndarray]:
    """Convert a PyTorch state dict into detached CPU NumPy arrays."""

    if not state_dict:
        raise ValueError("state_dict cannot be empty")
    output: OrderedDict[str, np.ndarray] = OrderedDict()
    for name, tensor in state_dict.items():
        if not isinstance(tensor, torch.Tensor):
            raise TypeError(f"state entry {name!r} is not a torch.Tensor")
        output[name] = np.ascontiguousarray(tensor.detach().cpu().numpy())
    return output


def numpy_state_to_torch(
    numpy_state: Mapping[str, np.ndarray],
    reference_state_dict: Mapping[str, torch.Tensor],
    *,
    device: torch.device | str | None = None,
) -> OrderedDict[str, torch.Tensor]:
    """Convert NumPy arrays back to tensors matching a reference model state."""

    if set(numpy_state) != set(reference_state_dict):
        missing = sorted(set(reference_state_dict) - set(numpy_state))
        extra = sorted(set(numpy_state) - set(reference_state_dict))
        raise ValueError(f"state keys do not match; missing={missing}, extra={extra}")

    output: OrderedDict[str, torch.Tensor] = OrderedDict()
    for name, reference in reference_state_dict.items():
        array = np.asarray(numpy_state[name])
        if tuple(array.shape) != tuple(reference.shape):
            raise ValueError(
                f"shape mismatch for {name}: got {array.shape}, expected {tuple(reference.shape)}"
            )
        tensor = torch.from_numpy(np.array(array, copy=True)).to(
            device=device or reference.device,
            dtype=reference.dtype,
        )
        output[name] = tensor
    return output


def model_to_payload(model: torch.nn.Module) -> bytes:
    """Serialize a PyTorch model state into the node transport payload."""

    return encode_state(torch_state_to_numpy(model.state_dict()))


def payload_to_model_state(
    payload: bytes,
    model: torch.nn.Module,
    *,
    max_payload_bytes: int,
    device: torch.device | str | None = None,
) -> OrderedDict[str, torch.Tensor]:
    """Decode an aggregate payload into a state dict suitable for load_state_dict."""

    numpy_state = decode_state(payload, max_payload_bytes)
    return numpy_state_to_torch(
        numpy_state,
        model.state_dict(),
        device=device,
    )
