# Protocol v4 security review — 5 November 2026

**Decision: suitable for supervisor review as a research prototype with disclosed
limits. NOT ready for deployment with sensitive updates or malicious clients.**
This is an implementation review and synthetic adversarial test, not an
independent cryptographic audit. Functional success is separate from security.
The old training campaign remains paused; its results were not changed.

## Critical findings reproduced

Tests use only synthetic 32-value vectors, three participants and the real
OpenFHE backend. One participant deliberately bypasses its own honest local
implementation. This is the relevant distinction between a curious participant
following the code and an actively malicious participant controlling its process.

| Finding | Reproduction | Consequence | Status |
|---|---|---|---|
| Signed rogue final public key | Final participant signs an unrelated public key, with a valid previous-key hash. Honest nodes accept the signed chain. | Attacker decrypts an individual contribution with its own secret key, without any aggregate approvals. Reconstruction error below 7.39e-6. | **Deployment blocker**: authenticated key-chain linkage does not prove correct joint-key generation. |
| Adaptive ciphertext cancellation | Corrupt participant signs the negation of another participant's ciphertext. All approvals accept the recomputed sum. | The authorized mean reveals a victim's update after multiplication by three; error below 7.51e-6. | **Deployment blocker**: signatures and sum recomputation do not prove plaintext knowledge or well-formed local encryption. |

These are application-protocol limitations, not evidence that BFV, TLS or
OpenFHE's advertised primitive security is broken. The previous passive-peer
threat model excludes these attacks; it cannot be expanded merely by adding
negative tests. The demonstrations are in
[`active_limit.json`](../results/protocol_v4/active_limit.json), reproducible with:

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 python scripts/probe_protocol_v4_active_limit.py
```

A successful probe means the security limitation was reproduced, **not** that
the protocol passed an active-security gate.

## Implementation defects fixed in this review

| Area | Before | After / validation |
|---|---|---|
| Tensor recovery | A finite float64 value could become infinity when cast to float32; duplicate names and integer schemas were accepted. | Strict bounded schema, unique names, floating dtypes, shape/size checks and finite checks after casting. Destination dtype must match. |
| Integer buffers | Fractional, overflowing or nonscalar replacements could be silently cast. | Exact in-range scalar integers only; maxima cannot decrease the existing counter. Original state is cloned. |
| Enrollment/policy | Caller could mutate a pinned roster; node IDs were used as filenames without a safe naming policy. | Defensive copy, identity/key validation, duplicate-key and unusable DH-key rejection; safe IDs and strict bounded policy types. |
| Transport availability | TLS handshake and request reads could wait indefinitely. | Three-second socket/handshake inactivity timeout, 30-second connection deadline, strict framing/JSON/body bounds, rejection of duplicate keys and nonfinite JSON. No unbounded request threads touch protocol state. |
| Error disclosure | Backend exception text was returned to callers. | Generic errors; no native exception details returned. |
| BFV recovery | No final declared-range check. | Reject a recovered mean outside the declared range plus quantization tolerance. This is not a malicious-input range proof. |
| Evidence | Totals mixed successful and rejected traffic without separate counters. | Positive traffic counters separated; reports carry runtime versions and normalized source hashes. |

Timeouts bound individual stalled connections; this is not proof of resistance
to sustained denial of service. The loopback transport uses Python `http.server`,
which its [official documentation](https://docs.python.org/3/library/http.server.html)
does not recommend for production.

## Verification and measured scope

- Windows: **8/8 unit/integration tests passed**. Linux server: **8/8 passed**.
- Real server: **20 independent processes per mode**, mTLS, 2,570-value head.
  Pairwise and multiparty BFV completed; 12 and 13 forbidden-request checks
  respectively passed. Fixtures include positive/negative range boundaries,
  cancellation, zero and quantization ties.
- Maximum mean error: pairwise **4.7684e-7**, BFV **7.6294e-6**, in the units of
  the synthetic vector. These are not accuracy percentages or privacy scores.
- OpenFHE 1.6.1.0.22.4, cryptography 50.0.2, NumPy 2.2.6, cffi 2.1.1 and
  pycparser 3.11: `pip-audit` reported no known advisories for these five exact
  installed versions. This covers the queried Python packages, not the OS,
  bundled native dependencies, unknown vulnerabilities or protocol design.
- Source hashes, receipts and test logs are in
  [`results/protocol_v4`](../results/protocol_v4/verification.json).
  Gate timings include setup and rejected requests; they are not clean training
  benchmarks. BFV's successful RPC request payloads alone were about **2.03 GB** with
  the current repeated-transcript design. This requires optimization and a new
  measurement before scaling, rather than extrapolating a small ciphertext size.

## Remaining realism requirements

1. **Private inputs and keys must belong to independent clients.** `Group` is a
   trusted-host test harness: its coordinator already knows all fixture values
   and provisions all TLS key files. Separate same-user worker processes do not
   establish isolation from that user, the host administrator or a compromised
   coordinator. Production clients must load their own local data and private
   keys, with verified enrollment, separate access controls and certificate
   lifecycle management.
2. **Choose and validate the actual adversary model.** A realistic malicious-peer
   claim needs an established protocol with verified distributed key generation
   and validated contributions, including appropriate proofs or equivalent
   reviewed mechanisms. Do not patch the two demonstrations and infer general
   security. A commit-before-reveal step alone would not fix rogue key generation.
   If evaluation is deliberately semi-honest, label that limitation throughout.
3. **Protect the whole update and specify aggregation weights.** Current tests
   cover an equally weighted classifier head only. Encrypting only the final
   layer leaves a plaintext backbone exposed. A complete hybrid must protect
   the backbone as well and bind tensor schemas, weights, masks and HE segments
   to one approved round policy. The real training/network runners do not yet
   use this prototype. The 64 MiB RPC cap cannot carry an arbitrary full-model
   dense transcript; large-vector transport remains unvalidated.
4. **Validate disclosure across rounds and topologies.** A minimum group of three
   is not a universal privacy guarantee. Authorized means leak information;
   overlapping neighborhoods and repeated releases may allow reconstruction.
   Identify who can see each aggregate and test the combined disclosure model.
5. **Test failure and recovery with 20 real training clients.** All-party BFV
   requires every share. Dropout aborts; there is no plaintext fallback. The
   ledger blocks approval/release replay, but it is not a persistent client/key
   recovery service. Validate process restarts, lost responses, timeouts, bounded
   storage, per-neighborhood key policy and full-model quantized controls before
   starting a model comparison. No claim of poisoning resistance, differential
   privacy, arbitrary collusion tolerance or Byzantine robustness is made.

## Sharing and experiment decision

Share the repository with this review attached and describe v4 as a **functional
semi-honest aggregation prototype with known active-security failures**. Do not
present it as a finished secure deployment. Keep the new full training campaign
blocked until the security model, client boundary and training integration are
resolved; preserve the historical results separately.

Existing Word/PowerPoint results describe prior experiment implementations;
they were not rewritten or relabelled as results of v4 in this review.
