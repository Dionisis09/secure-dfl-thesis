# Prepared trusted simulator50 — 7 November 2026

This is a trusted single-process simulator, with real TenSEAL CKKS and
reproducible simple/pairwise masking. The trainer holds plaintext models and
private keys. It does not claim independent-client isolation or protection
against that trainer. Read `docs/SIMULATOR50_TRUSTED_PLAN.md` before comparing
these timings to the separate proved/independent-client protocol.

Eight functional/regression tests pass: model/head budgets, actual five-mode
CKKS/masking reconstruction, integer counters, exact checkpoint continuation,
completed no-op/damaged-result refusal, persistent deadline, expired-job stop,
whole-bundle budget selection and cache-tamper detection. Model counts are
recorded in `model_cards.json`; equal parameter budgets do not imply equal FLOPs.

Public calibration folders contain only verified receipts/metadata/two-round
metrics from full-data CIFAR runs with50clients and seed0. These cost/functional
checks are not thesis accuracy measurements, not three-seed scientific results,
and not replay substitutes for the main runs. Each main method will train its
own complete trajectory and execute its actual protection operations every round.

`verification_summary.json` records actual calibrated/selected counts and the
conservative admission forecast. The468-job candidate design is larger than the
selected scope. `selected_plan.json` in the pack lists complete paired-model,
three-seed comparison bundles. Optional graphs without a measured calibration
or bundles exceeding the budget remain excluded. No main jobs were started in
this preparation task. All final groups require seeds1/2/3 for mean/sample SD.

The five-day clock starts at calibration, never resets on resume, and reserves
24hours beyond the admitted96-hour compute plan. Forecasts use2x measured CIFAR
stages, and1.5x CIFAR for grayscale. They are planning assumptions, not a promise
of completion or equivalent hardware performance. CUDA failure never falls back
silently to CPU. Checkpoints/datasets/private CKKS keys are not published.

Times are recorded stages on the laptop RTX5070, separate from previous server
and legacy-campaign profiles. Communication is calculated payload accounting,
including actual serialized CKKS sizes, not measured physical network traffic.
Original402/228 runs, thesis/PowerPoint/dashboard and proved protocol code/results
are preserved unchanged.

Prepared scope: **30 verified calibration jobs**, **438 selected main runs**, main started **0**. Conservative forecast **73.58h**, including the2× admission factor;24h reserve and120h maximum clock. Full graph candidates remain unselected without calibration.

| Topology / method | CNN two-round recorded stages(s) | MLP two-round recorded stages(s) |
|---|---:|---:|
|ring / none|58.65|26.04|
|ring / masking|57.76|25.90|
|ring / pairwise_masking|58.30|27.78|
|ring / selective_he|67.74|36.92|
|ring / adaptive_hybrid|69.27|38.78|
|barabasi_albert / none|56.31|24.89|
|barabasi_albert / masking|57.67|27.11|
|barabasi_albert / pairwise_masking|66.12|35.78|
|barabasi_albert / selective_he|68.88|37.44|
|barabasi_albert / adaptive_hybrid|78.24|46.88|
|caveman / none|57.13|26.04|
|caveman / masking|65.99|32.51|
|caveman / pairwise_masking|253.47|230.27|
|caveman / selective_he|79.62|45.72|
|caveman / adaptive_hybrid|268.85|241.86|
