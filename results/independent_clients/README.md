# Independent-client validation (6 November 2026)

The coordinator receives protected updates and the common aggregate, never local
trained models, optimizer/RNG state or training shards. Each independent service
owns its local training and private checkpoint. Read the
[design and boundaries](../../docs/INDEPENDENT_CLIENTS_V7.md).

| Verified gate | Scope |
|---|---|
| Server regression tests | 35/35, native backend required, no skips |
| Recovery pilot | MLP, 3 clients, 2 rounds; mixed partial commit and all-service restart |
| Scaling pilot | MLP, 20 clients, 1 round |
| Scaling pilot | CNN, 20 clients, 1 round |
| Correctness | Complete state hashes exactly match a separate trusted quantized-SGD auditor |
| Boundary probes per 20-client job | 80 private-file reads and 20 process-memory reads denied |
| Completed-run recovery | Zero new train/decryption calls; client and coordinator checkpoints unchanged |

All final jobs use CPU, real CIFAR-10 shards of 32 images per client, batch16,
one local SGD epoch at0.01 and full uniform aggregation. These are correctness
and privacy-boundary pilots, not accuracy benchmarks or three-seed results.
The MLP/CNN scaling jobs overlap; elapsed times are not model-speed comparisons.
The original v6 range-proof primitive is retained. Full floating backbone masking
includes BN statistics, but malicious backbone range proofs are not implemented.

The coordinator's actual sandbox denies client dataset, identity, checkpoint and
TLS-key reads and memory-reading syscalls. Unsupported model/optimizer/debug/forge
APIs and invalid-base training requests are rejected. Linux tests also verify
future-thread inheritance, refusal of pre-existing threads, permitted enrolled
TCP traffic and denial of Unix/socketpair/UDP/raw/io_uring, non-enrolled TCP and
foreign file-permission changes. Client RPC audit files contain metadata only.
`public_job.json` contains public enrollment, not private enrollment keys.
No private data, checkpoints, TLS keys, private training RNG seeds or plaintext local models are
published. All services stopped after verification.

This is a same-host Linux process boundary with trusted host administrator and
trusted provisioning/test audit operator, not physical multi-host or GPU isolation.
Pre-readiness crypto failures abort and require operator recovery/new enrollment;
general dropout recovery, DP and poisoning resistance are not claimed. The known
v6 dependency advisories remain and no independent production audit is claimed.
Unrestricted nvidia-smi/CUDA failed while SSH remained available, so the GPU path
was not used. Earlier campaigns, dashboard, Word and PowerPoint remain unchanged.
Earlier development pilots are not added to these final receipts or counted as
independent statistical samples.
