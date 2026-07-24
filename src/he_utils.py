"""Selective CKKS homomorphic-encryption utilities for DFL aggregation."""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import torch

from aggregation import average_state_dicts


StateDict = Mapping[str, torch.Tensor]
Device = Optional[Union[str, torch.device]]

TENSEAL_ERROR_MESSAGE = (
    "TenSEAL is required for --security_mode selective_he. "
    "Install it with: pip install tenseal"
)


@dataclass(frozen=True)
class ParameterMetadata:
    """Information required to reconstruct one flattened parameter tensor."""

    name: str
    shape: Tuple[int, ...]
    num_elements: int
    dtype: torch.dtype
    device: torch.device


@dataclass
class CKKSContextBundle:
    """Target-specific private/public CKKS material used in the simulation."""

    private_context: Any
    public_context: Any
    secret_key: Any


def import_tenseal_or_raise() -> Any:
    """Import TenSEAL lazily so non-HE modes do not require the package."""

    try:
        import tenseal as ts
    except ImportError as error:
        raise RuntimeError(TENSEAL_ERROR_MESSAGE) from error
    return ts


def parse_coeff_mod_bits(value: Union[str, Sequence[int]]) -> List[int]:
    """Parse a comma-separated coefficient modulus bit-size list."""

    if isinstance(value, str):
        try:
            bits = [int(item.strip()) for item in value.split(",") if item.strip()]
        except ValueError as error:
            raise ValueError(
                "he_coeff_mod_bits must be comma-separated integers"
            ) from error
    else:
        bits = [int(item) for item in value]
    if not bits or any(bit <= 0 for bit in bits):
        raise ValueError("he_coeff_mod_bits must contain positive integers")
    return bits


def create_ckks_context(
    poly_modulus_degree: int = 8192,
    coeff_mod_bit_sizes: Sequence[int] = (60, 40, 40, 60),
    scale_bits: int = 40,
) -> CKKSContextBundle:
    """Create target-owned CKKS keys plus a public encryption context copy."""

    if poly_modulus_degree <= 0 or scale_bits <= 0:
        raise ValueError("CKKS polynomial degree and scale bits must be positive")

    ts = import_tenseal_or_raise()
    private_context = ts.context(
        ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=poly_modulus_degree,
        coeff_mod_bit_sizes=list(coeff_mod_bit_sizes),
    )
    private_context.global_scale = 2**scale_bits
    secret_key = private_context.secret_key()

    # Contributors receive only this public copy. Galois and relinearization
    # keys are unnecessary because this prototype uses addition and a scalar
    # multiplication only (no rotations or ciphertext-ciphertext products).
    public_context = private_context.copy()
    public_context.make_context_public()
    return CKKSContextBundle(private_context, public_context, secret_key)


def get_final_layer_param_names(state_dict: StateDict) -> List[str]:
    """Identify the last floating-point weight and its matching bias."""

    weight_names = [
        name
        for name, tensor in state_dict.items()
        if name.endswith(".weight")
        and tensor.ndim >= 2
        and torch.is_floating_point(tensor)
    ]
    if not weight_names:
        raise ValueError("could not identify a final linear-layer weight")

    final_weight = weight_names[-1]
    prefix = final_weight[: -len(".weight")]
    final_bias = f"{prefix}.bias"
    selected = [final_weight]
    if final_bias in state_dict:
        bias = state_dict[final_bias]
        if not torch.is_floating_point(bias):
            raise ValueError("final-layer bias must be floating point for CKKS")
        selected.append(final_bias)
    return selected


