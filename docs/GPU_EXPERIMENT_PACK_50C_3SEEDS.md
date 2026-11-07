# GPU experiment pack — 50 clients, seeds 1/2/3

**7 November correction:** use the separately frozen
`experiment_pack_50c_3seeds_v8_1` supervisor revision. The original calibration
completed CNN rounds at106.4minutes/round; its MLP detailed receipt was lost in
an archive-path collision. [Measured evidence and incident](../results/calibration_50c_20261107/README.md)
explain the limitations. The full grid is not practical at the measured cost.
No bulk run is recommended before redesign/optimization. The original v8 folder
is historical and blocked for archive review; it must not be refrozen in place.

Prepared on 6 November 2026. **Building, uploading or opening the package does
not start experiments.** The GPU has reappeared after a server reboot. An explicit
`run` command starts the mandatory calibration stage; the scientific campaign
has not been run as part of preparing this package.

## Frozen scope

| Stage | Unique jobs | Seeds / purpose |
|---|---:|---|
| Dense GPU/protocol gates | 2 | Seed0; MLP/CNN, 50 clients, 2 rounds, full batch128 |
| Six-mode smoke checks | 12 | Seed0; 2 models ×6 modes, 50-client ring, 2 rounds |
| Equal-budget LR tuning | 36 | Seed7; 3 datasets ×2 models ×2 splits ×3 LRs |
| Main validation | 2,160 | 3 datasets ×2 models ×4 graphs ×5 distributions ×6 modes ×3 seeds |
| Extra sensitivity | 360 | HE ratios0.2/0.6/0.8/1.0 on the ring |
| Network demos | 540 | All datasets/models/distributions/modes, 3 seeds, 50 clients |
| **Total unique jobs** | **3,110** | **All jobs use50 clients** |

Sensitivity has450 points: its90 ratio0.4 points reference matching completed
main jobs, rather than being run/counting twice. Scientific evaluation seeds
are1/2/3. Calibration seed0 and tuning seed7 are separate, never additional
statistical replicates. The original402 runs, selected228 extension, older
paused campaign and earlier CNN pilots are not reused as v8 measurements.

- Datasets: MNIST, Fashion-MNIST, CIFAR-10, with native input shapes.
- Models: parameter-budget matched MLP and residual CNN, common2570-value head.
- Graphs: ring, fully connected, connected Caveman with2 balanced communities,
  Barabási–Albert withm2 and an initial completeK3 graph.
- Distributions: IID,2 sorted-label shards/client, Dirichlet alpha0.1/0.5/1.0.
- Modes: `none`, `masking`, `pairwise_masking`, `selective_he`,
  `hybrid_pairwise_head_he`, `adaptive_hybrid`.

The BA initializer is explicit and differs from the legacy NetworkX default
star. The star can leave a degree-one vertex (including seed2 atN50), giving a
two-member averaging cohort that reveals the other member's input. Starting
fromK3 preserves the standard preferential-attachment construction while keeping
minimum degree2. Legacy graph/results code is unchanged. No cohort has fewer
than3 members. This does not establish resistance to arbitrary collusion.

## Scientific training protocol

Main and tuning runs use60 rounds, one local epoch, batch128, AdamW, weight
decay0.01, a5-round linear warmup followed by cosine LR decay, FP32 and
deterministic PyTorch algorithms. Both models use the same preprocessing and
per-dataset/seed/client loader and augmentation stream. Crypto randomness is
independent of those reproducibility seeds.

Official train sets are split once, stratified with seed20261106:
MNIST/Fashion54,000 train +6,000 validation; CIFAR45,000 +5,000. Official test sets
remain separate. Normalization moments come only from the training fold. CIFAR
uses padded random crops and horizontal flips; grayscale datasets have no flips.
Each training sample belongs to exactly one client. Dirichlet can have both class
and quantity skew, with minimum10 samples/client and bounded whole-draw retries.

Validation is scheduled at rounds5,10,...,60. Test evaluation is permitted only
at the end, on the common last round and the best global-validation round. The
primary accuracy/loss is **mean client accuracy/loss on the shared evaluation
set**, not accuracy of a model reconstructed by the coordinator. Local optimizer
states persist in their own clients and are not averaged.

