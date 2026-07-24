"""Simple additive masking utilities for networked Secure DFL payloads.

This module implements a controlled masking simulation for the platform layer.
The sender transmits masked tensors plus the corresponding mask inside the
signed envelope so the receiver can reconstruct the model state before
aggregation. This is useful for measuring protocol overhead and demonstrating a
protected-sharing workflow, but it is not yet cryptographic secure aggregation.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Mapping

import numpy as np

from .codec import State, encode_state


def generate_mask_for_state(
    state: State,
    seed: int | None = None,
    scale: float = 1e-3,
) -> OrderedDict[str, np.ndarray]:
    """Generate additive masks with the same shapes as floating tensors."""

    rng = np.random.default_rng(seed)
    mask: OrderedDict[str, np.ndarray] = OrderedDict()
    for name, value in state.items():
        array = np.asarray(value)
        if np.issubdtype(array.dtype, np.floating):
            mask[name] = rng.normal(0.0, scale, size=array.shape).astype(array.dtype)
        else:
            mask[name] = np.zeros_like(array)
    return mask


def apply_mask(state: State, mask: State) -> OrderedDict[str, np.ndarray]:
    """Return state + mask for matching tensor names, shapes and dtypes."""

    _validate_compatible(state, mask)
    return OrderedDict(
        (name, np.asarray(state[name]) + np.asarray(mask[name]))
        for name in state
    )


def remove_mask(masked_state: State, mask: State) -> OrderedDict[str, np.ndarray]:
    """Return masked_state - mask for matching tensor names, shapes and dtypes."""

    _validate_compatible(masked_state, mask)
    return OrderedDict(
        (name, np.asarray(masked_state[name]) - np.asarray(mask[name]))
        for name in masked_state
    )


def estimate_masking_overhead_bytes(mask: State) -> int:
    """Estimate transport overhead introduced by carrying mask tensors."""

    return len(encode_state(mask))


def _validate_compatible(left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray]) -> None:
    if list(left.keys()) != list(right.keys()):
        raise ValueError("state and mask keys do not match")
    for name in left:
        left_array = np.asarray(left[name])
        right_array = np.asarray(right[name])
        if left_array.shape != right_array.shape:
            raise ValueError(f"mask shape mismatch for {name}")
        if left_array.dtype != right_array.dtype:
            raise ValueError(f"mask dtype mismatch for {name}")
