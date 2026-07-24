# Part 5 - Grouped Validation Results

Values are reported as mean ± standard deviation across completed seeds. A single-run group has a displayed standard deviation of zero.

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
