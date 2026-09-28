"""Run and analyze Adaptive Hybrid experiments across HE target ratios."""

import argparse
import gc
import math
from pathlib import Path
from typing import Dict, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from compare_results import dataframe_to_markdown
from config import Config
from main import run_experiment


DEFAULT_RATIOS = "0.2,0.4,0.6,0.8,1.0"
SUMMARY_COLUMNS = [
    "experiment_name",
    "split",
    "he_target_ratio",
    "final_accuracy_percent",
    "final_test_loss",
    "communication_mib_per_round",
    "avg_round_time_seconds",
    "avg_he_total_time_seconds",
    "avg_he_encryption_time_seconds",
    "avg_he_aggregation_time_seconds",
    "avg_he_decryption_time_seconds",
    "avg_masking_time_seconds",
    "avg_he_targets_count",
    "avg_pairwise_targets_count",
    "avg_actual_he_target_ratio",
    "avg_risk_score",
    "max_risk_score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adaptive Hybrid HE-target-ratio sensitivity analysis"
    )
    parser.add_argument(
        "--split_type", choices=["iid", "non_iid"], default="iid"
    )
    parser.add_argument("--ratios", default=DEFAULT_RATIOS)
    parser.add_argument("--num_clients", type=int, default=5)
    parser.add_argument("--num_rounds", type=int, default=20)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument(
        "--dataset",
        choices=["mnist", "fashion_mnist", "fmnist", "cifar10"],
        default="mnist",
    )
    parser.add_argument(
        "--topology",
        choices=["ring", "fully_connected", "star", "random", "small_world"],
        default="ring",
    )
    parser.add_argument("--output_prefix", default="adaptive_ratio")
    parser.add_argument("--skip_existing", action="store_true")
    return parser.parse_args()


def parse_ratios(value: str) -> List[float]:
    """Parse, validate, and de-duplicate comma-separated ratios."""

    try:
        parsed = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise ValueError("ratios must be comma-separated numbers") from error
    if not parsed:
        raise ValueError("at least one HE target ratio is required")
    if any(not math.isfinite(ratio) or ratio <= 0.0 or ratio > 1.0 for ratio in parsed):
        raise ValueError("every HE target ratio must be greater than 0 and at most 1")

    ratios: List[float] = []
    for ratio in parsed:
        if not any(math.isclose(ratio, existing, abs_tol=1e-12) for existing in ratios):
            ratios.append(ratio)
    return ratios


def ratio_token(ratio: float) -> str:
    """Create required tokens such as 02, 04, ..., 10."""

    tenths = ratio * 10
    if math.isclose(tenths, round(tenths), abs_tol=1e-10):
        return f"{int(round(tenths)):02d}"
    decimal_text = f"{ratio:.6f}".rstrip("0").rstrip(".")
    return decimal_text.replace("0.", "0").replace(".", "")


def effective_prefix(output_prefix: str) -> str:
    """Map the specified default to the thesis-standard experiment prefix."""

    if not output_prefix or Path(output_prefix).name != output_prefix:
        raise ValueError("output_prefix must be a non-empty path-safe name")
    if output_prefix == "adaptive_ratio":
        return "adaptive_hybrid_ratio"
    return output_prefix


def build_experiment_name(
    prefix: str,
    ratio: float,
    dataset: str,
    split_type: str,
    num_clients: int,
    num_rounds: int,
    batch_size: int,
) -> str:
    dataset_token = "" if dataset == "mnist" else f"{dataset}_"
    return (
        f"{prefix}_{ratio_token(ratio)}_{dataset_token}{split_type}_"
        f"{num_clients}c_{num_rounds}r_b{batch_size}"
    )


