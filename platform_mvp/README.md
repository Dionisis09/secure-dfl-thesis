# Secure DFL Platform MVP

This folder is the first networked product layer. It is separate from the thesis runner and does not change the existing training pipeline.

Current capabilities:

- Three or more independent node processes.
- Configurable peer topology.
- Ed25519-signed model-state envelopes.
- Trusted peer identities and payload hash verification.
- Deployment key generation and trusted-key manifest support.
- Safe NumPy NPZ transport without pickle loading.
- Decentralized neighborhood aggregation inside each node.
- Optional quorum finalization for dropout-tolerant rounds.
- Health, status, round, metrics and operator APIs.
- Per-node signed append-only audit log.
- Standalone audit-log verifier.
- Lightweight operator web dashboard.
- Optional TLS and mutual TLS configuration.
- Docker Compose demonstration with three nodes.

## Local smoke test

Run from `platform_mvp` with the project virtual environment:

```text
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\.venv\Scripts\python.exe smoke_test.py
```

The smoke test starts three real Python processes, performs three signed decentralized rounds and verifies every neighborhood aggregate.

## Deployment keys

Generate real Ed25519 keys for a deployment:

```text
..\.venv\Scripts\python.exe keygen.py --nodes node0,node1,node2 --output-dir deployment_keys
```

This creates:

```text
deployment_keys/trusted_keys.json
deployment_keys/key_metadata.json
deployment_keys/nodes/node0_private_key.pem
deployment_keys/nodes/node1_private_key.pem
deployment_keys/nodes/node2_private_key.pem
```

For a real node, configure:

```text
DFL_PRIVATE_KEY_FILE=deployment_keys/nodes/node0_private_key.pem
DFL_TRUSTED_KEYS_FILE=deployment_keys/trusted_keys.json
```

Do not commit private keys. Store them with proper filesystem permissions or a
secret manager.

End-to-end real-key demo:

```text
..\.venv\Scripts\python.exe real_keys_demo.py
```

This starts three nodes with generated PEM keys, runs signed decentralized rounds
and verifies the resulting audit logs against the trusted-key manifest.

## One-command demo stack

For presentations, run the full local product demo with one command:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --keep-alive-seconds 60
```

This starts real-key nodes, launches the operator dashboard, executes signed
decentralized rounds, verifies audit logs and writes a result package under:

```text
platform_mvp/results/demo_stack/<experiment-id>/
```

The package contains `summary.json`, `dashboard_snapshot.json`,
`audit_verification.json`, `demo_stack_report.md`, `run_commands.txt`,
generated deployment keys and per-node runtime audit logs. Use
`--keep-alive-seconds 0` for an automated non-interactive check. The generated
dashboard URL includes a temporary token.

Masking mode:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode masking --keep-alive-seconds 60
```

Masking mode additively masks outgoing model-state tensors before transport,
then reconstructs them at the receiver before aggregation. This is a controlled
masking simulation for workflow and overhead measurement, not final secure
aggregation.

## Real PyTorch/MNIST network demo

The MVP also includes a practical training demo. It starts independent node
processes, trains one PyTorch client per node, sends signed model states through
the node network, finalizes decentralized aggregates and writes metrics, plots
and per-node audit logs.

Quick run:

```text
..\.venv\Scripts\python.exe mnist_network_demo.py --dataset mnist --num-clients 3 --rounds 2 --topology ring --split-type iid --experiment-id mnist_ring_demo
```

Optional quorum mode:

```text
..\.venv\Scripts\python.exe mnist_network_demo.py --dataset mnist --num-clients 3 --rounds 2 --topology ring --min-peer-updates-to-finalize 1 --experiment-id mnist_quorum_demo
```

Optional masking mode:

```text
..\.venv\Scripts\python.exe mnist_network_demo.py --dataset mnist --num-clients 3 --rounds 2 --topology ring --security-mode masking --experiment-id mnist_masking_demo
```

Fast offline check without downloading MNIST:

```text
..\.venv\Scripts\python.exe mnist_network_demo.py --dataset fake --num-clients 3 --rounds 1 --experiment-id fake_network_check
```

