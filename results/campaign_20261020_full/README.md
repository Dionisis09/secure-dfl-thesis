# Full three-seed extension (in progress)

The user approved 1,440 new runs, separate from the original 402-run campaign
and the eight single-seed exploratory diagnostics. Final results are not yet
available. The local dashboard shows actual completed/pending/failed counts
and provisional mean/sample SD with the number of completed seeds.

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

Run/resume:

```powershell
python src/run_extended_campaign.py --workers 2 --publish_dashboard
```

The controller checkpoints progress and retries a failed job at most three
times. It refuses a duplicate live controller. Completed jobs are not rerun.
When all jobs finish, run `src/summarize_extended_campaign.py` to validate all
480 three-seed groups and write final statistics/evidence. The final PowerPoint
will be updated after the complete results are verified.