def flatten_selected_params(
    state_dict: StateDict, selected_param_names: Sequence[str]
) -> Tuple[np.ndarray, List[ParameterMetadata]]:
    """Flatten selected tensors into a CKKS-compatible float64 array."""

    if not selected_param_names:
        raise ValueError("at least one parameter must be selected for HE")

    flattened: List[np.ndarray] = []
    metadata: List[ParameterMetadata] = []
    for name in selected_param_names:
        if name not in state_dict:
            raise KeyError(f"selected parameter not found in state_dict: {name}")
        tensor = state_dict[name]
        if not torch.is_floating_point(tensor):
            raise ValueError(f"CKKS requires a floating-point tensor: {name}")
        values = (
            tensor.detach().cpu().reshape(-1).numpy().astype(np.float64, copy=True)
        )
        flattened.append(values)
        metadata.append(
            ParameterMetadata(
                name=name,
                shape=tuple(tensor.shape),
                num_elements=tensor.numel(),
                dtype=tensor.dtype,
                device=tensor.device,
            )
        )

    return np.concatenate(flattened), metadata


def reconstruct_selected_params(
    flat_values: Sequence[float],
    metadata: Sequence[ParameterMetadata],
    device: Device = None,
) -> OrderedDict:
    """Reconstruct selected parameter tensors from decrypted flat values."""

    values = np.asarray(flat_values, dtype=np.float64)
    expected_values = sum(item.num_elements for item in metadata)
    if values.size != expected_values:
        raise ValueError(
            f"decrypted vector has {values.size} values; expected {expected_values}"
        )

    reconstructed = OrderedDict()
    offset = 0
    for item in metadata:
        target_device = torch.device(device) if device is not None else item.device
        tensor_values = values[offset : offset + item.num_elements].copy()
        reconstructed[item.name] = torch.tensor(
            tensor_values, dtype=item.dtype, device=target_device
        ).reshape(item.shape)
        offset += item.num_elements
    return reconstructed


def encrypt_selected_state(
    state_dict: StateDict,
    selected_param_names: Sequence[str],
    context: CKKSContextBundle,
) -> Tuple[Any, List[ParameterMetadata], float, int]:
    """Flatten and encrypt selected parameters with the target public context."""

    ts = import_tenseal_or_raise()
    values, metadata = flatten_selected_params(state_dict, selected_param_names)
    start = time.perf_counter()
    encrypted_vector = ts.ckks_vector(context.public_context, values.tolist())
    encryption_time = time.perf_counter() - start
    ciphertext_size = len(encrypted_vector.serialize())
    return encrypted_vector, metadata, encryption_time, ciphertext_size


def homomorphic_average_encrypted_vectors(encrypted_vectors: Sequence[Any]) -> Any:
    """Homomorphically sum CKKS vectors and multiply by 1 / contributor count."""

    if not encrypted_vectors:
        raise ValueError("at least one encrypted vector is required")
    encrypted_sum = encrypted_vectors[0]
    for encrypted_vector in encrypted_vectors[1:]:
        encrypted_sum = encrypted_sum + encrypted_vector
    return encrypted_sum * (1.0 / len(encrypted_vectors))


def decrypt_selected_state(
    encrypted_average: Any,
    metadata: Sequence[ParameterMetadata],
    device: Device,
    secret_key: Any,
) -> Tuple[OrderedDict, float]:
    """Decrypt and reconstruct selected parameters on the requested device."""

    start = time.perf_counter()
    decrypted_values = encrypted_average.decrypt(secret_key)
    decrypted_state = reconstruct_selected_params(
        decrypted_values, metadata, device=device
    )
    return decrypted_state, time.perf_counter() - start


def selected_plain_size_bytes(
    state_dict: StateDict, selected_param_names: Sequence[str]
) -> int:
    """Return the plaintext byte size of the selected parameter tensors."""

    return sum(
        state_dict[name].numel() * state_dict[name].element_size()
        for name in selected_param_names
    )


