# Verified additive HE v5

V5 replaces the vulnerable v4 **HE path**, rather than treating signatures as
proof that a participant generated its key or ciphertext correctly. The v4 BFV
Node path is retired by default; historical attack reproduction requires an
explicit unsafe opt-in. Existing training results are unchanged.

This backend is **exponential ElGamal on Ristretto255**, not BFV, CKKS or general
FHE. It supports the operation actually needed here: encrypted integer addition,
then disclosed fixed-point mean. Its measurements must be labelled separately
from previous backends. There is no lattice noise flooding or SIMD packing.

## The two repairs

### Public-key replacement

Every member generates an independent secret scalar `x_i` and public share
`Y_i = x_i G`, with a Schnorr proof of possession. Every honest node verifies
every proof and derives `Y = sum(Y_i)` itself, including its pinned own share.
There is no RPC accepting a caller-supplied final public key. Private scalars
remain in their node processes; the application never assembles their sum.

For a proof commitment `T = aG`, the response is `z = a + cx_i`; verification
checks `zG = T + cY_i`. The Fiat-Shamir challenge binds the protocol/round policy,
owner, public share and commitment. A participant replacing its share with
`Y_rogue - sum(Y_honest)` cannot reuse a proof for `Y_rogue`.

### Ciphertext cancellation

A quantized value `m` is encrypted as `(R,C) = (rG, mG+rY)`. Each coordinate
includes an AND representation proof of knowledge of **both** `r` and `m`:

```
T1 = aG                  T2 = bG + aY
zr = a + cr              zm = b + cm
zr G = T1 + cR           zm G + zr Y = T2 + cC
```

The challenge binds the full round policy, verified key-set ID, sender,
coordinate index, joint key, ciphertext and proof commitments. Honest nodes
verify all input proofs before approving the exact complete-roster aggregate.
Negating someone else's ciphertext does not provide its encryption randomness;
a fresh participant signature cannot replace the missing proof.

### Decryption-share integrity

For an approved aggregate `(R_sum,C_sum)`, member `i` releases
`D_i = x_i R_sum`, with a Chaum-Pedersen equality-of-discrete-log proof tying
`D_i` to the member's pinned public share. Proof challenges also bind the exact
approved aggregate digest and coordinate. The recipient verifies every share
before subtracting `sum(D_i)` from `C_sum`. This rejects fabricated shares,
rather than interpreting their output as a new accuracy measurement.

All members are required. Signed complete-roster approvals, an approval/release
ledger, own-contribution inclusion and exact aggregate recomputation are retained.
Replayed or individual/subset decryption requests fail closed. Each configured
round uses fresh node keys. A crashed round aborts; there is no plaintext fallback.

## Implementation and encoding

- Group operations use native libsodium via pinned `rbcl==1.1.2`; no curve
  arithmetic is implemented in Python. Canonical Ristretto encodings and scalar
  bounds are checked. The RFC 9496 generator known-answer test is included.
- SHA512 with domain separation and length-delimited inputs supplies the
  Fiat-Shamir challenges. Random scalars/nonces come from the native CSPRNG,
  independently of training/data seeds. Scalar arithmetic uses native routines.
- A ciphertext plus coordinate proof is 192 bytes; a partial-decryption proof
  record is 128 bytes. Vectors are strictly length checked before use.
- Default fixed-point scale is 65,536; honest inputs outside the declared bound
  are rejected, not clipped. Bounded signed baby-step/giant-step decoding happens
  only on the disclosed aggregate, before division by participant count/scale.
  Quantized sum recovery is exact; quantization itself remains an approximation.
- The 50-client gate uses a 2,570-value classifier vector and bound 1.0, including
  boundary values and quantization ties. This does not establish that every
  model update in a future training campaign satisfies that bound.
- Transport uses TLS1.3 mutual certificates with endpoint/role checks, strict
  HTTP/JSON framing and a 64 MiB request cap. A three-second inactivity/handshake
  timeout and 300-second total connection deadline bound test connections.
  Eight independent requests are processed concurrently across node processes;
  each node's state machine remains serial. This is a loopback test transport.
- A test-only signing oracle models a compromised participant in attack tests.
  It is disabled by default and cannot be enabled through the RPC interface.

## Reproduce

```bash
python -m pip install -r requirements-protocol-v5.txt
python -m unittest discover -s tests -p 'test_secure_protocol_v*.py' -v
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python scripts/verify_protocol_v5.py \
  --participants 50 --length 2570 --parallelism 8 \
  --output results/protocol_v5/protocol50.json
```

The source-backed receipt in `results/protocol_v5/verification.json` records the
actual completed checks, installed versions and source hashes. Old v4 receipts
remain historical evidence at their recorded commit. Passing a regression means
the two reproduced attacks are rejected; it is not independent certification.
These are CPU cryptography tests, not GPU training-performance measurements.

## Remaining boundaries

1. This is a new application composition of standard proof constructions, with
   no independent cryptographic audit or formal whole-protocol security proof.
   Do not infer general active-MPC, Byzantine agreement or poisoning resistance
   from rejection of these attacks.
2. Knowledge proofs are **not range proofs**. A malicious client can prove a
   chosen value outside the honest-input bound, poison an allowed sum or force
   bounded decoding to abort. Client norm/range enforcement against malicious
   code needs an additional reviewed mechanism if required by the threat model.
3. The harness knows its synthetic inputs and provisions certificates. Separate
   same-user processes are not independent trust domains or protection from a
   malicious server administrator. Persistent clients with local model/data,
   private state, enrollment and operating-system isolation remain deployment work.
4. Authorized aggregate outputs leak information. At least two honest unknown
   inputs are needed for the intended individual-update privacy setting; group
   overlap, collusion and repeated releases need a separate disclosure analysis.
   No differential-privacy or inference-resistance claim is made.
5. All-party availability, persistent key/restart handling, full-backbone
   transport and integration into training/topology runners remain unvalidated.
   A 50-member complete-roster protocol gate is not a 50-client model-training
   experiment. The wider campaign remains paused.
6. Proof verification and repeated transcripts have substantial CPU/network cost.
   Report measured complete-gate phases separately; do not label them training
   latency, compare them directly with the former BFV gate, or silently omit proofs.

## Primary references

- [RFC 9496: Ristretto255 and test vectors](https://www.rfc-editor.org/rfc/rfc9496.html)
- [libsodium Ristretto APIs](https://doc.libsodium.org/advanced/point-arithmetic/ristretto)
- [rbcl source and native bindings](https://github.com/nthparty/rbcl)
- [Damgaard: On Sigma-protocols](https://www.cs.au.dk/~ivan/Sigma.pdf)

The cited works document primitives and proof techniques. They do not audit or
endorse this application's particular composition or implementation.
