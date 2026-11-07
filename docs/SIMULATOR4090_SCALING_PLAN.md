# RTX4090 scaling pack — prepared7November2026

## Scientific comparison

The new pack extends the trusted simulator with **20/50/100 logical clients**.
The scaling comparison is fixed in advance:

| Dimension | Fixed setting |
|---|---|
| Dataset | Full CIFAR-10;45,000train /5,000validation /10,000test |
| Models | CNN and parameter-budget matched MLP; same2570-value classifier |
| Distribution | Conditioned Dirichlet alpha0.5, minimum10samples/client |
| Topology | Ring; each client exchanges with two neighbors |
| Methods | Plain baseline (`none`) and adaptive hybrid (`adaptive_hybrid`) |
| Independent seeds |1,2,3; calibration seed0 is excluded |
| Training |20rounds,1local epoch, batch128, AdamW0.001, weight decay0.01 |
| Scheduler |3round warmup then cosine; deterministic FP32 |
| Adaptive rule | Existing update-norm policy, HE target ratio0.4 |
| Protection | Actual CKKS classifier aggregation; pairwise masking in hybrid |
| Evaluation | Validation5/10/15/20; final and best-validation tests, no test tuning |

There are **36 scientific scaling cases**:3counts ×2models ×2methods ×3seeds.
The **12 cases at50clients reference existing primary CIFAR/ring/Dirichlet
jobs**; they are not rerun as duplicate scaling jobs. The24new jobs at20/100
form one atomic required bundle. The full candidate pack has492unique jobs;
this is a candidate pool, not a claim that all492fit or have run.

The three primary CIFAR bundles (IID/shards/Dirichlet0.5, both models, five
methods, three seeds) plus scaling are mandatory: **114unique jobs**. Optional
grayscale/topology/alpha/sensitivity bundles are admitted in manifest order only
when measured cost fits. Each method trains its own complete trajectory. There
is no replay substitution, subset reduction, fewer rounds or dropped seeds.

## Meaning and limits

This is fixed-total-data scaling in a **single-process, single-GPU simulator**.
Average training samples/client are2250/900/450 respectively. The partition
changes with client count, so an accuracy change reflects both the amount and
distribution of local data and slower information propagation around a longer
ring. It is not a benchmark of20/50/100physical GPU machines or distributed
throughput. Parameter matching does not imply equal FLOPs or training time.

As in the approved original-style experiment, the trainer can inspect plaintext
models and private CKKS keys. This package measures learning utility and actual
operation cost under that trusted-trainer assumption. It does not establish
independent-client privacy, malicious-client resistance, threshold decryption
or measured WAN traffic. The separate proved/isolated protocol is preserved.

## One shared five-day budget

The original clock is inherited, never restarted on migration/resume:

- Start: **2026-11-07T11:35:56.126814+00:00**.
- Hard deadline: **2026-11-12T11:35:56.126814+00:00** (13:35Athens).
- Maximum admitted estimate: `min(96h, deadline-now-24h)`.
-24hours are reserved inside the120hour window, not added after it.

Only a real RTX4090-family CUDA device with at least20GiB VRAM is accepted.
RTX5070 laptop timings and the previous laptop selection are not imported.
GPU downtime/setup also use the inherited window. No five-day completion ETA
is asserted before actual calibration. If the mandatory114jobs do not fit,
`plan` produces `admission_blocked.json` and refuses bulk execution. Additional
calibration can then be collected and planning retried; a ready selection is
frozen. The controller stops before the deadline, retaining atomic checkpoints;
it never relabels unfinished groups as completed. It skips verified completed
jobs and rejects changed source/data/runtime archives rather than rerunning them.

The calibration grid uses full CIFAR-10/Dirichlet0.5, seed0, two rounds:

-50clients: both models ×5methods for each calibrated topology.
-20and100clients: both models ×baseline/adaptive for ring,8extra calibrations.
- Default ring/Caveman/Barabasi calibration: **38jobs**; ring alone: **18jobs**.
- Each calibration command has at most1hour within the same global clock;
  rerun it explicitly to resume unfinished calibrations if needed.

Predictions use client-count-specific measured setup/train/aggregation/evaluation/
checkpoint costs with a2× admission factor. No50-to100 timing extrapolation is
permitted. Grayscale optional costs use1.5× CIFAR as a planning assumption.
Dense graphs still require their own calibration; cryptography and masking also
use CPU, so a faster GPU alone is not evidence of a matching overall speedup.

## Transfer and launch later

No server training, installation or upload was started during preparation.
Use the allowlisted source ZIP and its separate exact-cache ZIP from the final
local output folder. Extract both in the same new server directory. The cache
archive contains `data/simulator50-cache/`; do not substitute another fold/cache
for the frozen receipt. Datasets, keys and checkpoints are excluded from Git.

On the server, from that extracted root:

```bash
bash scripts/simulator4090.sh setup
bash scripts/simulator4090.sh check
bash scripts/simulator4090.sh calibrate
bash scripts/simulator4090.sh plan
# Inspect selected_plan.json: status must be ready, required bundles included.
bash scripts/simulator4090.sh run
bash scripts/simulator4090.sh status
bash scripts/simulator4090.sh summarize
```

`setup` creates an isolated Python3.12 environment via the available Anaconda
or python3.12, leaving the old benchmark environment untouched. `check` verifies
CUDA/real CKKS and exact caches without training. GPU failure never falls back
to CPU. Keep at least16GiB free for a new job; low disk requests a checkpointed
pause. `pause` finishes the current round; `clear-pause` clears only pause flags
and does not start training. Use `run` explicitly afterward; the deadline and
completed receipts remain unchanged. For a disconnected SSH session use the
site's session manager, e.g. tmux if installed, without creating a second runner.

`summary.json` separates client count, model, distribution, mode, source, cache
and runtime. `scaling_summary.json` reuses the50client references, exposes all36
required cases, and calculates **mean/sample SD only for complete seeds1/2/3**.
It includes final accuracy/loss, recorded stage time and validation curves.
Incomplete/missing groups receive no synthetic statistics. Original402/228runs,
PowerPoint, Word and dashboard remain unchanged until actual new results exist.

## Verification scope

Sixteen tests cover the original simulator and new scaling controls, including
an actual100-logical-client2570-value CKKS head arithmetic fixture, exact resume,
seed completeness, disjoint partition coverage at20/50/100, provenance/target
rejection, mandatory-bundle admission and reporting without pooled client counts.
The100client arithmetic fixture shares one real context to bound test memory;
the training engine creates distinct per-target contexts. These tests are not
a full100model GPU training/memory/performance benchmark. That gate remains
pending on the repaired4090; no new accuracy results are claimed.

The earlier50client frozen manifest/receipts remain historical. Their archived
source ZIP and Git commit `df9aa08` reproduce their original source snapshot;
do not resume that old pack with this changed computational source.