def build_experiment_args(
    cli_args: argparse.Namespace, ratio: float, experiment_name: str
) -> argparse.Namespace:
    """Build the same argument namespace consumed by main.run_experiment."""

    defaults = Config()
    return argparse.Namespace(
        num_clients=cli_args.num_clients,
        num_rounds=cli_args.num_rounds,
        local_epochs=defaults.local_epochs,
        batch_size=cli_args.batch_size,
        lr=defaults.learning_rate,
        device=defaults.device,
        dataset=cli_args.dataset,
        split_type=cli_args.split_type,
        topology=cli_args.topology,
        security_mode="adaptive_hybrid",
        he_scheme=defaults.he_scheme,
        he_poly_modulus_degree=defaults.he_poly_modulus_degree,
        he_scale_bits=defaults.he_scale_bits,
        he_coeff_mod_bits=defaults.he_coeff_mod_bits,
        he_selected_layer=defaults.he_selected_layer,
        adaptive_policy="topk_risk",
        adaptive_he_target_ratio=ratio,
        adaptive_risk_threshold=defaults.adaptive_risk_threshold,
        adaptive_he_every_n_rounds=defaults.adaptive_he_every_n_rounds,
        adaptive_min_he_targets=defaults.adaptive_min_he_targets,
        experiment_name=experiment_name,
        seed=defaults.seed,
        enable_blockchain=False,
        enable_audit=False,
    )


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def summarize_experiment(
    csv_path: Path,
    experiment_name: str,
    split_type: str,
    ratio: float,
) -> Dict[str, object]:
    frame = pd.read_csv(csv_path)
    if frame.empty:
        raise ValueError(f"metrics CSV contains no rows: {csv_path}")
    if "round" in frame.columns:
        frame = frame.assign(
            _round=pd.to_numeric(frame["round"], errors="coerce")
        ).sort_values("_round", kind="stable")
    final = frame.iloc[-1]

    return {
        "experiment_name": experiment_name,
        "split": split_type,
        "he_target_ratio": ratio,
        "final_accuracy_percent": pd.to_numeric(
            pd.Series([final.get("avg_test_accuracy", np.nan)]), errors="coerce"
        ).iloc[0],
        "final_test_loss": pd.to_numeric(
            pd.Series([final.get("avg_test_loss", np.nan)]), errors="coerce"
        ).iloc[0],
        "communication_mib_per_round": float(
            numeric_series(frame, "total_communication_bytes").mean() / (1024**2)
        ),
        "avg_round_time_seconds": float(
            numeric_series(frame, "round_time_seconds").mean()
        ),
        "avg_he_total_time_seconds": float(
            numeric_series(frame, "he_total_time_seconds").mean()
        ),
        "avg_he_encryption_time_seconds": float(
            numeric_series(frame, "he_encryption_time_seconds").mean()
        ),
        "avg_he_aggregation_time_seconds": float(
            numeric_series(frame, "he_aggregation_time_seconds").mean()
        ),
        "avg_he_decryption_time_seconds": float(
            numeric_series(frame, "he_decryption_time_seconds").mean()
        ),
        "avg_masking_time_seconds": float(
            numeric_series(frame, "masking_time_seconds").mean()
        ),
        "avg_he_targets_count": float(
            numeric_series(frame, "adaptive_he_targets_count").mean()
        ),
        "avg_pairwise_targets_count": float(
            numeric_series(frame, "adaptive_pairwise_targets_count").mean()
        ),
        "avg_actual_he_target_ratio": float(
            numeric_series(frame, "adaptive_he_target_ratio_actual").mean()
        ),
        "avg_risk_score": float(
            numeric_series(frame, "adaptive_avg_risk_score").mean()
        ),
        "max_risk_score": float(
            numeric_series(frame, "adaptive_max_risk_score").max()
        ),
    }


