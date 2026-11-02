# Reduced comparison series (2026-11-02)

228/228 selected runs verified; 76 configurations with seeds 1/2/3. These are a subset of the 1440-run plan, not an additional duplicate campaign. 119 existing outputs were reused and 109 runs were added. The original 402 runs remain separate.

Coverage: 180 Dirichlet alpha0.5 runs across three datasets, 5/10 clients, Caveman/Barabasi-Albert and five security modes; 24 extra baseline CIFAR runs for alpha0.1/1.0; 24 baseline CIFAR IID/two-shard runs. Other comparisons remain deferred.

Full datasets, MLP128, 20 rounds, one local epoch, batch32 and SGD0.01 retained. SD is sample SD (n-1), n=3. Times are observed under two-worker concurrency and have a separate session export.

## CIFAR baseline accuracy (percent; mean +/- sample SD)

| num_clients | topology | split_type | dirichlet_alpha | accuracy_mean_sample_sd |
| --- | --- | --- | --- | --- |
| 5 | barabasi_albert | dirichlet | 0.5 | 36.14 +/- 3.79 |
| 5 | caveman | dirichlet | 0.5 | 34.60 +/- 1.91 |
| 10 | barabasi_albert | dirichlet | 0.5 | 32.89 +/- 1.95 |
| 10 | caveman | dirichlet | 0.5 | 34.24 +/- 0.52 |
| 5 | barabasi_albert | dirichlet | 0.1 | 24.86 +/- 6.17 |
| 5 | caveman | dirichlet | 0.1 | 27.27 +/- 2.55 |
| 5 | barabasi_albert | dirichlet | 1.0 | 39.47 +/- 0.75 |
| 5 | caveman | dirichlet | 1.0 | 38.67 +/- 0.70 |
| 5 | barabasi_albert | iid | n/a | 43.78 +/- 1.02 |
| 5 | caveman | iid | n/a | 43.85 +/- 0.75 |
| 5 | barabasi_albert | non_iid | n/a | 25.30 +/- 0.20 |
| 5 | caveman | non_iid | n/a | 22.60 +/- 0.13 |
| 10 | barabasi_albert | dirichlet | 0.1 | 21.96 +/- 2.94 |
| 10 | caveman | dirichlet | 0.1 | 24.05 +/- 0.78 |
| 10 | barabasi_albert | dirichlet | 1.0 | 34.43 +/- 3.17 |
| 10 | caveman | dirichlet | 1.0 | 36.04 +/- 2.25 |
| 10 | barabasi_albert | iid | n/a | 40.16 +/- 0.31 |
| 10 | caveman | iid | n/a | 40.68 +/- 0.22 |
| 10 | barabasi_albert | non_iid | n/a | 19.41 +/- 1.04 |
| 10 | caveman | non_iid | n/a | 22.24 +/- 0.82 |

Max absolute protected-vs-baseline accuracy difference across 144 matched pairs: 0.1980 percentage points.

No full-grid or universal topology conclusion follows from this reduced scope. Three seeds offer limited precision. HE processing savings do not imply the same reduction in whole-training time or equivalent privacy.
