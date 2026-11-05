# V6: range-proved HE in MLP/CNN training

V6 adds mandatory two-sided integer range proofs to the v5 HE construction and
an explicit runner for real PyTorch local training. The runner protects the
2,570-value classifier with HE and masks **all remaining floating model state**,
including CNN BatchNorm running statistics. It does not silently substitute an
unprotected backbone or relabel legacy runs as results of this protocol.

## What the range proof proves

The encrypted coordinate is the signed fixed-point integer
`m = round(delta * scale)`, with `B = ceil(bound * scale)`. The claim is
**`-B <= m <= B`**, not that the client computed an honest gradient or that its
whole update has a particular L2 norm. Honest out-of-bound floating deltas are
rejected before encryption; no silent clipping is performed.

Use the standard independent Pedersen generators `G,H` from Dalek Bulletproofs.
For ElGamal ciphertext `R=rG, C=mG+rY`, create `V=mG+bH`. A joint representation
proof links the **same** `m` to the ciphertext and Pedersen commitment:

```
T1=aG       T2=dG+aY       T3=dG+eH
zr=a+cr     zm=d+cm        zb=e+cb

zr G = T1+cR
zm G + zr Y = T2+cC
zm G + zb H = T3+cV
```

The domain-separated challenge binds round policy, key-set ID, owner, coordinate,
joint key, both generators, ciphertext and all proof commitments. `H` is the
library's independent default generator, not a generator whose discrete log is
the committee's HE private key.

Dalek Bulletproofs then proves ranges for **both** derived commitments:

```
U = BG + V = (B+m)G + bH
W = BG - V = (B-m)G - bH
```

Both represented values must lie in `[0,2^k)` with `k` selected from 8/16/32 and
`2B < 2^k`. Their sum is fixed to `2B`. These numbers are far below the group
order, so modular wraparound cannot make a negative shifted value valid. A
one-sided proof alone would not establish the requested signed interval.

The native backend uses pinned `bulletproofs==5.0.0`, `curve25519-dalek==4.1.3`
and Merlin, with `Cargo.lock`. Each proof aggregates at most 512 coordinates
(two shifted values each); padding is fixed to public commitment `G`. Block
count, position, exact vector/ciphertext hash, participant and policy are bound
into the transcript. Receivers reject missing, truncated, trailing, substituted
or out-of-range proofs before approval/decryption. Native backend failure
aborts; there is no unproved or plaintext fallback.

V5's verified key-share possession and Chaum-Pedersen decryption-share proofs,
complete-roster approval, own-input inclusion and replay ledger remain in use.

## Full-model integration

`scripts/run_secure_training.py` is the new opt-in entry point. The legacy
`src/main.py` experiments and old results remain unchanged. Both new model
architectures live in `src/matched_models.py`:

| CIFAR-10 architecture | Trainable parameters | Classifier |
|---|---:|---|
| Budget-matched MLP | 1,655,514 | 256 to 10 |
| Residual CNN | 1,646,122 | 256 to 10 |

The budget match concerns **parameters**, not equal FLOPs or equal training time.
These are trained from scratch. The runner also supports MNIST/Fashion-MNIST
input shapes and existing IID, sorted-shard and Dirichlet loaders. Its current
aggregation topology is explicitly **full**, with uniform client weights;
other topology runners are not silently upgraded.

The CNN's global max pooling is implemented as a spatial flatten followed by
`max(dim=2)`, keeping the same output shape and first-maximum tie selection. This
avoids the unsupported deterministic CUDA backward of `AdaptiveMaxPool2d(1)`.
Forward values and tie gradients are checked against the original operation on
CPU and CUDA. The parameter counts and MLP architecture are unchanged.

For each round:

1. Train each local model on its assigned real-data partition with SGD.
2. Snapshot local deltas relative to the common committed model. Bind the full
   named tensor schema, base-state hash, scale, client roster and integer policy.
3. Protect the complete floating backbone with finite-field pairwise masks.
   Stream signed 32,768-value chunks. Every recipient verifies every chunk and
   final sender-blob hash before approving. A commitment failure permanently
   aborts that transaction. This avoids an oversized full-model RPC transcript.
4. Bind the backbone commitments/output into the HE classifier policy. Verify
   all classifier knowledge/range proofs and collective decryption shares.
5. Check the recovered full vector against the independently computed quantized
   plaintext control inside the trusted simulator. Integer BatchNorm counters
   use an explicit maximum policy. Apply **both** segments together only after
   all checks succeed; compare full-state hashes and evaluation loss/accuracy.
6. Atomically checkpoint the committed model, optimizer state, Python/NumPy/
   Torch/CUDA RNG and DataLoader generators, completed-round records, source/
   dataset/config/native hashes. A resumed invocation skips committed rounds.
   Interrupted protocol epochs are discarded and rekeyed, not resumed with
   reused crypto randomness. Model checkpoints are private and not committed.

