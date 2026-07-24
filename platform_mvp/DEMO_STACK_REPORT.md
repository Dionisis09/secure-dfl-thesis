# Secure DFL Platform MVP - Demo Stack Report

## Purpose

The demo stack was added to provide a single reproducible command that launches
the Secure DFL platform locally and produces evidence of a completed run.

## Evidence generated

The stack writes a result package with:

- deployment keys and trusted public-key manifest
- per-node runtime directories
- per-node signed audit logs
- dashboard snapshot
- audit verification report
- human-readable demo stack report
- overall summary JSON

## What the demo proves

The demo proves that the platform can:

1. create independent node identities,
2. launch multiple decentralized nodes,
3. exchange signed model-state updates,
4. finalize decentralized rounds,
5. expose operator visibility through a dashboard,
6. verify the integrity of node audit logs after the run.

When `--security-mode masking` is enabled, the demo also proves that the network
can carry masked model-state payloads, unmask them at the receiver and account
for masking overhead in node metrics.

## How to reproduce

```text
..\.venv\Scripts\python.exe demo_stack.py --experiment-id reproducible_demo --rounds 3 --keep-alive-seconds 0
```

Masking mode:

```text
..\.venv\Scripts\python.exe demo_stack.py --experiment-id reproducible_masking_demo --rounds 3 --security-mode masking --keep-alive-seconds 0
```

The output is written under:

```text
platform_mvp/results/demo_stack/reproducible_demo/
```
