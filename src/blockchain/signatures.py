"""Deterministic simulated client signatures for the audit blockchain.

This module intentionally does not implement real public-key cryptography. It
creates reproducible identifiers and SHA256 signatures for thesis-level audit
experiments.
"""

from __future__ import annotations

from typing import Dict, Mapping

from .hashing import sha256_text


def generate_simulated_key_pair(client_id: int, seed: int = 0) -> Dict[str, str]:
    private_key = sha256_text(f"simulated-private-key|seed={seed}|client={client_id}")
    public_key_id = sha256_text(f"simulated-public-key|client={client_id}|{private_key}")[
        :16
    ]
    return {
        "private_key": private_key,
        "public_key_id": f"client_{client_id}_{public_key_id}",
    }


def generate_client_key_pairs(num_clients: int, seed: int = 0) -> Dict[int, Dict[str, str]]:
    return {
        client_id: generate_simulated_key_pair(client_id, seed)
        for client_id in range(num_clients)
    }


def sign_model_hash(
    client_id: int,
    round_number: int,
    model_hash: str,
    public_key_id: str,
) -> str:
    return sha256_text(
        f"client_id={client_id}|round={round_number}|model_hash={model_hash}|"
        f"public_key_id={public_key_id}"
    )


def build_round_signatures(
    round_number: int,
    model_hashes: Mapping[str, str],
    public_keys: Mapping[int, str],
) -> Dict[str, Dict[str, str]]:
    signatures: Dict[str, Dict[str, str]] = {}
    for client_id, public_key_id in sorted(public_keys.items()):
        model_hash = model_hashes.get(f"client_{client_id}_hash", "")
        signatures[f"client_{client_id}"] = {
            "public_key_id": public_key_id,
            "signature": sign_model_hash(
                client_id=client_id,
                round_number=round_number,
                model_hash=model_hash,
                public_key_id=public_key_id,
            ),
        }
    return signatures


def verify_round_signatures(
    round_number: int,
    model_hashes: Mapping[str, str],
    signatures: Mapping[str, Mapping[str, str]],
    public_keys: Mapping[str, str],
) -> bool:
    for client_key, public_key_id in sorted(public_keys.items()):
        try:
            client_id = int(client_key.replace("client_", ""))
        except ValueError:
            return False

        model_hash = model_hashes.get(f"client_{client_id}_hash")
        signature_data = signatures.get(client_key)
        if not model_hash or not signature_data:
            return False
        if signature_data.get("public_key_id") != public_key_id:
            return False

        expected = sign_model_hash(
            client_id=client_id,
            round_number=round_number,
            model_hash=model_hash,
            public_key_id=public_key_id,
        )
        if signature_data.get("signature") != expected:
            return False
    return True
