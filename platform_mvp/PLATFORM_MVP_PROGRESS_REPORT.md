# Secure DFL Platform MVP - Progress Report

## Summary

The platform MVP extends the thesis prototype from an offline experimental
pipeline into a small networked Secure Decentralized Federated Learning control
plane. It keeps the original thesis code separate and adds a product-oriented
runtime for independent nodes, signed model-state exchange, auditability,
operator visibility and reproducible demonstrations.

## Implemented capabilities

- Independent HTTP node agents.
- Ed25519 node identities.
- Trusted public-key manifest support.
- Signed model-update envelopes.
- Safe NumPy NPZ model-state transport without pickle loading.
- Decentralized neighborhood aggregation.
- Dropout-tolerant quorum finalization.
- Token-protected operator dashboard.
- Per-node signed append-only audit logs.
- Audit-log verifier for hash-chain and signature checks.
- Audit tampering demonstration.
- One-command local demo stack.
- Networked masking simulation with overhead metrics.
- PyTorch/MNIST network training demo.
- Release bundle generation.
- Deployment `.env.example` templates.
- Compact platform validation matrix.
- Docker real-key compose demo.
- Pairwise masking mode with target-specific mask cancellation.
- One-click Docker real-key evidence export script.

## Security and audit features

Each node owns a private Ed25519 key and signs outgoing model-state envelopes.
Receivers verify sender identity, experiment id, recipient id, payload hash and
signature before accepting an update. Each node also writes signed audit records
linked through a hash chain. The verifier can detect post-run tampering by
recomputing record hashes and checking signatures.

## Masking mode

The platform supports `DFL_SECURITY_MODE=masking`. In this mode, outgoing model
states are additively masked before transport and reconstructed by the receiver
before aggregation. The implementation records masked update counts and masking
overhead bytes.

This is currently a controlled masking simulation. It demonstrates the workflow
and overhead accounting but is not yet a full cryptographic secure aggregation
protocol.

## Pairwise masking mode

The platform also supports `DFL_SECURITY_MODE=pairwise_masking`. In this mode,
raw masks are not sent in the envelope. Each contributor derives
target-specific pairwise masks, sends a masked payload and the masks cancel only
when the target node finalizes over the complete contributor set.

## Demonstration commands

Baseline product demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --keep-alive-seconds 120
```

Masking product demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode masking --keep-alive-seconds 120
```

Pairwise masking product demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode pairwise_masking --keep-alive-seconds 120
```

Docker real-key evidence demo:

```powershell
.\run_docker_real_key_demo.ps1
```

Validation matrix:

```text
..\.venv\Scripts\python.exe run_platform_validation.py
```

Release bundle:

```text
..\.venv\Scripts\python.exe make_release_bundle.py
```

## Latest validation evidence

The compact validation matrix currently checks:

1. unit tests,
2. Docker real-key compose config validation,
3. baseline demo stack,
4. masking demo stack,
5. pairwise masking demo stack,
6. masking plus quorum demo stack,
7. audit tamper detection,
8. baseline-vs-masking comparison.

The latest local validation run passed all checks.

## Current limitations

- The dashboard token is suitable for local/product demonstration, not full
  enterprise authentication.
- TLS/mTLS is configurable in the node server but not yet packaged as the
  default demo path.
- Controlled masking is a simulation. Pairwise masking improves this by avoiding
  raw mask transport, but it currently requires a complete contributor set.
- There is no persistent external database or multi-tenant SaaS layer yet.

## Recommended next step

The next major engineering step is dropout-aware pairwise masking and external
audit anchoring.