def build_interpretation(summary: pd.DataFrame) -> List[str]:
    if summary.empty:
        return ["- No valid sensitivity experiments were available."]
    ordered = summary.sort_values("he_target_ratio")
    accuracy_range = (
        ordered["final_accuracy_percent"].max()
        - ordered["final_accuracy_percent"].min()
    )
    lines = [
        f"- Final accuracy varies by {accuracy_range:.4f} percentage points "
        "across the tested HE ratios."
    ]

    if len(ordered) >= 2:
        lowest = ordered.iloc[0]
        highest = ordered.iloc[-1]
        communication_increase = (
            highest["communication_mib_per_round"]
            - lowest["communication_mib_per_round"]
        )
        he_time_increase = (
            highest["avg_he_total_time_seconds"]
            - lowest["avg_he_total_time_seconds"]
        )
        lines.extend(
            [
                f"- Communication increases by {communication_increase:.4f} "
                f"MiB/round from ratio {lowest['he_target_ratio']:.2f} to "
                f"{highest['he_target_ratio']:.2f}.",
                f"- Average HE time increases by {he_time_increase:.4f} seconds/round "
                "over the same ratio range.",
            ]
        )

    if accuracy_range <= 1.0:
        lowest_ratio = float(ordered.iloc[0]["he_target_ratio"])
        middle = ordered.iloc[
            int(np.argmin(np.abs(ordered["he_target_ratio"].to_numpy() - 0.4)))
        ]
        lines.append(
            f"- Accuracy is stable within 1 percentage point. Ratio {lowest_ratio:.2f} "
            "offers the lowest measured overhead, while ratio "
            f"{float(middle['he_target_ratio']):.2f} is a practical intermediate "
            "security-efficiency operating point."
        )
    else:
        best_accuracy = ordered.loc[ordered["final_accuracy_percent"].idxmax()]
        lines.append(
            f"- The highest measured accuracy occurs at ratio "
            f"{float(best_accuracy['he_target_ratio']):.2f}; the preferred trade-off "
            "depends on the acceptable overhead."
        )
    return lines


