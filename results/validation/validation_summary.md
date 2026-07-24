# Part 5 - Robustness and Validation Experiments

## 1. Purpose

These experiments check whether the main observations remain similar across seeds, client counts, topologies and data splits. They are robustness checks, not formal proofs.

## 2. Experiment grid

| seeds | clients | topologies | splits | modes | planned_runs |
| --- | --- | --- | --- | --- | --- |
| 1,2,3 | 5 | ring | iid,non_iid | none,pairwise_masking,selective_he,adaptive_hybrid | 24 |

## 3. Completed runs

| experiment_name | final_accuracy_percent | communication_mib_per_round | avg_round_time_seconds |
| --- | --- | --- | --- |
| validation_none_iid_ring_5c_20r_b32_seed1 | 92.5180 | 3.8822 | 7.6810 |
| validation_pairwise_masking_iid_ring_5c_20r_b32_seed1 | 92.5220 | 3.8827 | 7.2915 |
| validation_selective_he_iid_ring_5c_20r_b32_seed1 | 92.5180 | 7.0210 | 7.4514 |
| validation_adaptive_hybrid_iid_ring_5c_20r_b32_seed1 | 92.5200 | 5.1384 | 7.6711 |
| validation_none_non_iid_ring_5c_20r_b32_seed1 | 65.0480 | 3.8822 | 7.6743 |
| validation_pairwise_masking_non_iid_ring_5c_20r_b32_seed1 | 65.0480 | 3.8827 | 7.6698 |
| validation_selective_he_non_iid_ring_5c_20r_b32_seed1 | 65.0480 | 7.0210 | 7.5088 |
| validation_adaptive_hybrid_non_iid_ring_5c_20r_b32_seed1 | 65.0480 | 5.1383 | 7.4582 |
| validation_none_iid_ring_5c_20r_b32_seed2 | 92.5240 | 3.8822 | 7.5379 |
| validation_pairwise_masking_iid_ring_5c_20r_b32_seed2 | 92.5220 | 3.8827 | 7.2459 |
| validation_selective_he_iid_ring_5c_20r_b32_seed2 | 92.5240 | 7.0209 | 7.1358 |
| validation_adaptive_hybrid_iid_ring_5c_20r_b32_seed2 | 92.5240 | 5.1382 | 7.2212 |
| validation_none_non_iid_ring_5c_20r_b32_seed2 | 63.8600 | 3.8822 | 7.1762 |
| validation_pairwise_masking_non_iid_ring_5c_20r_b32_seed2 | 63.8600 | 3.8827 | 7.1127 |
| validation_selective_he_non_iid_ring_5c_20r_b32_seed2 | 63.8600 | 7.0212 | 7.1474 |
| validation_adaptive_hybrid_non_iid_ring_5c_20r_b32_seed2 | 63.8600 | 5.1381 | 7.1341 |
| validation_none_iid_ring_5c_20r_b32_seed3 | 92.4860 | 3.8822 | 7.0760 |
| validation_pairwise_masking_iid_ring_5c_20r_b32_seed3 | 92.4860 | 3.8827 | 7.1512 |
| validation_selective_he_iid_ring_5c_20r_b32_seed3 | 92.4860 | 7.0209 | 7.2494 |
| validation_adaptive_hybrid_iid_ring_5c_20r_b32_seed3 | 92.4860 | 5.1381 | 7.3635 |
| validation_none_non_iid_ring_5c_20r_b32_seed3 | 67.9420 | 3.8822 | 7.0431 |
| validation_pairwise_masking_non_iid_ring_5c_20r_b32_seed3 | 67.9420 | 3.8827 | 7.0871 |
| validation_selective_he_non_iid_ring_5c_20r_b32_seed3 | 67.9420 | 7.0208 | 7.6636 |
| validation_adaptive_hybrid_non_iid_ring_5c_20r_b32_seed3 | 67.9420 | 5.1383 | 7.2580 |

## 4. Grouped results mean ± std

| method | split | topology | clients | runs | accuracy mean ± std | test loss mean ± std | communication MiB mean ± std | round time mean ± std |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | IID | ring | 5 | 3 | 92.509 ± 0.020 | 0.2686 ± 0.0010 | 3.8822 ± 0.0000 | 7.4316 ± 0.3162 |
| Pairwise Masking | IID | ring | 5 | 3 | 92.510 ± 0.021 | 0.2686 ± 0.0010 | 3.8827 ± 0.0000 | 7.2295 ± 0.0715 |
| Selective HE | IID | ring | 5 | 3 | 92.509 ± 0.020 | 0.2686 ± 0.0010 | 7.0209 ± 0.0001 | 7.2789 ± 0.1598 |
| Adaptive Hybrid | IID | ring | 5 | 3 | 92.510 ± 0.021 | 0.2686 ± 0.0010 | 5.1382 ± 0.0001 | 7.4186 ± 0.2299 |
| Baseline | Non-IID | ring | 5 | 3 | 65.617 ± 2.100 | 1.0595 ± 0.0481 | 3.8822 ± 0.0000 | 7.2979 ± 0.3327 |
| Pairwise Masking | Non-IID | ring | 5 | 3 | 65.617 ± 2.100 | 1.0595 ± 0.0481 | 3.8827 ± 0.0000 | 7.2898 ± 0.3293 |
| Selective HE | Non-IID | ring | 5 | 3 | 65.617 ± 2.100 | 1.0595 ± 0.0481 | 7.0210 ± 0.0002 | 7.4399 ± 0.2649 |
| Adaptive Hybrid | Non-IID | ring | 5 | 3 | 65.617 ± 2.100 | 1.0595 ± 0.0481 | 5.1382 ± 0.0001 | 7.2835 ± 0.1635 |

## 5. Main observations

- The largest observed within-group accuracy standard deviation is 2.0996 percentage points. This is a robustness measurement, not a proof of stability.
- Adaptive Hybrid communication is between Pairwise Masking and Selective HE in 2/2 matched configurations.
- Selective HE has higher mean HE time than Adaptive Hybrid in 2/2 matched configurations.
- Mean IID accuracy exceeds mean non-IID accuracy by 26.8930 percentage points across available runs.
- More than one client count is needed to measure client-scaling effects.
- More than one topology is needed to measure topology effects.

## 6. Missing or failed runs

Missing CSV files:
- None

Failed commands:
- None

## 7. Limitations

The measurements come from a single-machine research prototype. Runtime can vary with system load, and the validation does not establish a formal privacy or security guarantee.
