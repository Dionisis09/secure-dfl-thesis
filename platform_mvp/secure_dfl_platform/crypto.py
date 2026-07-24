"""Ed25519 identity and canonical-signature helpers."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def derive_demo_private_key(node_id: str, seed: str) -> Ed25519PrivateKey:
    """Create a reproducible demo key. Never use this derivation in production."""

    material = hashlib.sha256(
        f"secure-dfl-platform|{seed}|{node_id}".encode("utf-8")
    ).digest()
    return Ed25519PrivateKey.from_private_bytes(material)


def load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key must be Ed25519")
    return key


def load_public_key_b64(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))


def public_key_b64(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def public_key_id(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def sign_b64(key: Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(key.sign(message)).decode("ascii")


def verify_b64(key: Ed25519PublicKey, message: bytes, signature: str) -> bool:
    try:
        key.verify(base64.b64decode(signature, validate=True), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def trusted_keys_from_file(path: Path) -> dict[str, Ed25519PublicKey]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("trusted key manifest must be a JSON object")
    return {node_id: load_public_key_b64(value) for node_id, value in manifest.items()}

