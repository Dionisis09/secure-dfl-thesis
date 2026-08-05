"""Signed peer-to-peer update envelope."""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .codec import decode_state, encode_state, hash_payload, hash_state
from .crypto import canonical_json_bytes, public_key_id, sign_b64, verify_b64
from .masking import (
    apply_mask,
    apply_pairwise_canceling_mask,
    estimate_masking_overhead_bytes,
    estimate_pairwise_seed_overhead_bytes,
    generate_mask_for_state,
    remove_mask,
)


PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class UpdateEnvelope:
    protocol_version: str
    message_id: str
    experiment_id: str
    round_number: int
    sender_id: str
    recipient_id: str
    sent_at_unix: float
    payload_encoding: str
    payload_hash: str
    payload_b64: str
    public_key_id: str
    signature_b64: str
    security_mode: str = "none"
    original_payload_hash: str = ""
    mask_payload_hash: str = ""
    mask_payload_b64: str = ""
    masking_overhead_bytes: int = 0
    mask_contributor_ids: tuple[str, ...] = ()

    def signing_fields(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "experiment_id": self.experiment_id,
            "round_number": self.round_number,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "sent_at_unix": self.sent_at_unix,
            "payload_encoding": self.payload_encoding,
            "payload_hash": self.payload_hash,
            "public_key_id": self.public_key_id,
            "security_mode": self.security_mode,
            "original_payload_hash": self.original_payload_hash,
            "mask_payload_hash": self.mask_payload_hash,
            "mask_payload_b64": self.mask_payload_b64,
            "masking_overhead_bytes": self.masking_overhead_bytes,
            "mask_contributor_ids": list(self.mask_contributor_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UpdateEnvelope":
        return cls(
            protocol_version=str(value["protocol_version"]),
            message_id=str(value["message_id"]),
            experiment_id=str(value["experiment_id"]),
            round_number=int(value["round_number"]),
            sender_id=str(value["sender_id"]),
            recipient_id=str(value["recipient_id"]),
            sent_at_unix=float(value["sent_at_unix"]),
            payload_encoding=str(value["payload_encoding"]),
            payload_hash=str(value["payload_hash"]),
            payload_b64=str(value["payload_b64"]),
            public_key_id=str(value["public_key_id"]),
            signature_b64=str(value["signature_b64"]),
            security_mode=str(value.get("security_mode", "none")),
            original_payload_hash=str(
                value.get("original_payload_hash", value["payload_hash"])
            ),
            mask_payload_hash=str(value.get("mask_payload_hash", "")),
            mask_payload_b64=str(value.get("mask_payload_b64", "")),
            masking_overhead_bytes=int(value.get("masking_overhead_bytes", 0)),
            mask_contributor_ids=tuple(str(item) for item in value.get("mask_contributor_ids", [])),
        )


def create_envelope(
    *,
    private_key: Ed25519PrivateKey,
    experiment_id: str,
    round_number: int,
    sender_id: str,
    recipient_id: str,
    payload: bytes,
    security_mode: str = "none",
    max_payload_bytes: int = 32 * 1024 * 1024,
    mask_seed: int | None = None,
    pairwise_contributor_ids: list[str] | None = None,
) -> UpdateEnvelope:
    sent_at = time.time()
    original_payload_digest = hash_payload(payload)
    transmitted_payload = payload
    mask_payload = b""
    masking_overhead_bytes = 0
    mask_contributor_ids: tuple[str, ...] = ()
    if security_mode == "masking":
        state = decode_state(payload, max_payload_bytes)
        original_payload_digest = hash_state(state)
        mask = generate_mask_for_state(state, seed=mask_seed)
        transmitted_payload = encode_state(apply_mask(state, mask))
        mask_payload = encode_state(mask)
        masking_overhead_bytes = estimate_masking_overhead_bytes(mask)
    elif security_mode == "pairwise_masking":
        state = decode_state(payload, max_payload_bytes)
        original_payload_digest = hash_state(state)
        contributors = sorted(set(pairwise_contributor_ids or [sender_id, recipient_id]))
        if sender_id not in contributors or recipient_id not in contributors:
            raise ValueError("pairwise contributor set must include sender and recipient")
        transmitted_payload = encode_state(
            apply_pairwise_canceling_mask(
                state,
                experiment_id=experiment_id,
                round_number=round_number,
                target_id=recipient_id,
                contributor_id=sender_id,
                contributor_ids=contributors,
            )
        )
        mask_contributor_ids = tuple(contributors)
        masking_overhead_bytes = estimate_pairwise_seed_overhead_bytes(contributors)
    elif security_mode != "none":
        raise ValueError(f"unsupported security mode: {security_mode}")

    payload_digest = hash_payload(transmitted_payload)
    mask_payload_hash = hash_payload(mask_payload) if mask_payload else ""
    key_id = public_key_id(private_key.public_key())
    message_id = hashlib.sha256(
        f"{experiment_id}|{round_number}|{sender_id}|{recipient_id}|{security_mode}|{original_payload_digest}|{payload_digest}".encode(
            "utf-8"
        )
    ).hexdigest()
    unsigned = UpdateEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_id=message_id,
        experiment_id=experiment_id,
        round_number=round_number,
        sender_id=sender_id,
        recipient_id=recipient_id,
        sent_at_unix=sent_at,
        payload_encoding="numpy-npz-base64",
        payload_hash=payload_digest,
        payload_b64=base64.b64encode(transmitted_payload).decode("ascii"),
        public_key_id=key_id,
        signature_b64="",
        security_mode=security_mode,
        original_payload_hash=original_payload_digest,
        mask_payload_hash=mask_payload_hash,
        mask_payload_b64=base64.b64encode(mask_payload).decode("ascii") if mask_payload else "",
        masking_overhead_bytes=masking_overhead_bytes,
        mask_contributor_ids=mask_contributor_ids,
    )
    signature = sign_b64(private_key, canonical_json_bytes(unsigned.signing_fields()))
    return UpdateEnvelope(**{**unsigned.to_dict(), "signature_b64": signature})


def verify_envelope(
    envelope: UpdateEnvelope,
    *,
    trusted_key: Ed25519PublicKey,
    expected_experiment_id: str,
    expected_recipient_id: str,
    max_payload_bytes: int,
) -> bytes:
    if envelope.protocol_version != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    if envelope.experiment_id != expected_experiment_id:
        raise ValueError("experiment id mismatch")
    if envelope.recipient_id != expected_recipient_id:
        raise ValueError("recipient id mismatch")
    if envelope.payload_encoding != "numpy-npz-base64":
        raise ValueError("unsupported payload encoding")
    if envelope.public_key_id != public_key_id(trusted_key):
        raise ValueError("public key id mismatch")
    if not verify_b64(
        trusted_key,
        canonical_json_bytes(envelope.signing_fields()),
        envelope.signature_b64,
    ):
        raise ValueError("invalid Ed25519 signature")
    payload = base64.b64decode(envelope.payload_b64, validate=True)
    if len(payload) > max_payload_bytes:
        raise ValueError("model payload exceeds configured size limit")
    if hash_payload(payload) != envelope.payload_hash:
        raise ValueError("payload hash mismatch")
    if envelope.security_mode == "none":
        if envelope.original_payload_hash and envelope.original_payload_hash != envelope.payload_hash:
            raise ValueError("original payload hash mismatch")
        return payload
    if envelope.security_mode == "masking":
        mask_payload = base64.b64decode(envelope.mask_payload_b64, validate=True)
        if len(mask_payload) > max_payload_bytes:
            raise ValueError("mask payload exceeds configured size limit")
        if hash_payload(mask_payload) != envelope.mask_payload_hash:
            raise ValueError("mask payload hash mismatch")
        masked_state = decode_state(payload, max_payload_bytes)
        mask = decode_state(mask_payload, max_payload_bytes)
        unmasked_state = remove_mask(masked_state, mask)
        return encode_state(unmasked_state)
    if envelope.security_mode == "pairwise_masking":
        if envelope.mask_payload_b64 or envelope.mask_payload_hash:
            raise ValueError("pairwise masking must not transport raw mask payloads")
        if envelope.sender_id not in envelope.mask_contributor_ids:
            raise ValueError("sender is missing from pairwise contributor set")
        if envelope.recipient_id not in envelope.mask_contributor_ids:
            raise ValueError("recipient is missing from pairwise contributor set")
        return payload
    raise ValueError(f"unsupported security mode: {envelope.security_mode}")
