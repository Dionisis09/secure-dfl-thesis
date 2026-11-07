# 50-client calibration — 7 November 2026

**Bulk execution remains stopped.** The current implementation is too expensive
for the frozen 3,110-job design. These are functional/cost calibrations, not
new thesis accuracy measurements or three-seed scientific results.

| Measurement | CNN, 50 clients |
|---|---:|
| Round 1 | 6,427.68 s (107.13 min) |
| Round 2 | 6,340.19 s (105.67 min) |
| Mean complete round | 6,383.93 s (106.40 min) |
| Mean training-worker stage | 168.18 s |
| Actual GPU training, summed over 50 clients | 19.37 s |
| Mean secure model aggregation | 6,087.26 s (95.35% of total) |
| Mean reporting/evaluation | 126.86 s |
| Mean commit | 1.36 s |
| Complete CNN job including startup/shutdown | 12,774.08 s (3h32m54s) |

Configuration: CIFAR-10, matched residual CNN, 50 clients, fully connected graph,
hybrid pairwise backbone + proved joint-key HE head, seed0, 6,400 training and
500 evaluation images, batch128, one local epoch, two rounds. The GPU is a
working RTX4090; CPU verification and authenticated opaque peer fanout dominate.
Mean serialized request+response JSON is about126.87GB/round (decimal GB),
**not** physical NIC/WAN or TLS wire bytes. The GPU training time is a subset
of the worker stage, which also includes private process replacement/loading.

## What this implies for the full design

A 60-round job at the same measured cost is about106.4h (4.43days). The frozen
design has154,468 rounds across3,110 jobs. Assigning the dense hybrid cost to
every round gives an illustrative31.25years of serial24/7 work. It is not a
full-grid ETA: sparse graphs, plaintext/masking modes and datasets differ, and
full-data training/evaluation are larger than this calibration subset.
`timing_summary.json` also includes an explicitly unvalidated graph-pair-count
scaling scenario (~18years), with its assumptions. Neither scenario justifies
a narrow completion date. They show that the full design needs optimization
and a scope review; a faster GPU alone will not address the measured bottleneck.

Before more long runs, measure representative sparse/mode cases after reducing
redundant routing/verification work while preserving the threat model. A possible
evaluation redesign is to separate baseline learning-utility experiments from
cryptographic cost/replay experiments on frozen updates. Replays must be labelled
as such and must not be presented as independent full secure-training runs.

## Archive incident and recovery

The original controller completed MLP execution and advanced to CNN, but kept
the last manifest job's destination variable. Both gate archives targeted that
same network-job folder. CNN overwrote MLP public files; a self-including hash
list then failed verification. The original MLP private workspace had already
been removed by the retention policy. Its detailed receipt/round timings could
not be recovered. **It is not counted as a verified calibration result.**
The retained controller-state claim and filesystem birth timestamps bracket
an approximate MLP window of3h38m21s, including preflight/provisioning/handoff.
This is not reconstructed round data or accuracy. See `mlp_timing_window.json`.

The intact CNN private journal, public job and original receipt were recovered
into the correct archive, hashed and semantically verified, with private CNN
checkpoints retained. The misplaced archive and original failure/state were
quarantined on the server. No training round or cryptographic release was repeated.
All services/controllers are stopped; original pack state blocks automatic
retraining/recovery because the MLP receipt remains missing.

The corrected supervisor uses a destination per current job, rejects another
job's archive before writes, excludes the checksum file from its own list,
supports idempotent re-export, and validates/fsyncs complete evidence before
private cleanup. A missing recorded completion blocks automatic retraining.
The measured-cost guard now runs before any non-gate stage, including tuning.
All four new Linux regression tests passed (`archive_regression.txt`). No
training/model/cryptographic operation or security threshold was changed.

The corrected source is separately frozen as
`experiment_pack_50c_3seeds_v8_1`; old calibration records retain their original
source/runtime hashes. Earlier402/228 results and Word/PPT/dashboard are unchanged.

## Current GPU availability

At09:00:54UTC on7November, an idle unrestricted check again returned
`nvidia-smi` exit255, unable to determine the GPU device handle (`Unknown Error`),
and a separate PyTorch CUDA preflight failed. See `gpu_status_20261107.txt` and
the corrected package's `preflight.json`. No client/controller was active and no
server reset/reboot was attempted. Cause is undiagnosed; an administrator needs
to restore GPU availability before new runs. The completed CNN records capture
actual CUDA training during their execution; they do not assert current GPU health.
