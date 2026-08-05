"""Masking utilities for networked Secure DFL payloads.

The module supports two modes:

* ``masking``: controlled additive masking simulation. The sender transmits the
  mask in the signed envelope so the receiver can reconstruct the original
  state before normal aggregation.
* ``pairwise_masking``: target-specific pairwise masks. Contributors to the
  same target aggregate derive deterministic pair masks; the masks cancel only
  when the target aggregates the complete contributor set.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Mapping

import numpy as np

from .codec import State, encode_state
from .crypto import canonical_json_bytes


PAIRWISE_SEED_BYTES = 32


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


def pairwise_mask_seed(
    *,
    experiment_id: str,
    round_number: int,
    target_id: str,
    left_id: str,
    right_id: str,
) -> int:
    """Derive a deterministic seed for one target-specific contributor pair."""

    import hashlib

    low, high = sorted([left_id, right_id])
    material = canonical_json_bytes(
        {
            "mode": "pairwise_masking",
            "experiment_id": experiment_id,
            "round_number": round_number,
            "target_id": target_id,
            "left_id": low,
            "right_id": high,
        }
    )
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def generate_pairwise_canceling_mask(
    state: State,
    *,
    experiment_id: str,
    round_number: int,
    target_id: str,
    contributor_id: str,
    contributor_ids: list[str],
    scale: float = 1e-3,
) -> OrderedDict[str, np.ndarray]:
    """Return this contributor's target-specific mask contribution.

    For each pair of contributors, the lexicographically lower id adds the pair
    mask and the higher id subtracts it. Summed over the same contributor set,
    all pair masks cancel to approximately zero.
    """

    normalized = sorted(set(contributor_ids))
    if contributor_id not in normalized:
        raise ValueError("contributor_id must be part of contributor_ids")
    if target_id not in normalized:
        raise ValueError("target_id must be part of contributor_ids")

    total = OrderedDict(
        (name, np.zeros_like(np.asarray(value))) for name, value in state.items()
    )
    for other_id in normalized:
        if other_id == contributor_id:
            continue
        seed = pairwise_mask_seed(
            experiment_id=experiment_id,
            round_number=round_number,
            target_id=target_id,
            left_id=contributor_id,
            right_id=other_id,
        )
        pair_mask = generate_mask_for_state(state, seed=seed, scale=scale)
        sign = 1.0 if contributor_id < other_id else -1.0
        for name in total:
            total[name] = total[name] + (np.asarray(pair_mask[name]) * sign).astype(
                total[name].dtype,
                copy=False,
            )
    return total


def apply_pairwise_canceling_mask(
    state: State,
    *,
    experiment_id: str,
    round_number: int,
    target_id: str,
    contributor_id: str,
    contributor_ids: list[str],
    scale: float = 1e-3,
) -> OrderedDict[str, np.ndarray]:
    """Apply the contributor's pairwise canceling mask to a model state."""

    mask = generate_pairwise_canceling_mask(
        state,
        experiment_id=experiment_id,
        round_number=round_number,
        target_id=target_id,
        contributor_id=contributor_id,
        contributor_ids=contributor_ids,
        scale=scale,
    )
    return apply_mask(state, mask)


def estimate_pairwise_seed_overhead_bytes(contributor_ids: list[str]) -> int:
    """Estimate deterministic seed material needed by one contributor."""

    return max(0, len(set(contributor_ids)) - 1) * PAIRWISE_SEED_BYTES


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
