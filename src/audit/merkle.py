"""Merkle tree helpers for per-round client model hashes."""

from __future__ import annotations

from typing import Dict, List, Mapping

from .hashing import sha256_text


def _leaf_hash(client_key: str, model_hash: str) -> str:
    return sha256_text(f"leaf|{client_key}|{model_hash}")


def _parent_hash(left: str, right: str) -> str:
    return sha256_text(f"node|{left}|{right}")


def build_merkle_tree(client_hashes: Mapping[str, str]) -> List[List[str]]:
    leaves = [
        _leaf_hash(client_key, model_hash)
        for client_key, model_hash in sorted(client_hashes.items())
    ]
    if not leaves:
        return [[""]]

    tree = [leaves]
    level = leaves
    while len(level) > 1:
        next_level = []
        for idx in range(0, len(level), 2):
            left = level[idx]
            right = level[idx + 1] if idx + 1 < len(level) else left
            next_level.append(_parent_hash(left, right))
        tree.append(next_level)
        level = next_level
    return tree


def merkle_root(client_hashes: Mapping[str, str]) -> str:
    tree = build_merkle_tree(client_hashes)
    return tree[-1][0] if tree and tree[-1] else ""


def build_merkle_proofs(client_hashes: Mapping[str, str]) -> Dict[str, List[dict]]:
    ordered_clients = [client_key for client_key, _ in sorted(client_hashes.items())]
    tree = build_merkle_tree(client_hashes)
    proofs: Dict[str, List[dict]] = {}
    for leaf_index, client_key in enumerate(ordered_clients):
        proof = []
        index = leaf_index
        for level in tree[:-1]:
            sibling_index = index + 1 if index % 2 == 0 else index - 1
            if sibling_index >= len(level):
                sibling_index = index
            proof.append(
                {
                    "position": "right" if index % 2 == 0 else "left",
                    "hash": level[sibling_index],
                }
            )
            index //= 2
        proofs[client_key] = proof
    return proofs


def verify_merkle_proof(
    client_key: str, model_hash: str, proof: List[dict], expected_root: str
) -> bool:
    current = _leaf_hash(client_key, model_hash)
    for item in proof:
        sibling = item["hash"]
        if item["position"] == "right":
            current = _parent_hash(current, sibling)
        else:
            current = _parent_hash(sibling, current)
    return current == expected_root