Outputs are stored under:

```text
platform_mvp/results/<experiment-id>/
```

The important files are `metrics.csv`, `summary.json`, `plots/` and
`runtime/<node-id>/node_audit.jsonl`.

## Operator dashboard

Start nodes with Docker Compose or with the Python demos, then run:

```text
..\.venv\Scripts\python.exe operator_dashboard.py --nodes node0=http://localhost:9100,node1=http://localhost:9101,node2=http://localhost:9102 --admin-token local-dashboard-token
```

Open:

```text
http://127.0.0.1:9200?token=local-dashboard-token
```

The dashboard shows online/offline nodes, finalized rounds, quorum/partial
rounds, missing peers and network metrics.

## Dropout-tolerant quorum demo

By default, a node waits for all configured peers before finalizing a round.
For a more realistic network setting, the operator can configure a minimum
number of peer updates with `DFL_MIN_PEER_UPDATES_TO_FINALIZE`.

Run the dropout demo:

```text
..\.venv\Scripts\python.exe dropout_demo.py
```

This starts only `node0` and `node1`, while `node2` is configured but offline.
Because the minimum peer update count is set to 1, the live nodes finalize using
their local state plus the one received signed peer update. The audit log marks
the round as a partial finalization and records the missing peer.

## Audit verification

Verify node audit logs after a run:

```text
..\.venv\Scripts\python.exe verify_audit_logs.py --runtime-dir results/mnist_ring_demo/runtime --trusted-keys deployment_keys/trusted_keys.json --output results/mnist_ring_demo/audit_verification.json
```

The verifier checks record hashes, hash-chain continuity, Ed25519 signatures and
public-key ids.

If `--trusted-keys` is omitted, the verifier uses the public key recorded in the
node's `node_started` audit entry. That mode is convenient for demos; a real
deployment should verify against an external trusted-key manifest.

Tamper-detection demo:

```text
..\.venv\Scripts\python.exe tamper_audit_demo.py --runtime-dir results/demo_stack/masking_report_check_3/runtime --trusted-keys results/demo_stack/masking_report_check_3/deployment_keys/trusted_keys.json
```

The script copies one audit log, modifies a record and expects verification to
fail.

## Comparing demo stack runs

```text
..\.venv\Scripts\python.exe compare_demo_stack_results.py results/demo_stack/baseline_after_masking_check results/demo_stack/masking_report_check_3
```

This writes:

```text
results/demo_stack/comparison/demo_stack_comparison.csv
results/demo_stack/comparison/demo_stack_comparison.md
```

## Release bundle

Create a clean zip without generated results, runtime files, private keys or
Python caches:

```text
..\.venv\Scripts\python.exe make_release_bundle.py
```

The bundle is written under:

```text
platform_mvp/results/release/
```

## Deployment examples

Example environment files are available under:

```text
platform_mvp/deployment_examples/
```

They show how to configure three nodes, real key files, trusted public keys,
security mode, quorum threshold and dashboard token settings.

## Platform validation matrix

Run a compact validation matrix:

```text
..\.venv\Scripts\python.exe run_platform_validation.py
```

It executes unit tests, baseline demo stack, masking demo stack, quorum masking
demo stack, audit tamper detection and baseline-vs-masking comparison. Results
are written under:

```text
platform_mvp/results/platform_validation/
```

## Docker demonstration

```text
docker-compose up --build --exit-code-from demo
```

If Docker Compose v2 is installed, the equivalent command is
`docker compose up --build --exit-code-from demo`.

Node dashboards are available at:

```text
http://localhost:9100
http://localhost:9101
http://localhost:9102
```

Stop the demo with `docker-compose down`. Add `-v` only when the stored node audit volumes should also be removed.

## Security note

Docker Compose uses deterministic development identities and HTTP to keep the local demo reproducible. A real deployment must use mounted Ed25519 keys, a trusted public-key manifest, unique admin credentials, TLS or mTLS, secret management and external audit anchoring.

## Next milestone

The next implementation step is adding networked masking / secure aggregation to the platform layer.
