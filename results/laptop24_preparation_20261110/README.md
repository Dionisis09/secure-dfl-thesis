# Laptop24 preparation — 10 November 2026

**22/22 actual full-data calibration jobs and23unit/regression tests passed.**
GPU: RTX5070Laptop8GB, driver621.14. Main scientific jobs started:0.
Prepared selection: **144 /144candidate jobs**,
with a conservative **12.91h** forecast
including the2x admission factor. The4h reserve is inside the24h wall limit.
This forecast is measured-stage planning, not a guaranteed completion time.

Scientific groups use seeds1/2/3,20rounds and full datasets. Calibration seed0
uses two full-data CIFAR/Dirichlet0.5 rounds and is excluded from statistics.
20clients form the primary comparison.50clients are an optional ring control;
100clients and dense graphs are outside this smaller laptop series.

The original matched CNN/MLP architecture,2570-value head, FP32, AdamW recipe,
normalization/folds/augmentation and actual masking/CKKS operations are retained.
The trusted trainer owns plaintexts/private keys. Independent-client privacy,
measured WAN transport and a fixed accuracy threshold are not claimed.
Changed client counts affect learning/partitions as well as execution cost.

Source/hash/cache/runtime/driver are frozen. The existing server engine snapshot
remains unchanged. Original402/228runs, Word/PowerPoint/dashboard remain intact.
No scientific results or updated thesis figures are claimed by this preparation.
See docs/LAPTOP24_EXPERIMENTS_EL.md for the design, commands and limitations.

Start: 2026-11-10T12:50:33.714737+00:00. Deadline: 2026-11-11T12:50:33.714737+00:00.
Opening folders/reading status never starts training. Resume never resets24h.

| Clients | Graph | Model | Mode | Two-round recorded stages(s) |
|---:|---|---|---|---:|
|20|ring|cnn|none|32.85|
|20|ring|cnn|masking|28.17|
|20|ring|cnn|pairwise_masking|28.79|
|20|ring|cnn|selective_he|32.72|
|20|ring|cnn|adaptive_hybrid|32.89|
|20|ring|mlp|none|13.02|
|20|ring|mlp|masking|13.32|
|20|ring|mlp|pairwise_masking|13.72|
|20|ring|mlp|selective_he|18.06|
|20|ring|mlp|adaptive_hybrid|18.70|
|20|barabasi_albert|cnn|none|31.40|
|20|barabasi_albert|cnn|adaptive_hybrid|35.00|
|20|barabasi_albert|mlp|none|12.36|
|20|barabasi_albert|mlp|adaptive_hybrid|20.41|
|20|caveman|cnn|none|26.74|
|20|caveman|cnn|adaptive_hybrid|42.22|
|20|caveman|mlp|none|12.29|
|20|caveman|mlp|adaptive_hybrid|29.23|
|50|ring|cnn|none|49.57|
|50|ring|cnn|adaptive_hybrid|61.61|
|50|ring|mlp|none|23.11|
|50|ring|mlp|adaptive_hybrid|36.48|
