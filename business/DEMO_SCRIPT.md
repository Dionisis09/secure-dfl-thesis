# Demo Script

Goal

Show the project in 5 to 10 minutes as a serious R&D prototype.

Main message

This is a secure federated learning research prototype that compares baseline decentralized learning, masking, selective homomorphic encryption, adaptive hybrid security and audit verification.

Before the demo

Open the project folder:

C:\Users\dioni\Desktop\diplomatiki kodikas\secure-dfl-thesis

Activate the virtual environment:

.\.venv\Scripts\Activate.ps1

Demo flow

1. Explain the problem

Many organizations cannot centralize sensitive data, but still want collaborative machine learning. Federated learning helps, but it creates new questions about security, overhead, reproducibility and auditability.

2. Show the available modes

Open README.md and show:

- none
- masking
- pairwise_masking
- selective_he
- adaptive_hybrid
- blockchain audit layer

3. Run a short adaptive hybrid experiment

Command:

python src/main.py --security_mode adaptive_hybrid --enable_blockchain --num_rounds 3 --experiment_name demo_secure_fl

What to say:

This run trains local clients, applies adaptive hybrid protection, records metrics and creates an audit trail. The blockchain layer does not change aggregation or learning. It only records verifiable evidence after each round.

4. Show generated metrics

Open:

results/logs/demo_secure_fl_metrics.csv

Point out:

- accuracy
- loss
- communication bytes
- masking time
- HE time
- adaptive selected targets

5. Show plots

Open:

results/plots/demo_secure_fl/

Point out:

- accuracy curve
- loss curve
- communication
- round time

6. Show audit outputs

Open:

results/blockchain/demo_secure_fl_blockchain.json
results/blockchain/demo_secure_fl_verification_report.md
results/blockchain/blockchain_statistics.md
results/blockchain/plots/

What to say:

The audit layer records hashes of client models, round metadata, security mode, adaptive decisions and verification results. It does not store model parameters.

7. Run tamper detection

Command:

python src/demo_blockchain_attack.py results/blockchain/demo_secure_fl_blockchain.json

Expected output:

Chain INVALID
Verification status: INVALID_HASH_CHAIN

What to say:

This demonstrates that if an exported block is modified after the run, verification detects the change.

8. Show final report

Open:

docs/Secure_DFL_Technical_Report_FINAL.docx

What to say:

The prototype is accompanied by a technical report based on actual CSV metrics and generated figures.

Closing message

This prototype can be adapted to a client's dataset to evaluate whether privacy-preserving federated learning is technically realistic, what security mode is appropriate and what overhead should be expected.

Questions to ask the client

- Where is the data currently stored?
- Why can the data not be centralized?
- What model or prediction task matters?
- Is the priority privacy, integrity, accuracy or communication cost?
- Is this for research, internal evaluation or production planning?
- What would count as a successful PoC?
