# RTX4090 scaling preparation —7November2026

Prepared, not executed. The36scaling cases use20/50/100logical clients,
both matched models, baseline/adaptive, and seeds1/2/3.12cases reuse50client
main jobs;24new jobs are required before optional scope.492unique candidates
are not a selected-run count.114mandatory main jobs must fit actual server
calibration within the inherited120h clock, including24h reserve.

16unit/regression tests passed. The100client CKKS test is an arithmetic
fixture with2570head values and40HE targets, not full100model GPU training.
Synthetic timing fixtures test admission and are not performance measurements.
No laptop calibration or selected plan is imported into the server pack.
Actual4090GPU calibration, memory fit and performance remain pending.
There are no new scientific accuracy/latency results in this folder.

See docs/SIMULATOR4090_SCALING_PLAN.md and the frozen manifest. The trainer
holds plaintexts and private keys. This is the approved trusted simulator;
the separate independent-client/proved protocol and402/228historical results
remain intact. No Word/PowerPoint/dashboard replacements are made yet.
