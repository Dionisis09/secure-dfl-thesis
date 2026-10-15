# Final campaign: 14 October 2026

All **402/402 runs completed**, with no failed or pending runs. Completed at 19:48 UTC on 14 October 2026. The final documentation and dashboard were revised on 15 October.

| Workflow | Runs | Design |
| --- | ---: | --- |
| Validation | 360 | 3 datasets × 3 seeds × 2 client counts × 2 topologies × 2 splits × 5 modes |
| Sensitivity | 30 | 3 datasets × 2 splits × 5 HE ratios; seed 42 |
| Local HTTP network | 12 | 3 datasets × 2 splits × baseline/masking; seed 42 |

Validation and sensitivity use full train/test datasets, 20 rounds, one local epoch, batch 32, SGD 0.01 and an MLP with 128 hidden units. The network demos use three local processes, two rounds, 1,500 train / 500 test images, batch 64 and SGD 0.05.

## Evidence

- `manifest.json` retains the executed commands, run configurations, status and raw CSV paths. Historical commands contain the original machine's paths.
- `reproduce_commands.json` provides equivalent argument lists with `python` and repository-relative paths. Run from the repository root. These commands reuse the original experiment names; change names and output directories when preserving archived results.
- `summary.csv` contains one row per completed run. `performance_summary.csv` and `learning_curves.csv` aggregate non-time values.
- `grouped_summary.csv` retains execution-profile-specific means, sample SD and count. `EXECUTION_PROFILES.txt` documents the optimization and preserved original runs.
- Raw validation/sensitivity round CSVs are in `../logs/`; network round CSVs and summaries are in `network/`. All paths from the manifest are included in this repository.
- `execution_profile_validation/` contains paired full 20-round baseline CSVs. `execution_profile_validation.json` records their exact non-time agreement and measured speed factors.
- `environment.txt` records installed dependency versions; `completion.json` and `coverage.csv` establish final coverage.

## Findings and boundaries

Reference baseline, 5 clients and ring, mean ± sample SD across three seeds:

| Dataset | IID accuracy % | non-IID accuracy % |
| --- | ---: | ---: |
| MNIST | 92.51 ± 0.02 | 65.62 ± 2.10 |
| Fashion-MNIST | 83.17 ± 0.04 | 48.37 ± 1.58 |
| CIFAR-10 | 43.93 ± 0.71 | 23.30 ± 0.74 |

Across 288 matched protected/baseline validation comparisons, the maximum absolute accuracy difference is 0.23 percentage points. This is descriptive evidence and does not prove statistical equivalence or privacy.

Adaptive hybrid at ratio 0.4 reduces **HE processing time only** by about 60% compared with selective HE, using 22 matching cached_gpu pairs per dataset. Mean per-pair calculated communication reductions are 26.8% for MNIST/Fashion-MNIST and 10.3% for CIFAR-10. Whole-training speed and privacy equivalence do not follow from these percentages.

Sensitivity is exploratory (one seed). Increasing ratio 0.2 to 1.0 increases HE time by about 4.5–5.5× while the largest observed accuracy spread is 0.084 percentage points. All 12 network demos pass, with equal baseline/masking accuracy in each matched dataset/split; these are localhost functionality checks with a small training budget.

Validation and sensitivity execute clients serially in one process, with calculated model traffic. Network measurements record actual local HTTP sent plus received bytes. Do not aggregate these workflows together or mix their communication accounting. Keep legacy and cached_gpu timing means separate. Attack resistance, collusion, dropout behavior, distributed keys and physical networks require separate evaluation. Historical audit and Docker demonstrations elsewhere in the repository are separate from the 402 learning runs.

## Final artifacts

- [Interactive offline dashboard](../../dashboard/README.md)
- [Final presentation](../../docs/Secure_DFL_Thesis_Presentation_UPDATED.pptx): 38 slides, 27 native editable charts
- [Final technical report](../../docs/Secure_DFL_Technical_Report_COMPLETE_WITH_PLATFORM_FINAL.docx): 45 pages, 20 tables, 26 figures

## Validation

From `platform_mvp/`, run `python -m unittest discover -s tests -v` with the repository environment. All 15 tests passed, including the CUDA pixel/order/weight/loss/accuracy regression. Dashboard calculations were reconciled with the raw campaign summaries and final report; filters, source inspection, normal/narrow layouts and workflow counts were checked in the browser.
