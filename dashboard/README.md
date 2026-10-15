# Results dashboard

Download `secure-dfl-dashboard.html` and open it in a browser. The file contains the complete reviewed snapshot and runtime; it works offline without a Python or Node server. GitHub's file viewer does not execute the interactive page.

The full campaign has 402 completed runs: 360 validation, 30 sensitivity and 12 local HTTP network demos. Whole-campaign totals remain visible independently of the selected-scope cards. Filters, charts, source inspection and tables use the selected population.

Accuracy, loss and calculated communication combine numerically validated execution profiles at the same configuration. Timing statistics retain separate `legacy` and `cached_gpu` groups. Validation uses three seeds and sample SD. Sensitivity and network demos use one seed; their SD is unavailable.

The matched HE chart compares adaptive ratio 0.4 with selective HE using only matching cached_gpu validation runs. Its approximately 60% time reduction covers HE processing only. The source definitions and methodological notes explain the scope and limitations.

The authoritative source CSVs and manifests are in [the campaign directory](../results/campaign_20261014/README.md). This HTML is the final snapshot; it does not start or rerun experiments.
