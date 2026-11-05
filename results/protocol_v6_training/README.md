# Real CIFAR10 MLP/CNN integration pilots

These are correctness/recovery pilots, not statistical accuracy results. Each
model trains from scratch for 2 rounds with 20 IID clients, one local epoch,
batch size 16, SGD learning rate0.01, 640 training images and200 evaluation images,
seed1 and full uniform aggregation. The real source archive has10000/1000 images
and SHA256 `4b585e8fd53b861fc5a22359bcd70e0402de9484fb9bad32b72e95ea11409cee`.
This archive subset differs from selecting640 samples directly from the full
torchvision dataset; the config records the exact data/partition/evaluation hashes.
Do not compare these short-pilot accuracies with the earlier full-budget CNN run.
No mean/sampleSD or multi-seed performance conclusion is inferred from them.

| Model | Parameters | Round | Accuracy (%) | Quantized control (%) | Full-state error |
|---|---:|---:|---:|---:|---|
| mlp | 1655514 | 1 | 13.00 | 13.00 | exact hash match |
| mlp | 1655514 | 2 | 22.00 | 22.00 | exact hash match |
| cnn | 1646122 | 1 | 8.50 | 8.50 | exact hash match |
| cnn | 1646122 | 2 | 10.50 | 10.50 | exact hash match |

Every round matched the independently computed quantized-plaintext mean over
both protected segments, including all BatchNorm running statistics/counters.
All20 applied client-state hashes agree. The final CNN counters advanced2->4.
The MLP checkpoint test preserved round1 evidence, ran only round2 after resume,
and a further resume executed zero rounds without changing checkpoint/CSV hashes.
`resume_validation.json` records these checks. Checkpoints/individual local states
are kept private on the server; they are not committed here.

The deterministic global-max implementation preserves the original first-tie
gradient and passed CPU/CUDA equivalence checks. The final MLP states also match
the pre-CNN-pool-fix MLP validation; that earlier run is not counted as an extra
independent experiment. Final jobs partially overlapped, so timing columns are
validation diagnostics under shared load, not model-speed benchmarks.

The trainer holds plaintext local states, just as the existing project simulator.
This does not demonstrate privacy from that process or the host administrator.
Range proofs cover the HE classifier; masking covers all other floating state
but does not prove malicious backbone input norms/ranges. Training integration
for independent services, other topology runners and full campaigns remains
separate work. Existing historical results were preserved.
