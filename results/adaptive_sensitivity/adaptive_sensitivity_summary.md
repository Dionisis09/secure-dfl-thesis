# Adaptive Hybrid HE Target Ratio Sensitivity

This report measures the security-efficiency trade-off produced by changing the fraction of target neighborhoods protected with Selective HE.

| experiment_name | split | he_target_ratio | final_accuracy_percent | final_test_loss | communication_mib_per_round | avg_round_time_seconds | avg_he_total_time_seconds | avg_he_encryption_time_seconds | avg_he_aggregation_time_seconds | avg_he_decryption_time_seconds | avg_masking_time_seconds | avg_he_targets_count | avg_pairwise_targets_count | avg_actual_he_target_ratio | avg_risk_score | max_risk_score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adaptive_hybrid_ratio_02_non_iid_5c_20r_b32 | non_iid | 0.2000 | 62.1460 | 1.1989 | 4.5105 | 7.0003 | 0.0104 | 0.0088 | 0.0007 | 0.0009 | 0.0116 | 1.0000 | 4.0000 | 0.2000 | 0.6552 | 1.3977 |
| adaptive_hybrid_ratio_04_non_iid_5c_20r_b32 | non_iid | 0.4000 | 62.1460 | 1.1989 | 5.1384 | 6.6499 | 0.0201 | 0.0170 | 0.0013 | 0.0018 | 0.0097 | 2.0000 | 3.0000 | 0.4000 | 0.6552 | 1.3977 |
| adaptive_hybrid_ratio_06_non_iid_5c_20r_b32 | non_iid | 0.6000 | 62.1460 | 1.1989 | 5.7660 | 6.9114 | 0.0312 | 0.0263 | 0.0021 | 0.0028 | 0.0101 | 3.0000 | 2.0000 | 0.6000 | 0.6552 | 1.3977 |
| adaptive_hybrid_ratio_08_non_iid_5c_20r_b32 | non_iid | 0.8000 | 62.1460 | 1.1989 | 6.3936 | 7.1709 | 0.0421 | 0.0356 | 0.0028 | 0.0038 | 0.0111 | 4.0000 | 1.0000 | 0.8000 | 0.6552 | 1.3977 |
| adaptive_hybrid_ratio_10_non_iid_5c_20r_b32 | non_iid | 1.0000 | 62.1460 | 1.1989 | 7.0216 | 7.1356 | 0.0510 | 0.0431 | 0.0034 | 0.0045 | 0.0108 | 5.0000 | 0.0000 | 1.0000 | 0.6552 | 1.3977 |

## Automatic interpretation

- Final accuracy varies by 0.0000 percentage points across the tested HE ratios.
- Communication increases by 2.5111 MiB/round from ratio 0.20 to 1.00.
- Average HE time increases by 0.0405 seconds/round over the same ratio range.
- Accuracy is stable within 1 percentage point. Ratio 0.20 offers the lowest measured overhead, while ratio 0.40 is a practical intermediate security-efficiency operating point.
