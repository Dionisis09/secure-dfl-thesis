# Secure DFL Platform MVP - Product Demo Guide

This guide explains how to demonstrate the platform as a working secure
decentralized learning prototype.

## Demo goal

Show that the project is no longer only an offline thesis experiment. It can run
as a small local network of independent nodes with signed communication,
deployment keys, an operator dashboard, audit logs and post-run verification.

## Recommended command

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --keep-alive-seconds 120
```

Open the printed dashboard URL. It includes a temporary token.

## What to show

1. The dashboard shows three online nodes.
2. Each node has its own public key id and peer list.
3. Rounds move from empty state to finalized state.
4. Network metrics increase after every signed exchange.
5. The result package contains `summary.json`, `audit_verification.json`,
   generated keys and per-node audit logs.

## Optional masking demo

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode masking --keep-alive-seconds 120
```

This demonstrates masked model-state transport and exposes masked update counts
and masking overhead in the dashboard and result package.

## Comparison output

After running a baseline stack and a masking stack, compare them with:

```text
..\.venv\Scripts\python.exe compare_demo_stack_results.py results/demo_stack/<baseline-run> results/demo_stack/<masking-run>
```

Use the generated CSV/Markdown to discuss overhead and audit evidence.

## Tamper evidence

After a demo stack run, execute:

```text
..\.venv\Scripts\python.exe tamper_audit_demo.py --runtime-dir results/demo_stack/<run>/runtime --trusted-keys results/demo_stack/<run>/deployment_keys/trusted_keys.json
```

This copies one audit log, tampers with a record and shows that verification
fails. It is a simple way to demonstrate integrity protection.

## Sharing the MVP

Use:

```text
..\.venv\Scripts\python.exe make_release_bundle.py
```

The generated zip excludes runtime artifacts, generated result folders,
deployment private keys and Python cache files.

## Main message

The prototype demonstrates a deployable Secure DFL control plane: clients remain
decentralized, model-state exchanges are signed, every node maintains an
append-only audit log, and the operator can verify the run after completion.

## Important limitation

This MVP is a local product prototype. It is not yet a production SaaS service.
Production deployment would require hardened authentication, TLS/mTLS by
default, secret management, persistent databases, monitoring and operational
packaging.
