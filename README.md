Secure Decentralized Federated Learning

## Final results and artifacts

The [full three-seed Dirichlet/topology extension](results/campaign_20261020_full/README.md)
is now running: 1,440 new experiments, with Dirichlet alpha 0.1/0.5/1.0 and
Caveman/Barabasi-Albert comparisons. Its partial measurements are separate
from the completed 402-run artifacts below. Final slides and the downloadable
dashboard will be refreshed after the extension finishes and is validated.

The final MNIST, Fashion-MNIST and CIFAR-10 campaign completed **402/402 runs**: 360 validation, 30 sensitivity and 12 local HTTP network demos. The [campaign guide](results/campaign_20261014/README.md) documents the design, source CSVs, reproduction commands, findings and limitations.

- [Final main thesis](docs/Secure_DFL_Diplomatiki_Teliki_100plus_FINAL.docx): 103 pages, 35 figures and 38 tables, including the 402-run evaluation, revised abstracts and conclusions, full validation and sensitivity tables, and automatic contents and lists.
- [Final PowerPoint](docs/Secure_DFL_Thesis_Presentation_UPDATED.pptx): 38 slides and 27 editable charts. `Secure_DFL_Thesis_Presentation.pptx` contains the same final deck for compatibility.
- [Final Word technical report](docs/Secure_DFL_Technical_Report_COMPLETE_WITH_PLATFORM_FINAL.docx): updated results, sample SD, conclusions and methodological boundaries.
- [Offline dashboard](dashboard/README.md): download the self-contained HTML to explore all results, filters and source records.

Validation/sensitivity use full datasets and 20 rounds. Network demos use local HTTP, two rounds and subsets. Non-time metrics combine validated execution profiles; original and accelerated timings remain separate. The approximately 60% saving refers only to HE processing compared with selective HE in matching runs. Accuracy preservation does not establish privacy equivalence.

The main thesis, technical report, presentation and dashboard use the same final 402-run campaign. Historical audit and Docker examples are explicitly identified as separate demonstrations.

This project is a thesis prototype for decentralized federated learning.

Five clients train local models and exchange model parameters with their neighbors. There is no central aggregation server. The default dataset is MNIST and the default topology is a ring. IID and non-IID data splits are supported.

The available security modes are none, masking, pairwise_masking, selective_he and adaptive_hybrid.

Datasets:

mnist
fashion_mnist
fmnist
cifar10

Topologies:

ring
fully_connected
star
random
small_world
caveman
barabasi_albert

## Dirichlet partitions and additional topologies

The original `--split_type non_iid` still selects sorted-label shards (two per
client by default). `--split_type dirichlet` adds a separate class-wise
Dirichlet allocation with configurable `--dirichlet_alpha` (default 0.5).
Lower alpha produces more concentrated class proportions in expectation.
The allocation also changes client sample counts. It retries the whole draw
if a client has fewer than `--dirichlet_min_samples` (default 10), and fails
explicitly after 1,000 unsuccessful attempts. Every sample belongs to exactly
one client. Seeded partitions are reproducible, including on cached images.

`--topology caveman --caveman_cliques 2` uses communities connected in a ring
by rewiring one edge in each clique. Clique sizes differ by at most one when
the client count is not divisible by the requested clique count. Cliques must
contain at least two clients; size-two cliques retain their internal edge to
preserve connectivity. This is a connected Caveman variant, rather than
disconnected cliques. Equal cliques of size three or more match NetworkX's
connected Caveman construction up to seeded relabeling.

`--topology barabasi_albert --barabasi_m 2` uses NetworkX preferential
attachment, starting with its default star on `m+1` nodes. Each added node
attaches to `m` distinct existing nodes, with `1 <= m < num_clients`.
Small graphs should not be interpreted as evidence of a power-law distribution.

Examples:

```powershell
python src/main.py --dataset cifar10 --split_type dirichlet --dirichlet_alpha 0.5 --topology caveman --caveman_cliques 2 --execution_profile cached_gpu --diagnostics --experiment_name cifar_dir05_caveman
python src/main.py --dataset cifar10 --split_type dirichlet --dirichlet_alpha 0.1 --topology barabasi_albert --barabasi_m 2 --execution_profile cached_gpu --diagnostics --experiment_name cifar_dir01_barabasi
python src/run_validation_experiments.py --datasets mnist,fashion_mnist,cifar10 --split_types dirichlet --dirichlet_alpha 0.5 --topologies caveman,barabasi_albert --num_clients_list 5,10 --seeds 1,2,3 --security_modes none,masking,pairwise_masking,selective_he,adaptive_hybrid --execution_profile cached_gpu --output_dir results/dirichlet_validation --dry_run
```

Remove `--dry_run` to execute the requested validation grid. The simulation,
validation and HE sensitivity runners support the new options. Local HTTP
demos also accept `--split-type dirichlet`, `--dirichlet-alpha`,
`--topology caveman` and `--topology barabasi_albert` with hyphenated parameter
names. Caveman demos need at least four clients with the default two cliques.

