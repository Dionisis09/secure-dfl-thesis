# Secure aggregation v4 — implementation and measured boundaries

This is a separate, working **protocol prototype**, not a silent replacement of
the legacy training modes. It exposes all-party secure aggregation over real
mutually authenticated TLS connections between independent worker processes.
The large training campaign remains paused. No new model accuracy is claimed.

## Implemented

- Per-worker Ed25519 signing and ephemeral X25519 keys. The coordinator receives
  only public registrations. Enrollment/experiment CA is a trusted control plane.
- Public-ID-derived Gaussian masks are replaced by X25519/HKDF/ChaCha20 uniform
  masks in the prime field `2^61-1`. Rejection sampling avoids modular sampling
  bias. Fixed-point scale is `2^20`; inputs outside the declared finite bound
  are rejected, not silently clipped. Train/model seeds are not crypto secrets.
- Signed messages bind run, epoch, target, round, model/schema, roster, vector
  length and encoding policy. Contributions from exactly the enrolled roster
  are required. Each node checks its own committed contribution is included.
- Every member recomputes the canonical aggregate. It signs an approval only
  for that exact aggregate and checks all member approvals before release.
  A SQLite ledger rejects a second approval/release for the same round even
  across a process restart. A failed round requires an explicitly new epoch.
- TLS1.3 with experiment CA, client certificates and endpoint identity checks
  on each connection. The RPC role is restricted to the configured target.
  Protocol signatures are additional to TLS; a valid CA certificate alone is
  insufficient to impersonate another protocol signer.
- Actual OpenFHE multiparty **BFV**, with `NOISE_FLOODING_MULTIPARTY`, all-party
  private shares, `HEStd_128_classic` parameter selection and the configured
  participant count. No complete HE private key is assembled by this code.
- BFV plaintext modulus `2013265921`, fixed-point scale `65536`, packed head
  length2570. The encrypted sum is collectively decrypted, centered and divided
  by `scale * participant_count`. A modular inverse is deliberately not used
  to approximate real-number averaging. A declared range check prevents wrap.
- `model_adapter.py` provides explicit named-tensor schemas, SHA256 schema IDs,
  flatten/reconstruction and Torch/NumPy dtype-preserving overlay. It asserts
  `head.weight[10,256] + head.bias[10]`, shared by both proposed models.

### Why BFV rather than silently weaker CKKS

The installed OpenFHE CKKS backend rejects `SetMultipartyMode` and
`SetThresholdNumOfParties`. CKKS decryption-noise flooding has a different
configuration/calibration path and may require a128-bit native build for the
desired precision. The implementation **does not** silently drop those checks
or claim that the default CKKS decryption mode meets this new security goal.
`CKKS()` raises explicitly; the executable protocol ID is `he_bfv`.

Fixed-point BFV is suitable for the current shallow operation (sum and disclosed
mean); it is a deliberate change from the prior CKKS design. Quantization error
is measured separately. The128-bit setting is a library lattice-parameter
selection, not an independent proof/audit of this application protocol.

## Reproduce

On the tested Linux/Python3.10 environment:

```bash
python -m pip install -r requirements-protocol-v4.txt
python -m unittest discover -s tests -p test_secure_protocol_v4.py -v
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 python scripts/verify_protocol_v4.py \
  --participants 20 --output results/protocol_v4/protocol20.json
```

Pairwise and schema/replay tests also run on Windows without OpenFHE. The HE
integration gate requires the real backend and fails if it is absent.

The integration harness supplies random fixture vectors to each worker at
startup; they represent private local model inputs on a trusted experiment
host. Contributions are returned only as signed masked/encrypted payloads.
There is no remote operation to export signing/DH keys, private HE shares or
decrypt an arbitrary ciphertext. A diagnostic single-share probe is enabled
only in the test harness, uses only that node's own known fixture, returns a
boolean and accepts no external ciphertext.

### Gates exercised

Three-party and20-party tests each execute pairwise and real BFV aggregation
of2570 values, with separate OS processes and mTLS. Negative tests reject
individual ciphertexts, missing/duplicate participants, wrong context/round,
tampered contributions, raw-decryption RPCs, release before approval, wrong
mTLS client identity, absent client certificate, replay and duplicate input.
The BFV test also verifies a single worker share does not recover its individual
ciphertext. Results are recorded in `results/protocol_v4/`.

## Deliberate limits

- **All parties are required.** This is n-of-n decryption, not a general t-of-n
  recovery protocol. Dropped nodes cause abort; no plaintext fallback exists.
- Threat model is passive/curious peers on a trusted host/control plane, with
  at most one corrupted party in a minimum-three-member group and at least two
  honest unknown contributions. Arbitrary collusion, malicious key generation,
  poisoning, Byzantine agreement and active-secure MPC are not established.
- Authorized aggregates inherently disclose information. If all but one input
  are known, the remaining input follows by subtraction. Neither this code nor
  threshold HE prevents that. No differential-privacy/inference-resistance
  claim is made.
- The test fixture's trusted authority provisions TLS certificates. Node data
  signing/DH keys and HE shares are generated inside separate workers. Same-UID
  processes do not provide protection from a malicious host administrator or
  process escape. Production isolation of separate trust domains remains a
  deployment requirement, not a property established by these loopback tests.
- The RPC has a64MiB body limit and one request at a time per worker. Oversized
  full-backbone/dense groups fail closed; streaming/large-model integration is
  not yet validated. Pairwise core accepts vectors up to2million values, but
  the measured20-client case is the classifier vector, not the full CNN.
- The library creates ephemeral workers/keys for a configured group/round.
  A long-running, persistent client service and integration into all training
  and network runners remain separate work. The tensor adapter is not a claim
  that the144-run model evaluation has already started.
- No independent security audit or end-to-end production-security claim.

## Source references

- [OpenFHE threshold example](https://github.com/openfheorg/openfhe-python/blob/main/examples/pke/threshold-fhe.py)
- [OpenFHE developers: CKKS multiparty noise flooding](https://openfhe.discourse.group/t/support-for-noise-flooding-multiparty-in-threshold-ckks/2197)
- [CKKS noise-flooding requirements](https://github.com/openfheorg/openfhe-development/blob/main/src/pke/examples/CKKS_NOISE_FLOODING.md)
- [Bonawitz et al. secure aggregation](https://research.google/pubs/practical-secure-aggregation-for-privacy-preserving-machine-learning/)

The pairwise implementation uses the full-participation mask-cancellation
construction; it is not advertised as the full dropout-resilient Bonawitz
protocol. Standard cryptographic primitives do not automatically prove the
application-level composition secure against every attacker.

Integration elapsed times and JSON traffic include key setup and deliberately rejected negative requests. They are diagnostic workload measurements, not the latency/traffic of one clean training round.