Learning rates0.0003/0.001/0.003 receive equal tuning budgets. The selection uses
mean best scheduled validation accuracy across IID and shards, with a smaller-LR
tie-break. Tuning never evaluates the test set. One selected LR per model/dataset
is frozen and hashed before main modes/graphs/seeds. The manifest therefore pins
a validation-only LR reference; effective main configs also pin the selected
artifact hash. No test-driven or mid-grid hyperparameter changes are allowed.

Network demos use2 rounds,1500 total training and500 evaluation images, still
with50 clients. Their Dirichlet minimum is2 samples/client: conditioning all50
clients on at least10 samples in such a small, strongly skewed demo is generally
infeasible within the retry budget. This is a separate scope, never pooled with
full-data validation or interpreted as a WAN experiment.

## Coordinator privacy and modes

The coordinator only routes signed E2E-encrypted peer messages. Every client
computes its own actual self-and-neighbor model average. Per-neighborhood model
outputs stay inside clients; releasing all such averages to a coordinator could
permit linear-system reconstruction, for example on a50-node ring. The public
output is the protected mean of evaluation metrics and signed model hashes.
There is no local-model export, arbitrary evaluation-query or remote-loading API.

All modes use the same authenticated E2E transport; it is transport overhead,
not evidence that a plaintext application ablation provides secure aggregation.

| Mode | Application backbone | Application head | Peer-privacy interpretation |
|---|---|---|---|
| none | Same fixed-point plaintext mean | Same | Peers can read inputs; baseline ablation |
| masking | Legacy public-seed additive masks | Same | Public masks are reversible; explicitly insecure ablation |
| pairwise_masking | Secret pairwise field masks | Same | Reveals authorized cohort aggregate |
| selective_he | Plaintext ablation | Joint-key HE + mandatory proofs | Backbone exposed to peers |
| hybrid_pairwise_head_he | Secret pairwise masks | Joint-key HE + mandatory proofs | Protected full floating state |
| adaptive_hybrid | Secret pairwise masks | HE for selected target cohorts, otherwise pairwise | Protected full floating state |

All means use the same fixed-point recipe (scale65536), including the baseline,
to isolate the crypto representation from precision differences. No silent
clipping is performed. Head absolute values are bounded at2; floating backbone
values at32. The HE head uses the v6 two-sided Bulletproofs, linked ciphertext
knowledge proofs, verified joint-key shares and collective decryption approvals.
Backbone masking has no malicious-input range proof. No DP, poisoning defense,
arbitrary-collusion or independent production-security certification is claimed.

Adaptive target selection is a frozen **public graph-degree exposure proxy**,
with seeded tie-breaking; it is not a learned private-data risk estimator.
Requested ratios0.2/0.4/0.6/0.8/1.0 select10/20/30/40/50 logical targets. Identical
roster/mode groups can share one validated aggregate. Records distinguish logical
HE targets, unique groups, native ciphertext/proof bytes and actual serialized
RPC JSON bytes. A fully connected adaptive run may need two canonical groups,
where a fixed hybrid needs one; no automatic speed-saving claim is made.

RPC audit memory is bounded: aggregate counts/totals are retained by enrolled
client/operation/status, with only the first100 call metadata records as samples.
Full model payloads are not logged. This avoids retaining millions of individual
RPC dictionaries during a long50-client job; legacy v7 logging defaults remain
unchanged.

Linux roles use Landlock, seccomp, disabled core dumps and non-dumpable memory.
The coordinator cannot open client files/memory, execute programs or use Unix
control-plane sockets. Clients may execute only the fixed read-only Python/ELF
interpreter to replace their own process with a private GPU worker, then return
to their CPU service. All non-standard FDs are close-on-exec. Only one training
worker uses the GPU at a time;50 permanent CUDA contexts are not created.

CUDA additionally needs read-only public driver metadata, writes to its own
task-thread names and an NVIDIA SEQPACKET FD. Those permissions are GPU-client
only; Unix STREAM/DGRAM, socketpair and outbound `connect()` remain blocked
there. The coordinator has none of the GPU permissions. Host administrator,
trusted provisioning, drivers/kernel and supply chain remain outside the
boundary. This is a same-host simulation of independent services, not physical
multi-host or GPU side-channel certification. Known v6 dependency advisories
remain documented; the pinned profile is a research profile, not a clean
production dependency audit.

## Run the prepared package

