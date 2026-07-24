"""Default experiment configuration for the baseline DFL system."""

from dataclasses import dataclass


@dataclass
class Config:
    """Configuration values shared by the command-line experiment runner."""

    num_clients: int = 5
    num_rounds: int = 20
    local_epochs: int = 1
    batch_size: int = 32
    learning_rate: float = 0.01
    dataset: str = "MNIST"
    split_type: str = "iid"
    topology: str = "ring"
    security_mode: str = "none"
    he_scheme: str = "ckks"
    he_poly_modulus_degree: int = 8192
    he_scale_bits: int = 40
    he_coeff_mod_bits: str = "60,40,40,60"
    he_selected_layer: str = "final"
    adaptive_policy: str = "topk_risk"
    adaptive_he_target_ratio: float = 0.4
    adaptive_risk_threshold: float = 0.0
    adaptive_he_every_n_rounds: int = 5
    adaptive_min_he_targets: int = 1
    experiment_name: str = "baseline_dfl"
    seed: int = 42
    # Prefer the NVIDIA GPU by default. The runner falls back to CPU only when
    # CUDA is unavailable on the host machine.
    device: str = "cuda"
    results_dir: str = "results"
    data_dir: str = "data"
