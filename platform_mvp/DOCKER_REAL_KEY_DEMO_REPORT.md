# Docker Real-Key Demo Report

## Purpose

The Docker real-key demo provides a reproducible deployment-oriented demonstration of the Secure DFL platform layer. It is intended to show that the prototype is not limited to local in-process simulations: it can run as multiple independent services with mounted cryptographic identities, signed peer communication, dashboard visibility and audit-log verification.

## Architecture

The demo starts the following services:

- `keygen`: generates Ed25519 private keys and a trusted public-key manifest.
- `node0`, `node1`, `node2`: independent Secure DFL nodes.
- `dashboard`: operator dashboard for live status and metrics.
- `demo`: orchestrates decentralized communication rounds without aggregating centrally.
- `audit_verifier`: verifies signed per-node audit logs after the run.

The nodes communicate over HTTP inside the Docker network. Each node loads its own private key from the Docker key volume and verifies peers against `trusted_keys.json`.

## Security mode

The default Docker real-key demo uses:

```text
DFL_SECURITY_MODE=pairwise_masking
```

In this mode, each transmitted model-state payload is masked for a specific target aggregate. Raw masks are not transported. During finalization, the target node adds its own target-specific local mask and aggregates the masked contributor states. The deterministic pairwise masks cancel over the complete contributor set, producing a valid aggregate.

This is stronger than the earlier controlled `masking` mode, where the mask was transported to the receiver for reconstruction.

## Evidence generated

The one-click script writes:

```text
results/docker_real_key_demo_latest/
```

Important files:

- `demo_summary.json`
- `audit_verifier_stdout.json`
- `audit_verification.json`
- `node0_audit.jsonl`
- `node1_audit.jsonl`
- `node2_audit.jsonl`
- `docker_ps.txt`
- `docker_logs.txt`
- `README_DEMO_EVIDENCE.md`

## Run command

```powershell
.\run_docker_real_key_demo.ps1
```

Dashboard:

```text
http://localhost:9200?token=docker-dashboard-token
```

Stop and clean the stack:

```powershell
docker-compose -p secure_dfl_real_key_demo -f docker-compose.real-keys.yml down -v --remove-orphans
```

## Limitations

This is still a thesis/product prototype, not a production blockchain or production secure aggregation system.

Current limitations:

- local Docker HTTP transport; production requires TLS or mTLS;
- local Docker volumes; production requires managed secrets and persistent storage policy;
- pairwise masking currently assumes a complete target contributor set;
- dropout-resilient pairwise masking is future work;
- no external audit anchoring yet;
- no production identity lifecycle management.

## Value of this demo

The demo is useful because it connects the research prototype to a deployable software shape:

- independent containerized nodes;
- real generated keys;
- signed decentralized peer exchange;
- pairwise masked transport without raw mask transmission;
- live dashboard;
- reproducible evidence folder;
- machine-verifiable audit logs.
