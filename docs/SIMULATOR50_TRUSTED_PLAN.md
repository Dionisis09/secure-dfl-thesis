# Trusted simulator: matched CNN/MLP, 50 clients, three seeds

This is the legacy experiment **style** with new parameter-budget matched
architectures, a validation fold and resumable execution. Each method trains
its own trajectory and executes its masking/CKKS operations every round.
Learning trajectories are not replaced with replay benchmarks.

## What the experiment establishes

One trusted Python process owns all50 logical clients, plaintext model states,
optimizers and target-specific private CKKS contexts. CKKS encryption, encrypted
addition/scalar averaging, serialization and decryption are real TenSEAL0.3.16
operations. Simple/pairwise masks use reproducible simulation seeds. They provide
numerical/functional comparisons, not secrecy from this trainer. The HE recipient
has a complete secret key and could decrypt individual ciphertexts. There is no
threshold key, client OS isolation, adversarial-aggregator guarantee, range proof,
physical50-machine deployment or measured WAN traffic in this runner.

The separate proved/independent-client prototypes remain preserved. Their
security guarantees, protocol costs and calibration records must not be pooled
with this simulator. Accuracy preservation does not demonstrate equivalent privacy.

## Frozen learning recipe

- Models: residual CNN and parameter-budget matched MLP from `matched_models.py`.
  Counts differ by less than1% at each native input shape. Equal parameter counts
  do not mean equal FLOPs or wall time. Both classifiers have10×256 weights plus
  10 biases:2,570 values, the same HE workload dimension.
- Every selected run:50 clients,20 rounds, one local epoch, batch128, FP32,
  deterministic PyTorch, AdamW lr0.001 and weight decay0.01. Three-round warmup
  then cosine decay to zero over the declared20-round schedule. This is a fixed
  shared recipe, not a claim of individually optimized hyperparameters or80% accuracy.
- Scientific seeds1/2/3. Calibration seed0 is excluded from scientific statistics.
- Official train sets split stratified with seed20261106:54k/6k train/validation
  for MNIST/Fashion-MNIST,45k/5k for CIFAR-10. Official test10k stays separate.
  Normalization uses the training fold only. CIFAR augmentation is random padded
  crop/flip; grayscale has none. Every training sample belongs to one client.
- All clients share a seeded initialization within a run. Dataset/seed/client
  RNG streams and partitions are common across architectures and modes. Full
  training data are used, including calibration; calibration has two rounds only.
- Validation mean client accuracy/loss on a shared set at rounds5/10/15/20.
  The best common validation-round model states are retained privately. Test is
  evaluated only on the final and best-validation states; test accuracy never
  selects the LR, seeds, budget admission or candidate configurations.
- Mixing uses actual self+neighbors, uniform means, floating BN statistics and
  the target's own integer BN counters, matching legacy first-state semantics.
  Local AdamW states persist per client and are not averaged.

The earlier MLP128/SGD runs used different architectures/preprocessing/optimizer
and a different train/test protocol. They remain historical evidence and do not
form controlled MLP-vs-CNN pairs with this series.

## Candidate bundles and measured selection

There are468 **candidate** runs, not468 promised/started/completed runs:

| Priority | Design | Runs |
|---|---|---:|
| Primary | CIFAR-10, ring, IID/shards/Dirichlet0.5;2models×5modes×3seeds |90|
| Dataset checks | Same design on MNIST and Fashion-MNIST |180|
| Topology checks | CIFAR-10, Dirichlet0.5, Caveman/BA/full;2models×5modes×3seeds |90|
| Dirichlet sensitivity | CIFAR-10 ring, alpha0.1/1.0 |60|
| HE-ratio sensitivity | CIFAR-10 ring IID/Dirichlet0.5, ratios0.2/0.6/0.8/1.0 |48|

The12 matching adaptive ratio0.4 validation runs are references for sensitivity,
not duplicates. Caveman uses2 balanced communities and BA uses the legacy
NetworkX initializer withm2. These are simulation graphs, without a minimum
cohort privacy guarantee.

