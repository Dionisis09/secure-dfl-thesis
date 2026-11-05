# V5 protocol repair and 50-client verification

The two reported HE attacks are rejected in the new verified additive ElGamal
path. Legacy v4 BFV is disabled by default and retained only behind an explicit
unsafe reproduction opt-in. No previous model result is relabelled as v5.

| Check | Completed result |
|---|---|
| Local new-protocol suite | 9/9 passed |
| Server combined v4/v5 suite | 17/17 passed |
| New HE gate | 50 processes, 2,570 values, mTLS, 17 forbidden cases rejected |
| Pairwise baseline gate | 50 processes, 12 forbidden cases rejected |
| Exact quantized-plaintext control | Maximum difference 0 |
| Unquantized mean comparison | Maximum absolute error 7.629394531e-06 (vector units, not accuracy percentage) |
| New HE complete diagnostic gate | 249.60 seconds |
| Pairwise complete diagnostic gate | 9.55 seconds |

The HE gate uses bound 1.0 and scale 65,536, including signed boundaries,
cancellation, zero and quantization ties. Both attack tests use a fresh valid
participant signature: rejection is not just a bad-signature check. All fifty
members verify every ciphertext proof before release. Decryption shares are
verified against pinned public shares and the approved aggregate.

HE phase times: setup 6.54s,
input encryption/proofs 3.13s,
proof verification/approval 211.96s,
decryption-share production 8.50s,
share verification/decoding 10.43s.
Total JSON request traffic was 3.614 GB and
responses 56.88 MB. Totals include setup and
rejected probes; HTTP/TLS overhead is excluded. These are CPU protocol tests,
not GPU training benchmarks or clean-round latency estimates.

`legacy_reproduction.json` is an explicitly unsafe **v4** negative control:
the two old attacks still reproduce there, while the v5 path rejects them.
`protocol3.json` is the final-source three-member smoke gate.
`protocol50.json`, logs and normalized source hashes establish the tested scope.
The six exact Python dependencies had no known advisories in the recorded
pip-audit query; this is not a native-library/OS or protocol audit.

This remains a research prototype: no independent security audit, whole-protocol
formal proof, range proofs, poisoning resistance, DP or independent-host isolation
is established. The harness knows its synthetic inputs. All-party participation
is required; crashes abort without plaintext fallback. Full training, persistent
clients and full-backbone transport remain separate work. The training campaign
is still paused. Read [the design and limits](../../docs/SECURE_PROTOCOL_V5.md).
