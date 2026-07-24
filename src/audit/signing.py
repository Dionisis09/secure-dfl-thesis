"""Real Ed25519 signing for the product-style audit layer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .hashing import sha256_bytes, sha256_text, stable_json


@dataclass(frozen=True)
class ClientKeyPair:
    client_id: int
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    public_key_id: str

    def public_key_b64(self) -> str:
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")


def deterministic_private_key_bytes(client_id: int, seed: int) -> bytes:
    material = f"secure-fl-audit|seed={seed}|client={client_id}".encode("utf-8")
    return bytes.fromhex(sha256_bytes(material))


def create_client_key_pair(client_id: int, seed: int) -> ClientKeyPair:
    private_key = Ed25519PrivateKey.from_private_bytes(
        deterministic_private_key_bytes(client_id, seed)
    )
    public_key = private_key.public_key()
    raw_public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key_id = f"client_{client_id}_{sha256_bytes(raw_public)[:16]}"
    return ClientKeyPair(
        client_id=client_id,
        private_key=private_key,
        public_key=public_key,
        public_key_id=public_key_id,
    )


def create_keyring(num_clients: int, seed: int) -> Dict[int, ClientKeyPair]:
    return {
        client_id: create_client_key_pair(client_id, seed)
        for client_id in range(num_clients)
    }


def signing_payload(
    experiment_name: str,
    client_id: int,
    round_number: int,
    model_hash: str,
    security_mode: str,
    merkle_root: str,
) -> bytes:
    return stable_json(
        {
            "experiment_name": experiment_name,
            "client_id": client_id,
            "round_number": round_number,
            "model_hash": model_hash,
            "security_mode": security_mode,
            "merkle_root": merkle_root,
        }
    ).encode("utf-8")


def sign_payload(private_key: Ed25519PrivateKey, payload: bytes) -> str:
    return base64.b64encode(private_key.sign(payload)).decode("ascii")


def verify_signature(public_key_b64: str, payload: bytes, signature_b64: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64)
        )
        public_key.verify(base64.b64decode(signature_b64), payload)
        return True
    except (InvalidSignature, ValueError):
        return False


def public_keys_manifest(keyring: Mapping[int, ClientKeyPair]) -> Dict[str, dict]:
    return {
        f"client_{client_id}": {
            "client_id": client_id,
            "public_key_id": key_pair.public_key_id,
            "public_key": key_pair.public_key_b64(),
            "algorithm": "Ed25519",
        }
        for client_id, key_pair in sorted(keyring.items())
    }


def key_manifest_hash(manifest: Mapping[str, dict]) -> str:
    return sha256_text(stable_json(manifest))
