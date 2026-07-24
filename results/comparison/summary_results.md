# DFL Experiment Comparison

This report compares final accuracy, loss, communication, timing, and masking behavior across saved DFL experiments.

| experiment_name | method | split | final_accuracy_percent | final_test_loss | final_train_loss | communication_mib_per_round | avg_round_time_seconds | avg_masking_time_seconds | avg_seed_overhead_bytes | max_cancellation_error | avg_he_encryption_time_seconds | avg_he_aggregation_time_seconds | avg_he_decryption_time_seconds | avg_he_total_time_seconds | he_ciphertext_bytes | he_num_encrypted_values | he_ciphertext_expansion_ratio | avg_adaptive_he_targets_count | avg_adaptive_he_target_ratio_actual | avg_adaptive_risk_score | max_adaptive_risk_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_iid_5c_20r_b32 | baseline | iid | 92.3640 | 0.2700 | 0.2801 | 3.8822 | 7.3663 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| masking_iid_5c_20r_b32 | simple_masking | iid | 92.3640 | 0.2700 | 0.2801 | 7.7644 | 7.2064 | 0.0050 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pairwise_masking_iid_5c_20r_b32 | pairwise_masking | iid | 92.3640 | 0.2700 | 0.2801 | 3.8827 | 7.7767 | 0.0110 | 480.0000 | 3.166e-07 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| baseline_non_iid_5c_20r_b32 | baseline | non_iid | 62.1460 | 1.1989 | 0.1049 | 3.8822 | 7.8875 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| masking_non_iid_5c_20r_b32 | simple_masking | non_iid | 62.1460 | 1.1989 | 0.1049 | 7.7644 | 7.3381 | 0.0046 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| pairwise_masking_non_iid_5c_20r_b32 | pairwise_masking | non_iid | 62.1460 | 1.1989 | 0.1049 | 3.8827 | 7.6780 | 0.0112 | 480.0000 | 3.073e-07 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| selective_he_iid_5c_20r_b32 | selective_he | iid | 92.3660 | 0.2700 | 0.2801 | 7.0218 | 7.6916 | 0.0000 | 0.0000 | 0.0000 | 0.0444 | 0.0035 | 0.0049 | 0.0528 | 3343681.0000 | 19350.0000 | 64.8000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| selective_he_non_iid_5c_20r_b32 | selective_he | non_iid | 62.1460 | 1.1989 | 0.1049 | 7.0201 | 7.8471 | 0.0000 | 0.0000 | 0.0000 | 0.0457 | 0.0035 | 0.0050 | 0.0543 | 3341935.0000 | 19350.0000 | 64.7662 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| adaptive_hybrid_iid_5c_20r_b32 | adaptive_hybrid | iid | 92.3640 | 0.2700 | 0.2801 | 5.1374 | 8.1687 | 0.0126 | 480.0000 | 3.166e-07 | 0.0192 | 0.0015 | 0.0022 | 0.0230 | 1336273.0000 | 7740.0000 | 64.7419 | 2.0000 | 0.4000 | 0.2372 | 1.0128 |
| adaptive_hybrid_non_iid_5c_20r_b32 | adaptive_hybrid | non_iid | 62.1460 | 1.1989 | 0.1049 | 5.1374 | 7.6352 | 0.0124 | 480.0000 | 2.952e-07 | 0.0185 | 0.0015 | 0.0020 | 0.0220 | 1336314.0000 | 7740.0000 | 64.7439 | 2.0000 | 0.4000 | 0.6552 | 1.3977 |

## Automatic interpretation

- IID: Simple Masking communication is 7.7644 MiB/round versus 3.8822 for Baseline (2.00x).
- IID: Pairwise Masking communication is 3.8827 MiB/round versus 3.8822 for Baseline; its final accuracy matches Baseline within 0.0000 percentage points.
- IID: Pairwise cancellation error has average 2.769e-07 and maximum 3.166e-07.
- IID: Selective HE communication is 7.0218 MiB/round versus 3.8822 for Baseline, with 0.0020 percentage points final-accuracy difference.
- IID: Adaptive Hybrid communication is 5.1374 MiB/round versus 3.8822 for Baseline, using an average of 2.00 HE targets with 0.0000 percentage points final-accuracy difference.
- Non-IID: Simple Masking communication is 7.7644 MiB/round versus 3.8822 for Baseline (2.00x).
- Non-IID: Pairwise Masking communication is 3.8827 MiB/round versus 3.8822 for Baseline; its final accuracy matches Baseline within 0.0000 percentage points.
- Non-IID: Pairwise cancellation error has average 2.711e-07 and maximum 3.073e-07.
- Non-IID: Selective HE communication is 7.0201 MiB/round versus 3.8822 for Baseline, with 0.0000 percentage points final-accuracy difference.
- Non-IID: Adaptive Hybrid communication is 5.1374 MiB/round versus 3.8822 for Baseline, using an average of 2.00 HE targets with 0.0000 percentage points final-accuracy difference.
