# Secure DFL Platform MVP - Demo Checklist

## Before the demo

- Run unit tests:

```text
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

- Run automated stack check:

```text
..\.venv\Scripts\python.exe demo_stack.py --experiment-id pre_demo_check --rounds 1 --keep-alive-seconds 0
```

- Or run the compact validation matrix:

```text
..\.venv\Scripts\python.exe run_platform_validation.py
```

## During the demo

- Start the visible demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --keep-alive-seconds 120
```

- Optional masking demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode masking --keep-alive-seconds 120
```

- Optional pairwise masking demo:

```text
..\.venv\Scripts\python.exe demo_stack.py --rounds 3 --security-mode pairwise_masking --keep-alive-seconds 120
```

- Open the printed dashboard URL.
- Point out:
  - online nodes
  - public key ids
  - finalized rounds
  - sent and received update counters
  - masked update counters, if masking mode is enabled
  - audit verification result

## After the demo

- Open the result package under:

```text
platform_mvp/results/demo_stack/<experiment-id>/
```

- Show:
  - `summary.json`
  - `dashboard_snapshot.json`
  - `audit_verification.json`
  - `demo_stack_report.md`
  - `runtime/<node-id>/node_audit.jsonl`

- Optional tamper-evidence check:

```text
..\.venv\Scripts\python.exe tamper_audit_demo.py --runtime-dir results/demo_stack/<experiment-id>/runtime --trusted-keys results/demo_stack/<experiment-id>/deployment_keys/trusted_keys.json
```

- Optional release bundle:

```text
..\.venv\Scripts\python.exe make_release_bundle.py
```

- Optional Docker real-key demo:

```text
.\run_docker_real_key_demo.ps1
```

Evidence is written to `results/docker_real_key_demo_latest/`.

## Fallback command

If the full stack has a port conflict, rerun it. Ports are allocated dynamically.
