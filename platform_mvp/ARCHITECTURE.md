# Secure DFL Platform MVP - Architecture

## Components

### Node agent

Each node is an independent HTTP process. It owns a private Ed25519 key, a list
of trusted peer public keys and a local runtime directory. It accepts local model
states from an authorized local trainer, signs outgoing update envelopes and
verifies incoming peer envelopes.

### Signed update envelope

Every peer exchange includes the experiment id, round number, sender, recipient,
payload hash, public key id and Ed25519 signature. The payload itself is encoded
as a safe NumPy NPZ archive without pickle loading.

### Masking mode

The platform supports `DFL_SECURITY_MODE=masking`. In this mode, outgoing model
state tensors are additively masked before they are placed in the signed update
envelope. The receiver verifies the signature, reconstructs the original tensors
from the masked state and mask, and only then performs normal decentralized
aggregation.

This first version is intentionally a controlled masking simulation. It records
masking overhead and demonstrates the protocol workflow, but it is not yet a
full cryptographic secure aggregation protocol because the receiver obtains the
mask needed for reconstruction.

### Decentralized aggregation

Each node aggregates its own local state with the states received from its
configured peers. By default, all peer updates are required. The quorum setting
allows a node to finalize with a smaller number of received peer updates when
dropout tolerance is needed.

### Audit log

Every node writes a signed append-only JSONL audit log. Records contain the
previous record hash, event details, recomputed record hash, public key id and
signature. The verifier checks hash continuity and signatures after the run.
If a record is modified after the fact, the recomputed hash and signature checks
fail.

### Operator dashboard

The dashboard polls node status APIs and shows node health, round state, missing
peers, finalized rounds and network metrics. The API can be protected with a
dashboard token.

## Trust model

The MVP assumes configured node identities are known before the run. A peer is
trusted only if its public key appears in the trusted-key manifest. Messages from
unknown peers or messages with invalid signatures are rejected.

## Current non-goals

- It is not a production blockchain.
- It does not yet provide a multi-tenant SaaS control plane.
- It does not replace TLS/mTLS or secret management.
- The current networked masking mode is a simulation, not final secure aggregation.
