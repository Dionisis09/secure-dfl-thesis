"""Metric persistence and plotting for DFL experiments."""

from pathlib import Path
from typing import Dict, List, Union

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


MetricValue = Union[str, int, float]


class MetricsLogger:
    """Collect round-level experiment measurements and save them as CSV."""

    def __init__(self) -> None:
        self.metrics: List[Dict[str, MetricValue]] = []

    def log(
        self,
        round_number: int,
        avg_train_loss: float,
        avg_test_loss: float,
        avg_test_accuracy: float,
        communication_bytes: int,
        round_time_seconds: float,
        masking_time_seconds: float = 0.0,
        masking_overhead_bytes: int = 0,
        seed_overhead_bytes: int = 0,
        total_communication_bytes: int = 0,
        pairwise_masking_cancellation_error: float = 0.0,
        security_mode: str = "none",
        he_encryption_time_seconds: float = 0.0,
        he_aggregation_time_seconds: float = 0.0,
        he_decryption_time_seconds: float = 0.0,
        he_total_time_seconds: float = 0.0,
        he_ciphertext_bytes: int = 0,
        he_num_encrypted_values: int = 0,
        he_selected_param_count: int = 0,
        he_selected_param_names: str = "",
        he_plain_selected_bytes: int = 0,
        he_ciphertext_expansion_ratio: float = 0.0,
        he_reconstruction_max_error: float = 0.0,
        adaptive_policy: str = "",
        adaptive_he_targets_count: int = 0,
        adaptive_pairwise_targets_count: int = 0,
        adaptive_he_target_ratio_actual: float = 0.0,
        adaptive_avg_risk_score: float = 0.0,
        adaptive_max_risk_score: float = 0.0,
        adaptive_min_risk_score: float = 0.0,
        adaptive_selected_targets: str = "",
        adaptive_threshold_used: float = 0.0,
    ) -> None:
        if total_communication_bytes == 0:
            total_communication_bytes = communication_bytes + masking_overhead_bytes
        self.metrics.append(
            {
                "round": round_number,
                "security_mode": security_mode,
                "avg_train_loss": avg_train_loss,
                "avg_test_loss": avg_test_loss,
                "avg_test_accuracy": avg_test_accuracy,
                "communication_bytes": communication_bytes,
                "masking_time_seconds": masking_time_seconds,
                "masking_overhead_bytes": masking_overhead_bytes,
                "seed_overhead_bytes": seed_overhead_bytes,
                "total_communication_bytes": total_communication_bytes,
                "pairwise_masking_cancellation_error": (
                    pairwise_masking_cancellation_error
                ),
                "he_encryption_time_seconds": he_encryption_time_seconds,
                "he_aggregation_time_seconds": he_aggregation_time_seconds,
                "he_decryption_time_seconds": he_decryption_time_seconds,
                "he_total_time_seconds": he_total_time_seconds,
                "he_ciphertext_bytes": he_ciphertext_bytes,
                "he_num_encrypted_values": he_num_encrypted_values,
                "he_selected_param_count": he_selected_param_count,
                "he_selected_param_names": he_selected_param_names,
                "he_plain_selected_bytes": he_plain_selected_bytes,
                "he_ciphertext_expansion_ratio": he_ciphertext_expansion_ratio,
                "he_reconstruction_max_error": he_reconstruction_max_error,
                "adaptive_policy": adaptive_policy,
                "adaptive_he_targets_count": adaptive_he_targets_count,
                "adaptive_pairwise_targets_count": adaptive_pairwise_targets_count,
                "adaptive_he_target_ratio_actual": adaptive_he_target_ratio_actual,
                "adaptive_avg_risk_score": adaptive_avg_risk_score,
                "adaptive_max_risk_score": adaptive_max_risk_score,
                "adaptive_min_risk_score": adaptive_min_risk_score,
                "adaptive_selected_targets": adaptive_selected_targets,
                "adaptive_threshold_used": adaptive_threshold_used,
                "round_time_seconds": round_time_seconds,
            }
        )

    def save_csv(self, save_path: str) -> None:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(self.metrics).to_csv(path, index=False)


def _prepare_plot(metrics: List[Dict[str, float]], save_path: str):
    if not metrics:
        raise ValueError("cannot plot an empty metrics collection")
    path = Path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rounds = [int(item["round"]) for item in metrics]
    return rounds, path


def _finish_plot(path: Path) -> None:
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def plot_accuracy(metrics: List[Dict[str, float]], save_path: str) -> None:
    rounds, path = _prepare_plot(metrics, save_path)
    plt.figure()
    plt.plot(rounds, [item["avg_test_accuracy"] for item in metrics], marker="o")
    plt.xlabel("Communication round")
    plt.ylabel("Average test accuracy (%)")
    plt.title("Decentralized FL Test Accuracy")
    _finish_plot(path)


def plot_loss(metrics: List[Dict[str, float]], save_path: str) -> None:
    rounds, path = _prepare_plot(metrics, save_path)
    plt.figure()
    plt.plot(rounds, [item["avg_train_loss"] for item in metrics], label="Train")
    plt.plot(rounds, [item["avg_test_loss"] for item in metrics], label="Test")
    plt.xlabel("Communication round")
    plt.ylabel("Average loss")
    plt.title("Decentralized FL Loss")
    plt.legend()
    _finish_plot(path)


def plot_round_time(metrics: List[Dict[str, float]], save_path: str) -> None:
    rounds, path = _prepare_plot(metrics, save_path)
    plt.figure()
    plt.plot(rounds, [item["round_time_seconds"] for item in metrics], marker="o")
    plt.xlabel("Communication round")
    plt.ylabel("Time (seconds)")
    plt.title("Round Duration")
    _finish_plot(path)


def plot_communication(metrics: List[Dict[str, float]], save_path: str) -> None:
    rounds, path = _prepare_plot(metrics, save_path)
    per_round_bytes = [item["total_communication_bytes"] for item in metrics]
    cumulative_megabytes = np.cumsum(per_round_bytes) / (1024**2)
    plt.figure()
    plt.plot(rounds, cumulative_megabytes, marker="o")
    plt.xlabel("Communication round")
    plt.ylabel("Cumulative communication (MiB)")
    plt.title("Total Model Exchange Cost")
    _finish_plot(path)