A bundle contains both models, all three seeds and all five methods (30runs),
or both models/three seeds for one optional adaptive ratio (6runs). Entire bundles
are admitted in priority order. The primary90-run comparison must fit, otherwise
the plan is marked insufficient and main execution refuses to start. Optional
bundles can be excluded by cost or lack of a topology-specific calibration.
The candidate grid is never silently shortened in rounds, samples or seed count.

Calibration:2full-data CIFAR rounds for each model/mode/topology requested.
The default is ring (10jobs). Planning sums measured training, aggregation,
checkpoint, validation/test and setup stages. It uses a2× admission factor;
grayscale is estimated at1.5× the measured CIFAR cost. These are explicit planning
assumptions, not a guaranteed ETA. Optional graphs need their own calibration.
No statistical result is used to choose which bundles fit.

## Five-day clock and recovery

The fixed120-hour wall clock starts at the first explicit `calibrate` command.
Planning admits at most96hours and leaves24hours of reserve, also accounting for
time already spent since the clock began. Resume never resets the deadline.
Each calibration invocation is additionally capped at one hour; partial round
checkpoints remain available if this preparation cap expires.

The controller runs one subprocess/job and terminates it at the wall deadline.
Atomic checkpoints include all50 model/AdamW states, each loader/augmentation RNG,
round number, best-validation states and metrics. Resume restores committed
rounds; completed checksummed runs are skipped. A damaged completed archive
blocks automatic retraining. Source, configuration, cache hashes and runtime
drift are rejected. CUDA failure does not silently switch the execution to CPU.

Completed checkpoints are removed only after verified public metrics/metadata
were written. A live checkpoint is about1–2GB; temporary save requires more space.
The controller stops new admissions below16GiB free and requests a round-boundary
pause below12GiB. A `pause.request` in the pack requests a pause; remove it and
the affected job's `pause.request` before explicit continuation. Lock files use
OS locks, so a leftover filename alone is not a running controller.

Incomplete groups retain their actual count and no invented mean/SD. Complete
groups use sample SD(n−1). Runtime profiles are separate. `recorded_job_seconds`
sums recorded execution stages, setup and tests; incomplete recovered timing is
null. Calibration and unit-test accuracies are not thesis performance results.
Paired-model comparison plots require both model groups to be complete; a valid
three-seed result for one model alone does not establish a completed paired bundle.

## Communication and protection accounting

Communication fields are **calculated payload estimates**, not network measurements.
They include floating model states/buffers over directed graph edges. Actual
serialized CKKS ciphertext lengths replace head plaintext bytes on protected
edges. The legacy pairwise32-byte-per-pair seed exchange and simple-mask payload
formulas are modelling assumptions; no such transport exchange occurs here.
Full mask generation/cancellation is actually executed, including the expensive
pairwise loop in dense graphs. No shared-key/deduplicated-target shortcut is used.
Payload estimates exclude public-key/context distribution, protocol framing and
physical transport headers. CKKS context-creation CPU time is recorded in setup.

## Commands

Run from the repository root using the prepared environment:

```powershell
$simPython = '.\.venv\Scripts\python.exe'
$simPack = 'simulator50_pack_20261107'
$simCache = 'data\simulator50-cache'
& $simPython scripts\simulator50_status.py --pack $simPack
# Explicit benchmark only; it does not start seeds1/2/3.
& $simPython scripts\simulator50.py calibrate --pack $simPack --cache $simCache --topologies ring
& $simPython scripts\simulator50.py plan --pack $simPack
# Explicit main start, only after the selected plan is ready.
& $simPython scripts\simulator50.py run --pack $simPack --cache $simCache
& $simPython scripts\simulator50.py summarize --pack $simPack
```

Preparation/reading/building does not launch main jobs. On another machine,
install the pinned requirements, prepare the official cache and recalibrate the
new runtime; do not reuse laptop timings as server timings. Credentials, datasets,
plaintext checkpoints and private CKKS keys are excluded from public delivery.
Create a new named pack with `prepare` and freeze its local cache with
`prepare-data` when moving machines, rather than overwriting the delivered
snapshot/selection. Carry the existing `started_UTC` and `deadline_UTC` forward
for this same five-day campaign; moving machines does not restart its clock.
Live status is calculated from verified receipts by `simulator50_status.py`;
the controller's cached `completed` list is reconciled when its stage exits.
