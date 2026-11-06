# Prepared v8 package — verification, not a completed scientific campaign

Prepared on 6 November 2026. The frozen scope has **3,110 planned jobs**, all
with **50 clients**. Scientific evaluation uses seeds **1/2/3**; calibration and
tuning are separate. **Zero scientific jobs in this new campaign have started.**
The [package guide](../../docs/GPU_EXPERIMENT_PACK_50C_3SEEDS.md) defines settings,
privacy boundaries, runtime gates, recovery, retention and reporting.

## Checks on the frozen source

| Evidence | Verified scope |
|---|---|
| `unit_pack.txt` | 15 tests: grid, graphs, data folds, model budgets, envelope binding, bounded RPC audit, real native per-mode sessions |
| `unit_protocol.txt` | 27 existing cryptographic regression tests, native backend required |
| `unit_isolation.txt` | 8 existing Linux boundary tests |
| `frozen_deploy50.json` | 50 client services, coordinator boundary/denial probes; no training |
| `frozen_mlp_gpu.json` | 3 clients, actual GPU MLP, two rounds, hybrid pairwise/head HE |
| `frozen_cnn_gpu.json` | 3 clients, actual GPU CNN, one round, hybrid pairwise/head HE |
| `frozen_caveman.json` | 8 clients, CNN, Caveman, CPU plaintext/fixed-point ablation |
| `frozen_barabasi.json` | 6 clients, MLP, Fashion-MNIST, BA/K3, CPU pairwise masking |

The trusted test auditor independently recomputes the actual local training and
every self-and-neighbor quantized model average. Full-state hashes and protected
mean validation metrics match exactly. Best checkpoints and completed-job no-op
resume are checked. The auditor is outside the deployed coordinator boundary;
its privileged test access is not a trainer capability. All fixture services
are stopped. These tiny fixtures establish functional integration, not scientific
accuracy, throughput, full-grid completion or a completed 50-client GPU gate.

`verification_summary.json` and `checksums.json` identify the evidence. The
source hash matches `experiment_pack_50c_3seeds_v8/source_snapshot.json`.
`preflight.json` in that folder records a successful RTX 4090 CUDA tensor check
after the server reboot; it is not a full training calibration. Official dataset
fold/cache hashes are in `data_snapshot.json`. No private model, dataset, TLS
credential, SSH credential or role configuration is published here.

## Pending before bulk execution

Run the two actual 50-client GPU gates, then 12 mode smokes and 36 validation-only
tuning jobs. Review measured cost and the controller's budget guard before the
main grid. The full-peer proof verification/opaque relay can dominate GPU compute;
no full-campaign duration is inferred from tiny correctness fixtures.

The same-host host administrator/provisioner, kernel/drivers and software supply
chain remain trusted. No claim of arbitrary-collusion resistance, malicious
backbone range checks, DP, poisoning defense, multi-host isolation or independent
production-security certification is made. Original 402 runs, selected 228 runs,
old paused campaigns and their documents/charts are unchanged and are not merged
with this new package's measurements.