Mask cancellation reveals the permitted aggregate once all masked contributions
are collected; pairwise approval is an integrity/application gate, not a promise
to hide an already computable sum until release. Backbone masking currently has
**no malicious-input range/norm proof**. The new Bulletproofs cover every HE
classifier coordinate. Malicious poisoning of an in-range update is not prevented.

## Build and run

On the Linux test environment, with a Rust toolchain installed:

```bash
python -m pip install -r requirements-protocol-v6.txt
cargo build --release --locked --manifest-path native/dfl_range/Cargo.toml -j 2
export DFL_RANGE_LIB="$PWD/native/dfl_range/target/release/libdfl_range.so"
DFL_REQUIRE_NATIVE=1 python -m unittest discover -s tests -p 'test_secure_protocol_v*.py' -v

python scripts/run_secure_training.py --model mlp --dataset cifar10 \
  --clients 20 --rounds 2 --batch-size 16 --train-samples 640 --test-samples 200 \
  --seed 1 --device cuda --output results/protocol_v6_training/mlp
# Use --model cnn with a separate output directory for the CNN.
```

Without sample limits the runner uses the available full dataset. The bounded
example is an **integration pilot**, not a thesis accuracy benchmark. Production
checkpoints/configs are not compatible with changing model/data/source/runtime
mid-run. Use a new output directory for a changed experiment.

`--preflight-only` saves a round-zero checkpoint without training. For a bounded
session, `--max-new-rounds 1` commits one new round; continue using identical
configuration plus `--resume`. `--resume` on an already complete run performs
zero new rounds. An OS file lock prevents duplicate writers. A failed round
leaves the last committed checkpoint available; no partial global model is applied.

The supplied benchmark archive option loads previously verified real CIFAR-10
image bytes, never synthetic images. Its hash and actual subset sizes are
recorded. The default torchvision path checks the downloaded datasets normally.

## Evidence and limits

Completed measurements, exact scopes, source hashes and resume checks are in
`results/protocol_v6/` and `results/protocol_v6_training/`. Do not infer completion
from this design description; read the receipts. Native-heavy Windows tests
are skipped when the library has not been built; the server gate requires the
real backend and disallows those skips.

This remains a **trusted-host FL simulation**. Its training process holds the
plaintext local model states, and hands vectors to crypto worker processes over
local IPC. Protocol RPCs carry protected updates, but this does not establish
privacy from the simulator/host administrator or an independently deployed
client service. Synthetic protocol gates and real-data training pilots are
reported separately. No independent security audit, general active-MPC proof,
DP, arbitrary-collusion, dropout recovery or poisoning-resistance claim is made.

The dependency review found informational advisory
[RUSTSEC-2026-0283](https://rustsec.org/advisories/RUSTSEC-2026-0283.html):
transitive `clear_on_drop 0.2.5` is unmaintained, with no patched release. This is
recorded rather than misreported as a clean advisory scan. It is not an advisory
about broken Bulletproof verification. No guarantee of complete secret-memory
erasure is made; a maintained dependency strategy needs review before production.
OS/GPU drivers and the whole application have not received an independent audit.

The recorded training environment also has package-version advisories for
PyTorch 2.11.0 (`torch.jit.script`,
[GHSA-rrmf-rvhw-rf47](https://github.com/advisories/GHSA-rrmf-rvhw-rf47)) and
Pillow 12.3.0 image-format decoders (including
[GHSA-22hg-r758-rrw9](https://github.com/advisories/GHSA-22hg-r758-rrw9) and
[GHSA-78g4-xqwv-q3g8](https://github.com/advisories/GHSA-78g4-xqwv-q3g8)).
The archived pilot path uses eager PyTorch models and `np.load(allow_pickle=False)`
uint8 arrays directly; it does not invoke TorchScript compilation or Pillow file
decoders. This is a bounded reachability assessment for that path, not a claim
that those package versions are generally safe. Keep the recorded research
profile separate from a patched deployment runtime and revalidate after updates.
The complete advisory query results are preserved with the receipts.

## Primary references

- [Dalek Bulletproofs implementation](https://github.com/dalek-cryptography/bulletproofs)
- [RangeProof API, aggregation sizes and verifier parameters](https://docs.rs/bulletproofs/5.0.0/bulletproofs/struct.RangeProof.html)
- [Independent Pedersen generators](https://docs.rs/bulletproofs/5.0.0/src/bulletproofs/generators.rs.html)
- [Bulletproofs paper](https://eprint.iacr.org/2017/1066)
- [V5 key/ciphertext/decryption proof design](SECURE_PROTOCOL_V5.md)

The interval/ciphertext composition and application integration are our
implementation; the references do not constitute an audit or endorsement of it.
