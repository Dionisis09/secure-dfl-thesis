"""Safe NumPy model-state serialization for network transport."""

from __future__ import annotations

import hashlib
import io
import json
from collections import OrderedDict
from typing import Mapping

import numpy as np


State = Mapping[str, np.ndarray]


def encode_state(state: State) -> bytes:
    if not state:
        raise ValueError("state cannot be empty")
    arrays: dict[str, np.ndarray] = {}
    for name, value in state.items():
        if not isinstance(name, str) or not name:
            raise ValueError("state names must be non-empty strings")
        array = np.asarray(value)
        if array.dtype.hasobject:
            raise ValueError("object arrays are not allowed")
        arrays[name] = np.ascontiguousarray(array)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def decode_state(payload: bytes, max_payload_bytes: int) -> OrderedDict[str, np.ndarray]:
    if len(payload) > max_payload_bytes:
        raise ValueError("model payload exceeds configured size limit")
    result: OrderedDict[str, np.ndarray] = OrderedDict()
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        for name in sorted(archive.files):
            value = archive[name]
            if value.dtype.hasobject:
                raise ValueError("object arrays are not allowed")
            result[name] = np.array(value, copy=True)
    if not result:
        raise ValueError("decoded state is empty")
    return result


def hash_payload(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_state(state: State) -> str:
    """Create a deterministic hash from array names, shapes, dtypes and bytes."""

    digest = hashlib.sha256()
    for name in sorted(state):
        array = np.ascontiguousarray(np.asarray(state[name]))
        metadata = {
            "name": name,
            "shape": list(array.shape),
            "dtype": array.dtype.str,
        }
        digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
        digest.update(b"\0")
        digest.update(array.tobytes(order="C"))
        digest.update(b"\0")
    return digest.hexdigest()


def average_states(states: list[State]) -> OrderedDict[str, np.ndarray]:
    if not states:
        raise ValueError("at least one state is required")
    names = list(states[0].keys())
    for state in states[1:]:
        if list(state.keys()) != names:
            raise ValueError("state keys do not match")
    output: OrderedDict[str, np.ndarray] = OrderedDict()
    for name in names:
        first = np.asarray(states[0][name])
        for state in states[1:]:
            other = np.asarray(state[name])
            if other.shape != first.shape or other.dtype != first.dtype:
                raise ValueError(f"tensor metadata mismatch for {name}")
        if np.issubdtype(first.dtype, np.floating) or np.issubdtype(
            first.dtype, np.complexfloating
        ):
            accumulator = np.zeros_like(first)
            for state in states:
                accumulator += np.asarray(state[name])
            output[name] = accumulator / len(states)
        else:
            output[name] = np.array(first, copy=True)
    return output
