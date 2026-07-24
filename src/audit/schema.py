"""Audit record construction helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .hashing import compute_record_hash, sha256_json


AUDIT_SCHEMA_VERSION = "1.0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def configuration_hash(configuration: Mapping[str, Any]) -> str:
    return sha256_json(configuration)


def finalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(record)
    output["record_hash"] = compute_record_hash(output)
    return output
