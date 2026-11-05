# V6 verified range proofs and real-training integration

**Research validation completed; not production certification.**

| Gate | Completed scope |
|---|---|
| Combined server tests | 27/27 passed, real native backend required |
| HE range-proof stress gate | 50 processes, 2,570 coordinates, 21 rejected cases |
| Stress-gate total | 895.97 seconds; setup and negative probes included |
| Real training | MLP and CNN, 20 clients each, 2 rounds, seed 1 |
| Exact controls | Full model-state hashes, loss and accuracy match quantized plaintext |
| Recovery | Pause after round 1, resume only round 2, complete-run resume executes 0 rounds |

The bounds tests include fresh valid participant signatures and valid ciphertext
knowledge proofs for values outside both ends of the interval; their range
proofs are rejected. Missing/tampered proofs, key substitution, cancellation,
invalid decryption shares, missing participants/approvals and replay also fail.

The 50-process diagnostic uses synthetic vectors. The separate real-data
pilots use the actual parameter-budget matched MLP and residual CNN, with HE
over their classifier and streamed masking over the complete floating backbone.
See [training evidence](../protocol_v6_training/README.md) and
[design, build and threat-model boundaries](../../docs/SECURE_PROTOCOL_V6.md).

Known runtime advisories are preserved and triaged; this is not a clean
dependency audit or an independent security review. The trainer is a trusted
host simulator with plaintext local states, not an isolated client deployment.
No DP, poisoning resistance, dropout recovery or full-backbone malicious range
proof is claimed. Historical campaigns and presentation/Word results are unchanged.
