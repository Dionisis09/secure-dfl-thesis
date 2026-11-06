# V7: independent local-training services

The coordinator no longer owns local models, training data, optimizers or local
RNG state. Each independently launched client trains and protects its update
inside its own service. The coordinator handles public global states and
protected protocol messages. This opt-in path uses the v6 range-proved HE
primitives; it does not change earlier experiments or make their privacy claims
stronger retroactively.

## Roles and trust boundary

| Role | Holds | Receives from the clients |
|---|---|---|
| Client service | Its shard, trained model, optimizer/RNG, signing and ephemeral DH/HE secrets | Other clients' signed protected transcripts, relayed by the coordinator |
| Coordinator/trainer | Common initial/global model, fixed public job, public enrollment, its own TLS credential | Masked backbone chunks, range-proved ciphertexts, collective approvals/decryption shares and global-state consensus receipts |
| Trusted provisioning operator | Fixture shards, certificate provisioning and job distribution | Enrollment public keys; this operator is outside the trainer boundary |
| Optional test auditor | Explicit test-only access to private fixtures | Independently recomputes the quantized SGD result; never runs inside the coordinator |

The tested deployment uses separate long-running processes on one Linux host,
with Landlock filesystem/TCP restrictions, a seccomp syscall filter and
`PR_SET_DUMPABLE=0` plus disabled core
dumps. Each role can write only its own private directory. Software/runtime
roots are read-only; the full user home, other job directories and client
datasets/checkpoints/keys are not allowed in the coordinator's sandbox. No
Docker socket, shell-execution API or remote file-loading API is provided.
Landlock ABI 4 or newer and seccomp are required. Missing kernel support aborts;
there is no same-UID unsandboxed fallback.
Confinement is applied before importing PyTorch/NumPy or loading client secrets.
An already multithreaded startup is rejected, because Landlock restrictions on
one thread would not confine pre-existing sibling threads. Future worker threads
inherit the restrictions; this inheritance is also tested.
Only enrolled TCP ports are permitted. Unix sockets, UDP/raw/netlink sockets,
socket pairs, exec, cross-process memory/ptrace, io_uring and namespace/mount
escape routes are blocked. Path-based permission/ownership and ACL/xattr changes
are blocked too; checkpoints use `fchmod` only on already authorized open files.
This prevents changing another same-UID client's file permissions to expose it.
This matters for same-UID services: an unrestricted
Unix connection to a user service manager could otherwise request an unconfined
process. This is a combined policy, not a claim that seccomp alone is a sandbox.

This is an application/process boundary on a trusted host, not separate physical
machines or protection against root, the deployment operator, the kernel,
drivers or a compromised software supply chain. Do not launch the coordinator
from an administrator process that passes it client file descriptors, private
data or provisioning keys. The trusted launcher starts services independently;
the coordinator does not create their processes. For separate hosts, provide
properly issued endpoint-valid TLS certificates and pinned public enrollment,
and keep each client's private directory on that client's machine. Cross-host
deployment and GPU isolation require their own validation.

## Fixed policy and round flow

The job hash pins the architecture, input shape, initial global-state hash,
roster and enrollment, training settings, partition sizes, range bounds, source
hash and native backend hash. A client accepts only its next round and its own
committed base hash. The coordinator cannot upload a replacement model, select
an arbitrary subset, change the learning rate or request a plaintext update.
Common initial weights are distributed as an explicit public tensor buffer,
rather than relying on random initialization being identical under every
runtime. RPC tensor decoding uses exact schemas/byte counts, never pickle.

1. Every client trains on its own shard using its fixed local configuration.
   Its response contains a signed round/policy readiness message and a fresh
   ephemeral DH public key, without local weights, losses or per-client metrics.
2. Every client verifies the complete signed ephemeral enrollment, including
   its own message. This enrollment is bound into both segment contexts.
3. Clients mask the complete floating backbone, including BatchNorm running
   statistics. Signed chunks and whole-blob commitments are checked by every
   client. The coordinator can recover the authorized uniform mean once all
   masked inputs are collected; approvals do not hide an already computable sum.
4. Each client creates its own HE secret share. The classifier deltas use the
   v6 equality/knowledge proofs and mandatory two-sided Bulletproofs. Every
   client verifies the complete ciphertext set and collective approvals before
   releasing its verified decryption share. No single HE private key is held by
   the coordinator.
5. Each client independently reconstructs both means from verified transcripts,
   applies them to its locally committed base, and signs the resulting global
   hash. Integer BatchNorm counters use the public maximum scheduled batch-step
   policy, not a trainer-supplied integer value. Both segments are applied together.
