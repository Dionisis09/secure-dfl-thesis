"""Additive masking utilities for simulated protected model sharing."""

import hashlib
from collections import OrderedDict
from itertools import combinations
from typing import Dict, Mapping, Optional, Sequence, Union

import torch


StateDict = Mapping[str, torch.Tensor]
Device = Optional[Union[str, torch.device]]


def generate_mask_for_state_dict(
    state_dict: StateDict, seed: Optional[int] = None
) -> OrderedDict:
    """Create an independent random additive mask matching a model state."""

    generator = torch.Generator(device="cpu")
    if seed is None:
        generator.seed()
    else:
        generator.manual_seed(seed)

    mask = OrderedDict()
    for key, tensor in state_dict.items():
        if tensor.device.type != "cpu":
            raise ValueError("mask generation expects CPU model snapshots")
        if torch.is_floating_point(tensor) or torch.is_complex(tensor):
            mask[key] = torch.randn(
                tensor.shape,
                dtype=tensor.dtype,
                device=tensor.device,
                generator=generator,
            )
        else:
            # Integer state entries cannot be additively masked safely.
            mask[key] = torch.zeros_like(tensor)
    return mask


def _validate_matching_states(state_dict: StateDict, mask: StateDict) -> None:
    if list(state_dict.keys()) != list(mask.keys()):
        raise ValueError("state_dict and mask must have identical ordered keys")
    for key, tensor in state_dict.items():
        if tensor.shape != mask[key].shape:
            raise ValueError(f"mask shape does not match state tensor '{key}'")


def apply_mask(state_dict: StateDict, mask: StateDict) -> OrderedDict:
    """Return a masked copy without modifying the model state or mask."""

    _validate_matching_states(state_dict, mask)
    masked_state = OrderedDict()
    for key, tensor in state_dict.items():
        if torch.is_floating_point(tensor) or torch.is_complex(tensor):
            masked_state[key] = tensor.clone() + mask[key].to(
                device=tensor.device, dtype=tensor.dtype
            )
        else:
            masked_state[key] = tensor.clone()
    return masked_state


def remove_mask(masked_state_dict: StateDict, mask: StateDict) -> OrderedDict:
    """Remove an additive mask and return a reconstructed model state."""

    _validate_matching_states(masked_state_dict, mask)
    unmasked_state = OrderedDict()
    for key, tensor in masked_state_dict.items():
        if torch.is_floating_point(tensor) or torch.is_complex(tensor):
            unmasked_state[key] = tensor.clone() - mask[key].to(
                device=tensor.device, dtype=tensor.dtype
            )
        else:
            unmasked_state[key] = tensor.clone()
    return unmasked_state


def estimate_masking_overhead_bytes(mask: StateDict) -> int:
    """Return the serialized tensor payload size of one mask in bytes."""

    return sum(
        tensor.numel() * tensor.element_size()
        for tensor in mask.values()
        if torch.is_floating_point(tensor) or torch.is_complex(tensor)
    )


def generate_deterministic_mask_like_state_dict(
    reference_state_dict: StateDict,
    seed: int,
    device: Device = None,
) -> OrderedDict:
    """Generate a reproducible mask matching all floating-point state tensors."""

    if not reference_state_dict:
        raise ValueError("reference_state_dict cannot be empty")

    first_tensor = next(iter(reference_state_dict.values()))
    mask_device = torch.device(device) if device is not None else first_tensor.device
    generator = torch.Generator(device=mask_device).manual_seed(seed)

    mask = OrderedDict()
    for key, tensor in reference_state_dict.items():
        if torch.is_floating_point(tensor) or torch.is_complex(tensor):
            mask[key] = torch.randn(
                tensor.shape,
                dtype=tensor.dtype,
                device=mask_device,
                generator=generator,
            )
        else:
            mask[key] = torch.zeros(
                tensor.shape, dtype=tensor.dtype, device=mask_device
            )
    return mask


def get_pairwise_mask_seed(
    round_idx: int,
    target_client_id: int,
    client_a_id: int,
    client_b_id: int,
    base_seed: int,
) -> int:
    """Derive a stable PRG-style seed for one target-specific client pair."""

    client_a_id, client_b_id = sorted((client_a_id, client_b_id))
    if client_a_id == client_b_id:
        raise ValueError("a pairwise mask requires two different clients")

    seed_material = (
        f"{base_seed}:{round_idx}:{target_client_id}:"
        f"{client_a_id}:{client_b_id}"
    ).encode("utf-8")
    digest = hashlib.blake2b(
        seed_material, digest_size=8, person=b"DFL-pair-mask"
    ).digest()
    return int.from_bytes(digest, byteorder="big") & ((1 << 63) - 1)


def build_masked_contributions_for_target(
    target_client_id: int,
    contributor_ids: Sequence[int],
    previous_states: Mapping[int, StateDict],
    round_idx: int,
    base_seed: int,
    device: Device = None,
) -> Dict[int, OrderedDict]:
    """Build target-specific contributions whose pairwise masks cancel in sum."""

    if not contributor_ids:
        raise ValueError("at least one contributor is required")
    if len(set(contributor_ids)) != len(contributor_ids):
        raise ValueError("contributor_ids must be unique")
    missing_ids = [client_id for client_id in contributor_ids if client_id not in previous_states]
    if missing_ids:
        raise KeyError(f"missing states for contributors: {missing_ids}")

    masked_contributions: Dict[int, OrderedDict] = {}
    for contributor_id in contributor_ids:
        masked_contributions[contributor_id] = OrderedDict(
            (key, tensor.detach().clone().to(device=device or tensor.device))
            for key, tensor in previous_states[contributor_id].items()
        )

    # Canonical ordering fixes both seed derivation and the +/- sign convention.
    for client_a_id, client_b_id in combinations(sorted(contributor_ids), 2):
        pair_seed = get_pairwise_mask_seed(
            round_idx=round_idx,
            target_client_id=target_client_id,
            client_a_id=client_a_id,
            client_b_id=client_b_id,
            base_seed=base_seed,
        )
        pair_mask = generate_deterministic_mask_like_state_dict(
            previous_states[client_a_id], seed=pair_seed, device=device
        )

        for key, tensor in previous_states[client_a_id].items():
            if torch.is_floating_point(tensor) or torch.is_complex(tensor):
                # For a < b, contributor a adds M and contributor b subtracts M.
                masked_contributions[client_a_id][key] = (
                    masked_contributions[client_a_id][key] + pair_mask[key]
                )
                masked_contributions[client_b_id][key] = (
                    masked_contributions[client_b_id][key] - pair_mask[key]
                )

    return masked_contributions


def max_state_dict_difference(first: StateDict, second: StateDict) -> float:
    """Return the maximum absolute difference across floating-point tensors."""

    _validate_matching_states(first, second)
    maximum = 0.0
    for key, first_tensor in first.items():
        if torch.is_floating_point(first_tensor) or torch.is_complex(first_tensor):
            second_tensor = second[key].to(
                device=first_tensor.device, dtype=first_tensor.dtype
            )
            difference = (first_tensor - second_tensor).abs().max().item()
            maximum = max(maximum, float(difference))
    return maximum
