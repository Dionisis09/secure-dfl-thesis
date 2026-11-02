# Full three-seed extension (wider grid deferred)

The original design contains 1,440 runs, separate from the original 402-run
campaign and the eight single-seed exploratory diagnostics. On November 2,
2026, a [selected subset of 228 runs](../campaign_20261102_reduced/README.md)
was completed and verified: 76 configurations with seeds 1/2/3. The other
1,212 runs remain deferred. No experiment workers are running. The dashboard
and presentation report the completed subset explicitly; they do not claim
completion of this wider grid. The selected subset reuses 119 existing outputs
and adds 109 runs without reducing the full datasets or training settings.

- 1,080 Dirichlet runs: alpha 0.1, 0.5, 1.0 on ring, fully connected, connected
  Caveman (two balanced communities) and Barabasi-Albert (m=2).
- 360 IID/two-shard runs on the two new topologies.
- All combinations use MNIST, Fashion-MNIST and CIFAR-10, 5/10 clients,
  seeds 1/2/3, and none/masking/pairwise/selective HE/adaptive hybrid.
- Full datasets, 20 rounds, one local epoch, batch 32, SGD 0.01 and MLP 128.

Two persistent workers reuse immutable cached images. Each experiment still
trains its clients serially with the unchanged algorithm. Timings are labeled
`parallel_2_workers` and are kept separate from the original serial profiles.
`execution_validation.json` records a full 20-round CIFAR-10 baseline check:
accuracy, training loss and test loss match the serial cached run exactly.

Optional full-grid reproduction (not required for the selected results):

```powershell
python src/run_extended_campaign.py --workers 2 --publish_dashboard
```

Running the command above would resume the deferred wider grid. It is not
started automatically. The controller checkpoints progress and retries a failed job at most three
times. It refuses a duplicate live controller. Completed jobs are not rerun.
When all jobs finish, run `src/summarize_extended_campaign.py` to validate all
480 three-seed groups and write full-grid statistics/evidence. Final statistics
for the completed 76-group subset are already available in
`../campaign_20261102_reduced/`; the updated PowerPoint includes that subset.