The prepared server workspace is `~/secure-dfl-gpu-pack`. Its existing research
environment is `~/.venvs/secure-dfl-bench`. For a new machine install the pinned
`requirements-protocol-v8.txt`, using official PyTorch CUDA wheels, and build:

```bash
cargo build --release --locked --manifest-path native/dfl_range/Cargo.toml -j2
export DFL_RANGE_LIB="$PWD/native/dfl_range/target/release/libdfl_range.so"
```

The server already has the validated v6 native library. Start with:

```bash
cd ~/secure-dfl-gpu-pack
export DFL_RANGE_LIB="$HOME/secure-dfl-protocol-v6/native/dfl_range/target/release/libdfl_range.so"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 CUBLAS_WORKSPACE_CONFIG=:4096:8
PY="$HOME/.venvs/secure-dfl-bench/bin/python"
PACK=experiment_pack_50c_3seeds_v8_1

"$PY" scripts/pack_campaign.py status --pack "$PACK"
"$PY" scripts/pack_campaign.py preflight --pack "$PACK"
# Explicit first execution: only the two50-client GPU gates.
"$PY" scripts/pack_campaign.py run --pack "$PACK" \
  --work-root "$PWD/private-campaign" --data-cache "$PWD/data-cache" --until gpu_gate
```

Then continue the same controller with `--until smoke`, `--until tuning`, and
finally `--until network` to include all stages. Default continuation stops at
the GPU gates, never silently launching3,110 jobs. Before main validation, a
conservative measured calibration budget is checked before any non-gate stage against
`--max-estimated-hours` (default168). An exceeded budget stops with jobs pending;
it is not permission to truncate rounds/seeds or claim a trustworthy fixed ETA.
Choose any larger budget deliberately after reviewing calibration.

For a fresh data cache, `prepare-data --cache data-cache` downloads/checks official
sources, and `freeze-data --pack "$PACK" --cache data-cache` pins fold/file hashes.
The delivered server cache already contains all three datasets. Data/source/
runtime drift aborts. Runtime is frozen at the first successful calibration.

## Recovery, retention and reporting

One controller lock and one supervisor lock prevent duplicate writers. Completed
job receipts/checksums are verified and skipped on resume. Private client model,
AdamW, loader and RNG checkpoints persist across committed rounds. Commit intent
is fsynced before distributed commit; saved intents can be retried idempotently.
An interrupted crypto phase before durable commit readiness fails closed and
requires review; it is not retrained/rekeyed automatically. There is no plaintext
fallback. A pause request is honored after a complete round.

The supervisor requires at least48GiB available host RAM and20GiB free disk before
a job. It requests a round-boundary pause below12GiB free. Each job is bounded to
7 days; TLS credentials last14 days and are refreshed by the trusted supervisor
before launching a paused job if necessary. No running role can renew credentials.

By default, completed *new package* private workspaces are pruned only after all
workers stopped and durable public receipts/config/curves/checksums were copied
and verified. This intentionally retains reproducibility metadata/metrics, not
every client's trained weights/optimizer for thousands of jobs. `--retain-private`
keeps those files and may exhaust storage sooner. Deletion is restricted to an
exact direct-child workspace with a matching ownership marker/job ID. Official
dataset caches and all historical/user project directories are outside cleanup.

```bash
"$PY" scripts/pack_campaign.py summarize --pack "$PACK"
```

Summaries require complete groups of seeds1/2/3 before computing mean and sample
SD (`n-1`, accuracy SD in percentage points). Incomplete groups retain their real
`n` and no invented statistics. Timing profiles are never pooled. Per-round
timings separate the GPU-worker stage, native training, aggregation, evaluation/
reporting and commit; serialized JSON sizes are not NIC/TLS wire-byte measures.
Recovered commit timings are marked incomplete. Earlier results are not mixed.

The package's own verification fixtures are small tests only; their accuracies
must not be added to thesis performance charts. No new campaign, PowerPoint,
Word or dashboard performance results are claimed while its jobs are pending.

The repaired supervisor assigns the archive path inside the current-job loop,
rejects another job's archive before writing, excludes `checksums.json` from its
own hash list, fsyncs evidence and verifies the complete durable journal before
private cleanup. Re-export is idempotent. A recorded completion whose archive
is missing blocks automatic retraining and requires explicit recovery review.
