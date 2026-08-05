"""Environment-driven node configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    host: str
    port: int
    experiment_id: str
    peer_urls: Mapping[str, str]
    data_dir: Path
    admin_token: str
    max_payload_bytes: int = 32 * 1024 * 1024
    min_peer_updates_to_finalize: int = 0
    security_mode: str = "none"
    request_timeout_seconds: float = 10.0
    demo_identity_seed: str | None = None
    private_key_file: Path | None = None
    trusted_keys_file: Path | None = None
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None
    tls_ca_file: Path | None = None
    tls_require_client_cert: bool = False

    @classmethod
    def from_env(cls) -> "NodeConfig":
        node_id = os.getenv("DFL_NODE_ID", "node0").strip()
        host = os.getenv("DFL_HOST", "0.0.0.0").strip()
        port = int(os.getenv("DFL_PORT", "9000"))
        experiment_id = os.getenv("DFL_EXPERIMENT_ID", "commercial_mvp_demo").strip()
        peer_urls = json.loads(os.getenv("DFL_PEERS_JSON", "{}"))
        if not isinstance(peer_urls, dict):
            raise ValueError("DFL_PEERS_JSON must be a JSON object")
        peer_urls = {
            str(peer_id): str(url).rstrip("/")
            for peer_id, url in peer_urls.items()
            if str(peer_id) != node_id
        }
        min_peer_updates = int(
            os.getenv("DFL_MIN_PEER_UPDATES_TO_FINALIZE", str(len(peer_urls)))
        )
        config = cls(
            node_id=node_id,
            host=host,
            port=port,
            experiment_id=experiment_id,
            peer_urls=peer_urls,
            data_dir=Path(os.getenv("DFL_DATA_DIR", f".runtime/{node_id}")),
            admin_token=os.getenv("DFL_ADMIN_TOKEN", "change-me"),
            max_payload_bytes=int(os.getenv("DFL_MAX_PAYLOAD_BYTES", str(32 * 1024 * 1024))),
            min_peer_updates_to_finalize=min_peer_updates,
            security_mode=os.getenv("DFL_SECURITY_MODE", "none").strip().lower(),
            request_timeout_seconds=float(os.getenv("DFL_REQUEST_TIMEOUT_SECONDS", "10")),
            demo_identity_seed=os.getenv("DFL_DEMO_IDENTITY_SEED"),
            private_key_file=_optional_path("DFL_PRIVATE_KEY_FILE"),
            trusted_keys_file=_optional_path("DFL_TRUSTED_KEYS_FILE"),
            tls_cert_file=_optional_path("DFL_TLS_CERT_FILE"),
            tls_key_file=_optional_path("DFL_TLS_KEY_FILE"),
            tls_ca_file=_optional_path("DFL_TLS_CA_FILE"),
            tls_require_client_cert=_env_bool("DFL_TLS_REQUIRE_CLIENT_CERT"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.node_id:
            raise ValueError("node_id cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.experiment_id:
            raise ValueError("experiment_id cannot be empty")
        if not 0 <= self.min_peer_updates_to_finalize <= len(self.peer_urls):
            raise ValueError(
                "DFL_MIN_PEER_UPDATES_TO_FINALIZE must be between 0 and the number of peers"
            )
        if self.security_mode not in {"none", "masking", "pairwise_masking"}:
            raise ValueError("DFL_SECURITY_MODE must be one of: none, masking, pairwise_masking")
        if self.admin_token == "change-me":
            print("WARNING: DFL_ADMIN_TOKEN uses the development default.")
        if not self.demo_identity_seed and not self.private_key_file:
            raise ValueError(
                "configure DFL_PRIVATE_KEY_FILE or DFL_DEMO_IDENTITY_SEED"
            )
        if self.tls_cert_file and not self.tls_key_file:
            raise ValueError("DFL_TLS_KEY_FILE is required with DFL_TLS_CERT_FILE")
        if self.tls_require_client_cert and not self.tls_ca_file:
            raise ValueError("DFL_TLS_CA_FILE is required for client certificate verification")


def _optional_path(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None