def homomorphic_average_selected_params_only(
    target_client_id: int,
    contributor_ids: Sequence[int],
    previous_states: Mapping[int, StateDict],
    target_context: CKKSContextBundle,
    selected_param_names: Sequence[str],
    device: Device,
) -> Tuple[OrderedDict, Dict[str, Union[int, float]]]:
    """Return only the target's decrypted homomorphic selected-parameter average."""

    if target_client_id not in contributor_ids:
        raise ValueError("target client must be included in contributor_ids")
    if len(set(contributor_ids)) != len(contributor_ids):
        raise ValueError("contributor_ids must be unique")

    encrypted_vectors = []
    reference_metadata: Optional[List[ParameterMetadata]] = None
    encryption_time = 0.0
    transmitted_ciphertext_bytes = 0

    for contributor_id in contributor_ids:
        if contributor_id not in previous_states:
            raise KeyError(f"missing state for contributor {contributor_id}")
        encrypted, metadata, elapsed, ciphertext_bytes = encrypt_selected_state(
            previous_states[contributor_id], selected_param_names, target_context
        )
        encrypted_vectors.append(encrypted)
        encryption_time += elapsed
        if reference_metadata is None:
            reference_metadata = metadata
        elif [item.name for item in metadata] != [
            item.name for item in reference_metadata
        ]:
            raise ValueError("contributors have incompatible selected parameters")
        if contributor_id != target_client_id:
            transmitted_ciphertext_bytes += ciphertext_bytes

    aggregation_start = time.perf_counter()
    encrypted_average = homomorphic_average_encrypted_vectors(encrypted_vectors)
    aggregation_time = time.perf_counter() - aggregation_start

    if reference_metadata is None:
        raise RuntimeError("HE aggregation did not produce parameter metadata")
    decrypted_selected, decryption_time = decrypt_selected_state(
        encrypted_average,
        reference_metadata,
        device=device,
        secret_key=target_context.secret_key,
    )

    plaintext_selected_average = average_state_dicts(
        OrderedDict(
            (name, previous_states[contributor_id][name])
            for name in selected_param_names
        )
        for contributor_id in contributor_ids
    )

    reconstruction_error = 0.0
    for name in selected_param_names:
        reference = plaintext_selected_average[name].to(
            device=decrypted_selected[name].device,
            dtype=decrypted_selected[name].dtype,
        )
        error = (decrypted_selected[name] - reference).abs().max().item()
        reconstruction_error = max(reconstruction_error, float(error))

    values_per_contributor = sum(item.num_elements for item in reference_metadata)
    plain_bytes_per_contributor = selected_plain_size_bytes(
        previous_states[target_client_id], selected_param_names
    )
    transmitted_plain_selected_bytes = plain_bytes_per_contributor * (
        len(contributor_ids) - 1
    )
    total_time = encryption_time + aggregation_time + decryption_time
    metrics: Dict[str, Union[int, float]] = {
        "he_encryption_time_seconds": encryption_time,
        "he_aggregation_time_seconds": aggregation_time,
        "he_decryption_time_seconds": decryption_time,
        "he_total_time_seconds": total_time,
        "he_ciphertext_bytes": transmitted_ciphertext_bytes,
        "he_num_encrypted_values": values_per_contributor * len(contributor_ids),
        "he_plain_selected_bytes": transmitted_plain_selected_bytes,
        "he_reconstruction_max_error": reconstruction_error,
    }
    return decrypted_selected, metrics


def selective_he_aggregate_for_target(
    target_client_id: int,
    contributor_ids: Sequence[int],
    previous_states: Mapping[int, StateDict],
    target_context: CKKSContextBundle,
    selected_param_names: Sequence[str],
    device: Device,
) -> Tuple[OrderedDict, Dict[str, Union[int, float]]]:
    """Aggregate plaintext non-selected and CKKS-selected model parameters."""

    decrypted_selected, metrics = homomorphic_average_selected_params_only(
        target_client_id=target_client_id,
        contributor_ids=contributor_ids,
        previous_states=previous_states,
        target_context=target_context,
        selected_param_names=selected_param_names,
        device=device,
    )
    plaintext_average = average_state_dicts(
        previous_states[contributor_id] for contributor_id in contributor_ids
    )
    aggregated_state = OrderedDict(
        (key, tensor.detach().clone().to(device=device or tensor.device))
        for key, tensor in plaintext_average.items()
    )
    for name in selected_param_names:
        aggregated_state[name] = decrypted_selected[name]
    return aggregated_state, metrics