def save_summary(summary: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "adaptive_sensitivity_summary.csv", index=False)
    markdown = [
        "# Adaptive Hybrid HE Target Ratio Sensitivity",
        "",
        (
            "This report measures the security-efficiency trade-off produced by "
            "changing the fraction of target neighborhoods protected with "
            "Selective HE."
        ),
        "",
        dataframe_to_markdown(summary),
        "",
        "## Automatic interpretation",
        "",
        *build_interpretation(summary),
    ]
    (output_dir / "adaptive_sensitivity_summary.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )


def save_line_plot(
    summary: pd.DataFrame,
    y_column: str,
    title: str,
    ylabel: str,
    save_path: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(8, 5.5))
    axis.plot(
        summary["he_target_ratio"],
        summary[y_column],
        marker="o",
        linewidth=2,
    )
    axis.set_title(title)
    axis.set_xlabel("Configured HE target ratio")
    axis.set_ylabel(ylabel)
    axis.set_xticks(summary["he_target_ratio"])
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(save_path, dpi=150)
    plt.close(figure)


def save_tradeoff_plot(
    summary: pd.DataFrame,
    x_column: str,
    y_column: str,
    title: str,
    xlabel: str,
    ylabel: str,
    save_path: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(8, 5.5))
    axis.scatter(summary[x_column], summary[y_column], s=70)
    max_x = summary[x_column].max()
    max_y = summary[y_column].max()
    for _, row in summary.iterrows():
        at_right_edge = math.isclose(row[x_column], max_x)
        at_top_edge = math.isclose(row[y_column], max_y)
        axis.annotate(
            f"r={row['he_target_ratio']:.1f}",
            (row[x_column], row[y_column]),
            xytext=(-6 if at_right_edge else 6, -8 if at_top_edge else 6),
            textcoords="offset points",
            horizontalalignment="right" if at_right_edge else "left",
            verticalalignment="top" if at_top_edge else "bottom",
        )
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(save_path, dpi=150)
    plt.close(figure)


def generate_plots(summary: pd.DataFrame, plots_dir: Path) -> None:
    if summary.empty:
        raise ValueError("cannot plot an empty sensitivity summary")
    plots_dir.mkdir(parents=True, exist_ok=True)
    ordered = summary.sort_values("he_target_ratio").reset_index(drop=True)
    save_line_plot(
        ordered,
        "final_accuracy_percent",
        "HE Target Ratio vs Final Accuracy",
        "Final accuracy (%)",
        plots_dir / "ratio_vs_accuracy.png",
    )
    save_line_plot(
        ordered,
        "communication_mib_per_round",
        "HE Target Ratio vs Communication",
        "Communication (MiB/round)",
        plots_dir / "ratio_vs_communication.png",
    )
    save_line_plot(
        ordered,
        "avg_he_total_time_seconds",
        "HE Target Ratio vs HE Time",
        "Average HE time (seconds/round)",
        plots_dir / "ratio_vs_he_time.png",
    )
    save_line_plot(
        ordered,
        "avg_round_time_seconds",
        "HE Target Ratio vs Round Time",
        "Average round time (seconds)",
        plots_dir / "ratio_vs_round_time.png",
    )
    save_line_plot(
        ordered,
        "avg_he_targets_count",
        "HE Target Ratio vs Protected Targets",
        "Average HE targets per round",
        plots_dir / "ratio_vs_he_targets.png",
    )
    save_tradeoff_plot(
        ordered,
        "communication_mib_per_round",
        "final_accuracy_percent",
        "Accuracy-Communication Trade-off",
        "Communication (MiB/round)",
        "Final accuracy (%)",
        plots_dir / "ratio_tradeoff_accuracy_communication.png",
    )
    save_tradeoff_plot(
        ordered,
        "avg_he_total_time_seconds",
        "communication_mib_per_round",
        "HE Time-Communication Trade-off",
        "Average HE time (seconds/round)",
        "Communication (MiB/round)",
        plots_dir / "ratio_tradeoff_he_time_communication.png",
    )


def validate_cli_args(args: argparse.Namespace) -> None:
    if args.num_clients <= 0 or args.num_rounds <= 0 or args.batch_size <= 0:
        raise ValueError("num_clients, num_rounds, and batch_size must be positive")


def main() -> None:
    args = parse_args()
    validate_cli_args(args)
    ratios = parse_ratios(args.ratios)
    prefix = effective_prefix(args.output_prefix)
    project_root = Path(__file__).resolve().parent.parent
    logs_dir = project_root / "results" / "logs"
    output_dir = project_root / "results" / "adaptive_sensitivity"
    logs_dir.mkdir(parents=True, exist_ok=True)

    experiment_specs = []
    for ratio in ratios:
        experiment_name = build_experiment_name(
            prefix=prefix,
            ratio=ratio,
            dataset=args.dataset,
            split_type=args.split_type,
            num_clients=args.num_clients,
            num_rounds=args.num_rounds,
            batch_size=args.batch_size,
        )
        csv_path = logs_dir / f"{experiment_name}_metrics.csv"
        experiment_specs.append((ratio, experiment_name, csv_path))

        if args.skip_existing and csv_path.is_file():
            print(f"Skipping existing experiment: {experiment_name}")
            continue

        print("\n" + "=" * 78)
        print(f"Running ratio {ratio:.2f}: {experiment_name}")
        print("=" * 78)
        experiment_args = build_experiment_args(args, ratio, experiment_name)
        run_experiment(experiment_args)
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    records = [
        summarize_experiment(csv_path, experiment_name, args.split_type, ratio)
        for ratio, experiment_name, csv_path in experiment_specs
        if csv_path.is_file()
    ]
    if not records:
        raise RuntimeError("no sensitivity experiment metrics were produced")

    summary = pd.DataFrame(records, columns=SUMMARY_COLUMNS)
    summary = summary.sort_values("he_target_ratio").reset_index(drop=True)
    save_summary(summary, output_dir)
    generate_plots(summary, output_dir / "plots")

    print("\nAdaptive sensitivity analysis complete")
    print(f"Experiments summarized: {len(summary)}/{len(experiment_specs)}")
    print(f"Summary CSV: {output_dir / 'adaptive_sensitivity_summary.csv'}")
    print(f"Summary Markdown: {output_dir / 'adaptive_sensitivity_summary.md'}")
    print(f"Plots directory: {output_dir / 'plots'}")


if __name__ == "__main__":
    main()