6. The coordinator verifies all clients agree with its own independently
   reconstructed global hash. Clients durably save a pending global state before
   returning readiness. The coordinator fsyncs a commit-intent journal before
   sending the complete signed readiness set. Clients verify that set and commit.

The coordinator checkpoint contains only a public global-state tensor buffer,
round records and signed public consensus receipts. Local shards, local optimizer
state, local RNG state and private protocol keys are never included. Ordinary
RPC audit logs contain operation names and byte counts, not request/response
bodies. Client logs/checkpoints remain in their private directories.

## Recovery and failure handling

Clients keep an exclusive service lock and an atomic fsynced private checkpoint.
The coordinator has its own exclusive writer lock and fsynced aggregate-only
journal. A restart after the coordinator's durable commit intent can finish the saved collective commit;
repeating an already committed request is idempotent. A completed coordinator
resume executes no new training or decryption rounds.

An interrupted epoch *before* durable global readiness is deliberately fail-closed:
an inflight marker prevents automatic retraining, rekeying or another decryption
release for that round. This needs operator recovery/new enrollment; arbitrary
dropout recovery is not implemented. No plaintext fallback is available. In-range
malicious gradients, update poisoning, DP, arbitrary collusion and malicious
backbone input-range proofs remain outside the demonstrated guarantees. At least
two non-colluding honest contributors are needed to avoid the trivial inference
of the remaining contributor from a sum and all other inputs. Aggregates and
metadata still leak information; secure aggregation is not differential privacy.
The same operator-recovery limit applies if clients saved readiness but the
coordinator crashed before saving its own commit intent; that earlier window is
not claimed as automatically recoverable by the current journal.

## Reproduce a bounded local-host verification

Use the recorded Python dependencies from v6 and build its native backend first.
The trusted operator supplies a real CIFAR-10 NPZ archive with `train_images`
uint8 NHWC and integer `train_labels`. The verifier creates per-client shards;
the coordinator never opens that source archive.

```bash
export DFL_RANGE_LIB=/absolute/path/to/libdfl_range.so
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python -m unittest discover -s tests -p 'test_independent_clients.py' -v
python scripts/verify_independent_clients.py --data-archive /private/sample.npz \
  --model mlp --clients 20 --job mlp20 --recovery
python scripts/verify_independent_clients.py --data-archive /private/sample.npz \
  --model cnn --clients 20 --job cnn20
```

Each client gets 32 training images, batch size 16, one local epoch and SGD 0.01.
The recovery check uses two rounds, otherwise one. This verifier explicitly uses
CPU; it is a correctness/privacy-boundary pilot, not an accuracy or speed benchmark.
It runs the aggregate coordinator in its sandbox, probes forbidden private file
reads and cross-client `process_vm_readv`, tests rejected exfiltration API commands,
and uses a separate trusted auditor to check exact quantized full-model results.
All services are stopped by the trusted verifier after success/failure.

`private-jobs/` contains enrollment secrets, datasets and checkpoints and is ignored
by Git. Never publish it. Reviewable receipts are written under
`results/independent_clients/<job>/`; publish only those reviewed artifacts.

To launch already provisioned roles independently:

```bash
python scripts/independent_client.py --config /client-only/config.json
python scripts/run_independent_training.py --config /coordinator-only/config.json
```

The current aggregation topology is full/uniform. Existing ring, Caveman,
Barabási–Albert, sensitivity and network campaign runners are not automatically
replaced by this entry point. No new multi-seed accuracy result or updated
Word/PowerPoint/dashboard is implied by implementing this boundary.
The provisioning policy caps enrollment at 50 to keep the full HE transcript
inside the bounded RPC body; the independent-training scaling gate is 20.
Larger groups require further transport, timeout and resource validation.

## Evidence and runtime limits

Read the receipts in `results/independent_clients/` for completed scopes and source
hashes. The dependency advisories and limitations documented in
[v6](SECURE_PROTOCOL_V6.md) still apply; changing process placement does not fix
them. No independent production security audit is claimed.

On 6 November 2026 the CEID SSH account remained accessible, but an unrestricted
`nvidia-smi` reported no devices and unrestricted PyTorch CUDA initialization also
failed. These checks therefore use CPU. They do not establish a CUDA performance
or GPU-memory isolation result, and do not diagnose why the server GPU failed.

Primary platform references:

- [Linux Landlock policy and inheritance](https://docs.kernel.org/userspace-api/landlock.html)
- [Linux non-dumpable processes and ptrace](https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html)
- [Linux seccomp filtering, ABI checks and inheritance](https://docs.kernel.org/userspace-api/seccomp_filter.html)
- [V6 proof construction and restrictions](SECURE_PROTOCOL_V6.md)
