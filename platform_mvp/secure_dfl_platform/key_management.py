"""Deployment key generation helpers for Secure DFL platform nodes."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .crypto import public_key_b64, public_key_id


def write_node_keys(
    *,
    node_ids: list[str],
    output_dir: Path,
    overwrite: bool = False,
) -> dict[str, dict[str, str]]:
    """Generate one Ed25519 private key per node and a trusted-key manifest."""

    if not node_ids:
        raise ValueError("at least one node id is required")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("node ids must be unique")

    output_dir.mkdir(parents=True, exist_ok=True)
    nodes_dir = output_dir / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, str] = {}
    metadata: dict[str, dict[str, str]] = {}
    for node_id in node_ids:
        private_key = Ed25519PrivateKey.generate()
        private_path = nodes_dir / f"{node_id}_private_key.pem"
        if private_path.exists() and not overwrite:
            raise FileExistsError(
                f"{private_path} already exists; pass --overwrite to replace it"
            )
        private_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        public_key = private_key.public_key()
        manifest[node_id] = public_key_b64(public_key)
        metadata[node_id] = {
            "private_key_file": str(private_path),
            "public_key_b64": manifest[node_id],
            "public_key_id": public_key_id(public_key),
        }

    manifest_path = output_dir / "trusted_keys.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(
            f"{manifest_path} already exists; pass --overwrite to replace it"
        )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    metadata_path = output_dir / "key_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "trusted_keys_file": str(manifest_path),
                "nodes": metadata,
                "warning": "Private keys are unencrypted demo/deployment files. Protect them with OS permissions or a secret manager in production.",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata
