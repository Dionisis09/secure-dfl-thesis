# CIFAR-10 accuracy investigation and new experiment options

The low non-IID accuracy is reproducible with the existing MLP and shard split.
The investigation did not find a CIFAR loading, caching or accuracy-denominator
error in the checks performed. Increasing the round budget from 20 to 40
improves shard/ring accuracy only from 22.69% to
24.32% for seed 1. IID reaches 47.45%
at 40 rounds with the same MLP. The evidence supports a substantial difficulty
from the partition and decentralized training setup. The contribution of the
MLP architecture itself has not been isolated with a CNN ablation.

## Scope and metric

Eight exploratory runs, one seed (1), full CIFAR-10 (50,000 train and 10,000
test), 5 clients, batch 32, SGD 0.01, one local epoch per round, SimpleMLP
(Flatten, Linear(3072,128), ReLU, Linear(128,10)), cached GPU execution.
Accuracy is the equal mean of the five clients' accuracies on the full shared
test set after synchronous neighbor aggregation. It is not accuracy on a
client's restricted training labels and not virtual mean-model accuracy.
The two 40-round runs use their round-20 checkpoints for equal-budget
comparisons. All other runs have 20 rounds. These are controlled exploratory
comparisons with no confidence interval or seed SD.

## New measurements

| Experiment (seed 1) | Dirichlet alpha | Rounds | Accuracy at 20 (%) | Final accuracy (%) |
| --- | --- | --- | --- | --- |
| shards_ring_40r | — | 40 | 22.690 | 24.320 |
| iid_ring_40r | — | 40 | 43.970 | 47.454 |
| shards_full_20r | — | 20 | 31.590 | 31.590 |
| dir01_ring_20r | 0.100 | 20 | 26.654 | 26.654 |
| dir05_ring_20r | 0.500 | 20 | 34.090 | 34.090 |
| dir10_ring_20r | 1.000 | 20 | 38.510 | 38.510 |
| dir05_caveman_20r | 0.500 | 20 | 33.418 | 33.418 |
| dir05_barabasi_20r | 0.500 | 20 | 34.236 | 34.236 |

## Original multi-seed context

The original 402-run campaign remains separate and unchanged. Its CIFAR-10
baseline uses 3 seeds per configuration, with sample SD in percentage points:

| num_clients | topology | split_type | mean | std | count |
| --- | --- | --- | --- | --- | --- |
| 5 | fully_connected | iid | 44.410 | 0.752 | 3 |
| 5 | fully_connected | non_iid | 31.260 | 0.456 | 3 |
| 5 | ring | iid | 43.931 | 0.714 | 3 |
| 5 | ring | non_iid | 23.303 | 0.738 | 3 |
| 10 | fully_connected | iid | 41.220 | 0.185 | 3 |
| 10 | fully_connected | non_iid | 34.087 | 0.334 | 3 |
| 10 | ring | iid | 39.939 | 0.416 | 3 |
| 10 | ring | non_iid | 17.551 | 0.670 | 3 |

Across 96 matched original CIFAR-10 security-versus-baseline pairs,
the maximum absolute accuracy change is 0.230 pp. The large
IID/non-IID gap is therefore also present without encryption and masking.

## What the checks establish

- The first 20 rounds of the new IID/ring, shards/ring and shards/full runs
  reproduce original seed-1 accuracy, training loss and test loss within
  1e-9. See `verification.json` for measured deltas and original source paths.
- The original shard split gives each of the five CIFAR clients exactly
  two classes and 10,000 training examples. Evaluation still covers all ten
  classes. At round 40, mean local training accuracy is
  77.21%, while mean
  global-test accuracy is 24.32%.
  Local fitting does not establish generalization to all classes.
- Switching only ring to full connectivity improves the shard result at
  round 20 from 22.69% to
  31.59% for the same seed and
  partition, while doubling directed model transmissions (10 to 20).
- Every new partition covers all 50,000 samples exactly once. For Dirichlet
  alpha 0.5 the three topology runs have identical per-client index hashes.
- Independent final confusion matrices reconcile the logged mean accuracy.
  Each client sees exactly 10,000 test examples. Existing regression tests
  check RGB tensor values/channel order against uncached ToTensor data.
- Real CPU/CKKS integration checks cover all five security modes with both
  new topologies on a small synthetic RGB dataset. Separate local HTTP smoke
  demos with synthetic data passed for Caveman and Barabasi-Albert. Those
  functional checks are not CIFAR accuracy evidence.

## Interpretation and limits

Severe class concentration, local updates before mixing, and limited graph
mixing are consistent with the observed gap. More rounds alone do not remove
it in this test. SimpleMLP flattens RGB images and has no convolutional spatial
features. A separate CNN comparison is needed to quantify that architectural
limitation; changing the original model would create a different experiment.

Dirichlet changes both labels and client sample counts. In this implementation
each class draws Dir(alpha) client probabilities, then multinomial counts,
without replacement. The complete draw repeats until every client has at
least 10 samples, with an explicit failure after 1,000 failed attempts.
The new allocation is not an equal-size shard split. Do not select an alpha
because it happens to yield the highest test accuracy in one seed.

Caveman uses two balanced communities (sizes 3 and 2 here), with the
connectivity-preserving size-two extension documented in the main README.
Barabasi-Albert uses m=2. With only five nodes these are small graph instances,
not evidence of scale-free behavior. The unchanged equal-neighbor aggregation
has stationary mixing weights proportional to degree+1 on undirected graphs.
Irregular degrees and Dirichlet quantity skew must therefore be considered
before attributing differences solely to topology. No sample-weighted or
Metropolis mixing was introduced.

The eight runs are exploratory, not a replacement for a matched three-seed
validation over all security modes. New results are deliberately separate
from the existing PowerPoint, thesis and dashboard's 402-run claims.

## Reproduction and evidence

```powershell
python src/run_cifar_diagnostics.py --dry_run
python src/run_cifar_diagnostics.py --output_dir results/cifar_reproduction
python src/run_cifar_diagnostics.py --resume
python src/analyze_cifar_diagnostics.py
python -m unittest discover -s tests -v
```

`plan.json` defines the eight configurations. `summary.csv` contains measured
run results, `*_metrics.csv` the round curves, `*_metadata.json` the partitions
and graph, and `*_diagnostics.json` the client confusion matrices.
`verification.json` records reconciliations and per-client local/global
accuracy. Original references come from `../campaign_20261014/summary.csv`
and its `metrics_path` records. Code entry points are
`src/main.py`, `src/data_utils.py`, `src/topology.py`, `src/client.py` and
`src/experiment_diagnostics.py`.

Method definitions: [connected Caveman](https://networkx.org/documentation/stable/reference/generated/networkx.generators.community.connected_caveman_graph.html),
[Barabasi-Albert](https://networkx.org/documentation/stable/reference/generated/networkx.generators.random_graphs.barabasi_albert_graph.html),
[Dirichlet partitions](https://flower.ai/docs/datasets/ref-api/flwr_datasets.partitioner.DirichletPartitioner.html).