Each new simulation run writes a `*_metadata.json` with effective partition
parameters, per-client class counts and index hashes, adjacency lists and
communication counts. `--diagnostics` adds final per-client local-training and
global-test confusion matrices plus a separate virtual mean-model probe.
The reported accuracy remains mean client accuracy on the shared global test
set. Diagnostic evaluation happens after the timed rounds.

Aggregation remains an equal average of each target and its neighbors,
across all five security modes. It does not weight models by sample count.
On irregular graphs repeated mixing favors clients in proportion to
`degree+1`. Dirichlet quantity skew and nonuniform graph degrees therefore
need to be reported when interpreting these experiments.

The [separate CIFAR-10 investigation](results/campaign_20261020_extension/README.md)
compares partitions, topologies and training budgets. Its exploratory runs
do not replace or augment the 402-run campaign's multi-seed statistics.

Definitions: [NetworkX connected Caveman](https://networkx.org/documentation/stable/reference/generated/networkx.generators.community.connected_caveman_graph.html),
[NetworkX Barabási–Albert](https://networkx.org/documentation/stable/reference/generated/networkx.generators.random_graphs.barabasi_albert_graph.html),
[Flower Dirichlet partitioning](https://flower.ai/docs/datasets/ref-api/flwr_datasets.partitioner.DirichletPartitioner.html).
The partitioner here uses its documented class-wise multinomial allocation,
without Flower's optional self-balancing heuristic.

Use a different dataset with:

python src/main.py --dataset fashion_mnist --security_mode none --experiment_name fmnist_baseline

Use a different topology with:

python src/main.py --topology small_world --security_mode pairwise_masking --experiment_name small_world_pairwise

Fashion-MNIST uses the same 28x28 grayscale input format as MNIST, so it is a safe second benchmark. CIFAR-10 uses 32x32 RGB images, so the model input size is adjusted automatically. The training logic remains the same.

Installation on Windows:

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Run the baseline:

python src/main.py --security_mode none --experiment_name baseline_run

Run pairwise masking:

python src/main.py --security_mode pairwise_masking --experiment_name pairwise_run

Run Selective HE:

python src/main.py --security_mode selective_he --experiment_name selective_he_run

Run Adaptive Hybrid:

python src/main.py --security_mode adaptive_hybrid --adaptive_he_target_ratio 0.4 --experiment_name adaptive_run

Add --split_type non_iid for a non-IID experiment.

Results are saved in results/logs and results/plots.

Create comparison results with:

python src/compare_results.py

Run the sensitivity analysis with:

python src/run_adaptive_sensitivity.py --split_type iid
python src/run_adaptive_sensitivity.py --split_type non_iid

The final technical report is stored in the docs folder.

Run the same validation matrix on MNIST, Fashion-MNIST and CIFAR-10:

python scripts/run_dataset_suite.py --workflow validation -- --skip_existing

For a smaller first run (one seed, three clients, one round, all four security modes):

python scripts/run_dataset_suite.py --workflow validation -- --seeds 1 --num_clients_list 3 --topologies ring --split_types iid --num_rounds 1

Run adaptive sensitivity on all three datasets:

python scripts/run_dataset_suite.py --workflow sensitivity -- --split_type iid
python scripts/run_dataset_suite.py --workflow sensitivity -- --split_type non_iid

Run the real network training demo on all three datasets:

python scripts/run_dataset_suite.py --workflow network -- --rounds 2

Preview any suite without training by adding --dry-run before the separator `--`.
Suite summaries are stored in separate dataset folders to avoid overwriting results.
The existing `platform_mvp/mnist_network_demo.py` command remains compatible and
now accepts --dataset fashion_mnist and --dataset cifar10. CIFAR-10 uses an RGB
32x32 input and the same lightweight MLP baseline; these are benchmark runs,
not a specialized CIFAR-10 accuracy model. Datasets download on first use.

Part 5 - Robustness and Validation Experiments

The validation runner checks the results with different datasets, random seeds, client counts, topologies and IID or non-IID data. Multiple seeds are used to measure how much the final metrics change between runs.

Smoke test:

python src/run_validation_experiments.py --seeds 1 --datasets mnist --num_clients_list 5 --topologies ring --split_types iid --security_modes none,pairwise_masking,adaptive_hybrid --num_rounds 3 --max_runs 3

Dataset and topology smoke test:

python src/run_validation_experiments.py --seeds 1 --datasets mnist,fashion_mnist --num_clients_list 5 --topologies ring,star,small_world --split_types iid --security_modes none --num_rounds 1 --dry_run

Show the planned commands without running them:

python src/run_validation_experiments.py --dry_run

Run the full default validation:

python src/run_validation_experiments.py --skip_existing

Validation summaries and plots are saved in results/validation.

Part 6 - Blockchain-based Audit Layer

Purpose

The blockchain component provides an optional audit and integrity layer for the decentralized federated learning prototype. Its purpose is to record a verifiable history of communication rounds, model-state hashes, security mode metadata, adaptive security decisions and communication metrics. It is not used for privacy protection, consensus or model aggregation.

Architecture

The audit layer is implemented as a lightweight local hash chain. Each experiment creates one genesis block and then one additional block per communication round. Every block stores the previous block hash, its own current hash, the experiment configuration hash, round-level metrics, client model hashes and deterministic simulated client signatures. The model parameters themselves are never stored in the blockchain.

Why blockchain is included

The blockchain layer is included to demonstrate how an immutable audit trail can support reproducibility, traceability and post-training integrity verification in decentralized learning experiments. It allows the experimenter to verify that recorded rounds, model hashes and selected metadata were not modified after the run. This is useful for thesis evaluation because it connects secure decentralized learning with an integrity mechanism without introducing a central aggregation server.

Limitations

This is not a production blockchain. It does not implement mining, consensus, networking, smart contracts, wallets or a distributed peer-to-peer ledger. The digital signatures are deterministic SHA256-based simulations and are intended only for educational verification inside this prototype. The blockchain does not protect model privacy; privacy is handled separately by masking and selective homomorphic encryption.

Threat model

The audit layer detects accidental or deliberate modification of exported blockchain records after an experiment has completed. If a block value, model hash, signature or previous hash is changed, verification reports an invalid chain or an invalid signature. The layer does not defend against a fully compromised local machine that can rewrite all experiment artifacts and regenerate the complete ledger.

Future work

Future versions could replace simulated signatures with real public-key signatures, distribute the ledger across clients, add independent timestamping, support external notarization and integrate stronger provenance checks for datasets, code versions and runtime environments.

Enable blockchain auditing with:

python src/main.py --security_mode adaptive_hybrid --enable_blockchain --experiment_name adaptive_blockchain_run

Blockchain outputs are saved in results/blockchain.

The main files are:

results/blockchain/adaptive_blockchain_run_blockchain.json
results/blockchain/adaptive_blockchain_run_blockchain_summary.csv
results/blockchain/adaptive_blockchain_run_verification_report.md
results/blockchain/blockchain_statistics.md
results/blockchain/verification_report.md
results/blockchain/plots

Run a small blockchain smoke test with:

python src/main.py --security_mode adaptive_hybrid --enable_blockchain --num_rounds 3 --experiment_name blockchain_smoke_test

Run the tamper detection demo with:

python src/demo_blockchain_attack.py results/blockchain/blockchain_smoke_test_blockchain.json

Expected result:

Chain INVALID

This shows that changing a saved block without recomputing hashes breaks the chain.

Optional faster execution

The original execution remains the default (`--execution_profile legacy`). For
MNIST, Fashion-MNIST and CIFAR-10, deterministic ToTensor images can be cached
once while retaining the same seeds, partitions, batch order, model, optimizer
and number of rounds:

```sh
python src/main.py --dataset cifar10 --device cuda --execution_profile cached_gpu --num_rounds 20 --experiment_name cifar10_cached_gpu
```

`cached_gpu` stores the converted images on CUDA (approximately 0.2 GiB for
MNIST/Fashion-MNIST or 0.7 GiB for CIFAR-10, in addition to model/runtime memory).
`cached_cpu` stores them in host memory. Both defer CUDA metric transfers until
the end of local training/evaluation, preserving the original Python accumulation
order. No mixed precision, batch-size or dataset reduction is used. The CSV and
audit configuration record `execution_profile`; compare timing measurements
within the same profile and keep earlier runs intact. Network demos retain their
original execution.

Regression checks for pixels, partitions, batch order, weights, losses and accuracy:

```sh
python -m unittest discover -s platform_mvp/tests -p test_execution_profiles.py -v
```

Advanced Audit Package

This is a more realistic audit prototype for the thesis implementation. It is separate from the lightweight blockchain simulation.

It uses:

real Ed25519 client signatures
append-only JSONL ledger
Merkle root for client model hashes
public key manifest
verification CLI
audit summary CSV
audit report
audit plots

Enable it with:

python src/main.py --security_mode adaptive_hybrid --enable_audit --num_rounds 3 --experiment_name audit_demo

Outputs are saved in:

results/audit_packages/audit_demo/

Main files:

results/audit_packages/audit_demo/ledger.jsonl
results/audit_packages/audit_demo/public_keys.json
results/audit_packages/audit_demo/audit_summary.csv
results/audit_packages/audit_demo/verification_report.md
results/audit_packages/audit_demo/audit_statistics.md
results/audit_packages/audit_demo/plots

Verify the audit package:

python src/audit_cli.py verify --package results/audit_packages/audit_demo

Inspect one round:

python src/audit_cli.py inspect-round --package results/audit_packages/audit_demo --round 1

Run tamper detection:

python src/audit_cli.py tamper-demo --package results/audit_packages/audit_demo --mode hash
python src/audit_cli.py tamper-demo --package results/audit_packages/audit_demo --mode signature

The audit package is still a prototype, but it is closer to a realistic integrity-verification mechanism than the local blockchain simulation.
