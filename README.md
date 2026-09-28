Secure Decentralized Federated Learning

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
