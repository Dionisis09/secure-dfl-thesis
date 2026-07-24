"""Compare saved baseline and masking DFL experiment metrics."""

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_EXPERIMENTS = [
    "baseline_iid_5c_20r_b32",
    "masking_iid_5c_20r_b32",
    "pairwise_masking_iid_5c_20r_b32",
    "baseline_non_iid_5c_20r_b32",
    "masking_non_iid_5c_20r_b32",
    "pairwise_masking_non_iid_5c_20r_b32",
]
OPTIONAL_SELECTIVE_HE_EXPERIMENTS = [
    "selective_he_iid_5c_20r_b32",
    "selective_he_non_iid_5c_20r_b32",
]
OPTIONAL_ADAPTIVE_HYBRID_EXPERIMENTS = [
    "adaptive_hybrid_iid_5c_20r_b32",
    "adaptive_hybrid_non_iid_5c_20r_b32",
]

SUMMARY_COLUMNS = [
    "experiment_name",
    "method",
    "split",
    "final_accuracy_percent",
    "final_test_loss",
    "final_train_loss",
    "communication_mib_per_round",
    "avg_round_time_seconds",
    "avg_masking_time_seconds",
    "avg_seed_overhead_bytes",
    "max_cancellation_error",
    "avg_he_encryption_time_seconds",
    "avg_he_aggregation_time_seconds",
    "avg_he_decryption_time_seconds",
    "avg_he_total_time_seconds",
    "he_ciphertext_bytes",
    "he_num_encrypted_values",
    "he_ciphertext_expansion_ratio",
    "avg_adaptive_he_targets_count",
    "avg_adaptive_he_target_ratio_actual",
    "avg_adaptive_risk_score",
    "max_adaptive_risk_score",
]

METHOD_ORDER = [
    "baseline",
    "simple_masking",
    "pairwise_masking",
    "selective_he",
    "adaptive_hybrid",
]
METHOD_LABELS = {
    "baseline": "Baseline",
    "simple_masking": "Simple Masking",
    "pairwise_masking": "Pairwise Masking",
    "selective_he": "Selective HE",
    "adaptive_hybrid": "Adaptive Hybrid",
}
SPLIT_ORDER = ["iid", "non_iid"]
SPLIT_LABELS = {"iid": "IID", "non_iid": "Non-IID"}


@dataclass
class ExperimentData:
    """One loaded experiment and its inferred metadata."""

    name: str
    method: str
    split: str
    metrics: pd.DataFrame
    avg_cancellation_error: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline and masking DFL result CSV files"
    )
    parser.add_argument("--logs_dir", default="results/logs")
    parser.add_argument("--output_dir", default="results/comparison")
    parser.add_argument(
        "--experiments",
        nargs="*",
        default=None,
        help="Experiment names without the _metrics.csv suffix",
    )
    parser.add_argument(
        "--include_adaptive_ratios",
        action="store_true",
        help="Also include discovered adaptive ratio sensitivity logs",
    )
    return parser.parse_args()


def resolve_project_path(path_value: str) -> Path:
    """Resolve relative CLI paths from the project root, not the caller's cwd."""

    path = Path(path_value)
    if path.is_absolute():
        return path
    project_root = Path(__file__).resolve().parent.parent
    return project_root / path


def infer_metadata(experiment_name: str) -> Tuple[str, str]:
    """Infer method and split while checking non-IID before IID."""

    if (
        experiment_name.startswith("adaptive_hybrid")
        or "_adaptive_hybrid" in experiment_name
        or "adaptive_ratio" in experiment_name
    ):
        method = "adaptive_hybrid"
    elif experiment_name.startswith("selective_he") or "_selective_he" in experiment_name:
        method = "selective_he"
    elif experiment_name.startswith("pairwise_masking"):
        method = "pairwise_masking"
    elif experiment_name.startswith("masking"):
        method = "simple_masking"
    elif experiment_name.startswith("baseline"):
        method = "baseline"
    else:
        method = "unknown"

    if "non_iid" in experiment_name:
        split = "non_iid"
    elif "_iid_" in experiment_name:
        split = "iid"
    else:
        split = "unknown"
    return method, split


def numeric_series(
    frame: pd.DataFrame, column: str, default: float
) -> pd.Series:
    """Read a numeric column or provide a same-length fallback series."""

    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def ordered_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort by numeric round when available, preserving rows otherwise."""

    ordered = frame.copy()
    if "round" in ordered.columns:
        ordered["_numeric_round"] = pd.to_numeric(
            ordered["round"], errors="coerce"
        )
        ordered = ordered.sort_values("_numeric_round", kind="stable")
        ordered = ordered.drop(columns="_numeric_round")
    return ordered.reset_index(drop=True)


def load_experiments(
    logs_dir: Path, experiment_names: Sequence[str]
) -> Tuple[List[ExperimentData], List[str]]:
    loaded: List[ExperimentData] = []
    warnings: List[str] = []

    for experiment_name in experiment_names:
        csv_path = logs_dir / f"{experiment_name}_metrics.csv"
        if not csv_path.is_file():
            message = f"Missing CSV: {csv_path}"
            warnings.append(message)
            print(f"Warning: {message}")
            continue

        try:
            metrics = pd.read_csv(csv_path)
        except (OSError, pd.errors.ParserError) as error:
            message = f"Could not read {csv_path}: {error}"
            warnings.append(message)
            print(f"Warning: {message}")
            continue

        if metrics.empty:
            message = f"CSV contains no metric rows: {csv_path}"
            warnings.append(message)
            print(f"Warning: {message}")
            continue

        method, split = infer_metadata(experiment_name)
        if method == "unknown" or split == "unknown":
            message = f"Could not fully infer metadata for: {experiment_name}"
            warnings.append(message)
            print(f"Warning: {message}")

        metrics = ordered_metrics(metrics)
        cancellation = numeric_series(
            metrics, "pairwise_masking_cancellation_error", 0.0
        )
        loaded.append(
            ExperimentData(
                name=experiment_name,
                method=method,
                split=split,
                metrics=metrics,
                avg_cancellation_error=float(cancellation.mean()),
            )
        )

    return loaded, warnings


def build_summary(experiments: Sequence[ExperimentData]) -> pd.DataFrame:
    records: List[Dict[str, object]] = []

    for experiment in experiments:
        metrics = experiment.metrics
        final_row = metrics.iloc[-1]

        total_communication = numeric_series(
            metrics, "total_communication_bytes", np.nan
        )
        model_communication = numeric_series(
            metrics, "communication_bytes", np.nan
        )
        total_communication = total_communication.fillna(model_communication)
        cancellation = numeric_series(
            metrics, "pairwise_masking_cancellation_error", 0.0
        )

        records.append(
            {
                "experiment_name": experiment.name,
                "method": experiment.method,
                "split": experiment.split,
                "final_accuracy_percent": pd.to_numeric(
                    pd.Series([final_row.get("avg_test_accuracy", np.nan)]),
                    errors="coerce",
                ).iloc[0],
                "final_test_loss": pd.to_numeric(
                    pd.Series([final_row.get("avg_test_loss", np.nan)]),
                    errors="coerce",
                ).iloc[0],
                "final_train_loss": pd.to_numeric(
                    pd.Series([final_row.get("avg_train_loss", np.nan)]),
                    errors="coerce",
                ).iloc[0],
                "communication_mib_per_round": (
                    float(total_communication.iloc[-1]) / (1024**2)
                ),
                "avg_round_time_seconds": float(
                    numeric_series(metrics, "round_time_seconds", np.nan).mean()
                ),
                "avg_masking_time_seconds": float(
                    numeric_series(metrics, "masking_time_seconds", 0.0).mean()
                ),
                "avg_seed_overhead_bytes": float(
                    numeric_series(metrics, "seed_overhead_bytes", 0.0).mean()
                ),
                "max_cancellation_error": float(cancellation.max()),
                "avg_he_encryption_time_seconds": float(
                    numeric_series(
                        metrics, "he_encryption_time_seconds", 0.0
                    ).mean()
                ),
                "avg_he_aggregation_time_seconds": float(
                    numeric_series(
                        metrics, "he_aggregation_time_seconds", 0.0
                    ).mean()
                ),
                "avg_he_decryption_time_seconds": float(
                    numeric_series(
                        metrics, "he_decryption_time_seconds", 0.0
                    ).mean()
                ),
                "avg_he_total_time_seconds": float(
                    numeric_series(metrics, "he_total_time_seconds", 0.0).mean()
                ),
                "he_ciphertext_bytes": float(
                    numeric_series(metrics, "he_ciphertext_bytes", 0.0).iloc[-1]
                ),
                "he_num_encrypted_values": float(
                    numeric_series(
                        metrics, "he_num_encrypted_values", 0.0
                    ).iloc[-1]
                ),
                "he_ciphertext_expansion_ratio": float(
                    numeric_series(
                        metrics, "he_ciphertext_expansion_ratio", 0.0
                    ).iloc[-1]
                ),
                "avg_adaptive_he_targets_count": float(
                    numeric_series(
                        metrics, "adaptive_he_targets_count", 0.0
                    ).mean()
                ),
                "avg_adaptive_he_target_ratio_actual": float(
                    numeric_series(
                        metrics, "adaptive_he_target_ratio_actual", 0.0
                    ).mean()
                ),
                "avg_adaptive_risk_score": float(
                    numeric_series(
                        metrics, "adaptive_avg_risk_score", 0.0
                    ).mean()
                ),
                "max_adaptive_risk_score": float(
                    numeric_series(
                        metrics, "adaptive_max_risk_score", 0.0
                    ).max()
                ),
            }
        )

    return pd.DataFrame(records, columns=SUMMARY_COLUMNS)


def format_markdown_value(value: object) -> str:
    if pd.isna(value):
        return "NaN"
    if isinstance(value, (float, np.floating)):
        if value != 0 and abs(value) < 0.0001:
            return f"{value:.3e}"
        return f"{value:.4f}"
    return str(value).replace("|", "\\|")


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No valid experiment CSV files were loaded._"

    header = "| " + " | ".join(frame.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = [
        "| "
        + " | ".join(format_markdown_value(value) for value in row)
        + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def find_summary_row(
    summary: pd.DataFrame, method: str, split: str
) -> Optional[pd.Series]:
    matches = summary[(summary["method"] == method) & (summary["split"] == split)]
    if matches.empty:
        return None
    return matches.iloc[0]


def build_interpretation(
    summary: pd.DataFrame, experiments: Sequence[ExperimentData]
) -> List[str]:
    lines: List[str] = []

    for split in SPLIT_ORDER:
        baseline = find_summary_row(summary, "baseline", split)
        simple = find_summary_row(summary, "simple_masking", split)
        pairwise = find_summary_row(summary, "pairwise_masking", split)
        split_label = SPLIT_LABELS[split]

        if baseline is not None and simple is not None:
            baseline_comm = float(baseline["communication_mib_per_round"])
            simple_comm = float(simple["communication_mib_per_round"])
            ratio = simple_comm / baseline_comm if baseline_comm else np.nan
            lines.append(
                f"- {split_label}: Simple Masking communication is "
                f"{simple_comm:.4f} MiB/round versus {baseline_comm:.4f} for "
                f"Baseline ({ratio:.2f}x)."
            )

        if baseline is not None and pairwise is not None:
            baseline_comm = float(baseline["communication_mib_per_round"])
            pairwise_comm = float(pairwise["communication_mib_per_round"])
            accuracy_difference = abs(
                float(pairwise["final_accuracy_percent"])
                - float(baseline["final_accuracy_percent"])
            )
            match_text = "matches" if accuracy_difference <= 0.01 else "differs from"
            lines.append(
                f"- {split_label}: Pairwise Masking communication is "
                f"{pairwise_comm:.4f} MiB/round versus {baseline_comm:.4f} for "
                f"Baseline; its final accuracy {match_text} Baseline within "
                f"{accuracy_difference:.4f} percentage points."
            )

            pairwise_data = next(
                (
                    item
                    for item in experiments
                    if item.method == "pairwise_masking" and item.split == split
                ),
                None,
            )
            max_error = float(pairwise["max_cancellation_error"])
            avg_error = (
                pairwise_data.avg_cancellation_error
                if pairwise_data is not None
                else np.nan
            )
            lines.append(
                f"- {split_label}: Pairwise cancellation error has average "
                f"{avg_error:.3e} and maximum {max_error:.3e}."
            )

        selective_he = find_summary_row(summary, "selective_he", split)
        if baseline is not None and selective_he is not None:
            baseline_comm = float(baseline["communication_mib_per_round"])
            he_comm = float(selective_he["communication_mib_per_round"])
            accuracy_difference = abs(
                float(selective_he["final_accuracy_percent"])
                - float(baseline["final_accuracy_percent"])
            )
            lines.append(
                f"- {split_label}: Selective HE communication is "
                f"{he_comm:.4f} MiB/round versus {baseline_comm:.4f} for "
                f"Baseline, with {accuracy_difference:.4f} percentage points "
                "final-accuracy difference."
            )

        adaptive = find_summary_row(summary, "adaptive_hybrid", split)
        if baseline is not None and adaptive is not None:
            baseline_comm = float(baseline["communication_mib_per_round"])
            adaptive_comm = float(adaptive["communication_mib_per_round"])
            accuracy_difference = abs(
                float(adaptive["final_accuracy_percent"])
                - float(baseline["final_accuracy_percent"])
            )
            lines.append(
                f"- {split_label}: Adaptive Hybrid communication is "
                f"{adaptive_comm:.4f} MiB/round versus {baseline_comm:.4f} for "
                f"Baseline, using an average of "
                f"{float(adaptive['avg_adaptive_he_targets_count']):.2f} HE "
                f"targets with {accuracy_difference:.4f} percentage points "
                "final-accuracy difference."
            )

    if not lines:
        lines.append("- Insufficient matching experiments for automatic comparison.")
    return lines


def save_summary_outputs(
    summary: pd.DataFrame,
    experiments: Sequence[ExperimentData],
    warnings: Sequence[str],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_dir / "summary_results.csv", index=False)

    markdown_parts = [
        "# DFL Experiment Comparison",
        "",
        (
            "This report compares final accuracy, loss, communication, timing, "
            "and masking behavior across saved DFL experiments."
        ),
        "",
        dataframe_to_markdown(summary),
        "",
        "## Automatic interpretation",
        "",
        *build_interpretation(summary, experiments),
    ]
    if warnings:
        markdown_parts.extend(
            ["", "## Warnings", "", *[f"- {warning}" for warning in warnings]]
        )
    (output_dir / "summary_results.md").write_text(
        "\n".join(markdown_parts) + "\n", encoding="utf-8"
    )


def prepare_axis(title: str, ylabel: str) -> Tuple[plt.Figure, plt.Axes]:
    figure, axis = plt.subplots(figsize=(9, 5.5))
    axis.set_title(title)
    axis.set_ylabel(ylabel)
    axis.grid(axis="y", alpha=0.3)
    return figure, axis


def save_figure(figure: plt.Figure, output_path: Path) -> None:
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def plot_grouped_metric(
    summary: pd.DataFrame,
    metric: str,
    title: str,
    ylabel: str,
    output_path: Path,
) -> None:
    figure, axis = prepare_axis(title, ylabel)
    available_methods = [
        method for method in METHOD_ORDER if method in set(summary.get("method", []))
    ]
    available_splits = [
        split for split in SPLIT_ORDER if split in set(summary.get("split", []))
    ]

    if not available_methods or not available_splits:
        axis.text(0.5, 0.5, "No matching experiment data", ha="center", va="center")
        axis.set_xticks([])
        save_figure(figure, output_path)
        return

    positions = np.arange(len(available_methods))
    width = 0.8 / len(available_splits)
    for split_index, split in enumerate(available_splits):
        values = []
        for method in available_methods:
            rows = summary[(summary["method"] == method) & (summary["split"] == split)]
            values.append(float(rows[metric].mean()) if not rows.empty else np.nan)
        offset = (split_index - (len(available_splits) - 1) / 2) * width
        axis.bar(
            positions + offset,
            values,
            width=width,
            label=SPLIT_LABELS[split],
        )

    axis.set_xticks(positions)
    axis.set_xticklabels([METHOD_LABELS[method] for method in available_methods])
    axis.legend()
    save_figure(figure, output_path)


def plot_cancellation_error(summary: pd.DataFrame, output_path: Path) -> None:
    figure, axis = prepare_axis(
        "Pairwise Masking Cancellation Error", "Maximum absolute error"
    )
    pairwise = summary[summary["method"] == "pairwise_masking"]
    splits = [split for split in SPLIT_ORDER if split in set(pairwise["split"])]
    if not splits:
        axis.text(0.5, 0.5, "No pairwise masking data", ha="center", va="center")
        axis.set_xticks([])
    else:
        values = [
            float(pairwise[pairwise["split"] == split]["max_cancellation_error"].max())
            for split in splits
        ]
        axis.bar([SPLIT_LABELS[split] for split in splits], values)
        axis.ticklabel_format(axis="y", style="scientific", scilimits=(0, 0))
    save_figure(figure, output_path)


def plot_he_total_time(summary: pd.DataFrame, output_path: Path) -> None:
    he_methods = summary[
        summary["method"].isin(["selective_he", "adaptive_hybrid"])
    ]
    plot_grouped_metric(
        he_methods,
        "avg_he_total_time_seconds",
        "HE Processing Time",
        "Average HE time (seconds/round)",
        output_path,
    )


def plot_adaptive_he_targets(
    experiments: Sequence[ExperimentData], output_path: Path
) -> None:
    figure, axis = prepare_axis(
        "Adaptive HE Targets by Round", "Number of HE targets"
    )
    plotted = False
    for split in SPLIT_ORDER:
        experiment = select_curve_experiment(experiments, "adaptive_hybrid", split)
        if experiment is None or "adaptive_he_targets_count" not in experiment.metrics:
            continue
        rounds = numeric_series(experiment.metrics, "round", np.nan)
        values = numeric_series(
            experiment.metrics, "adaptive_he_targets_count", np.nan
        )
        valid = rounds.notna() & values.notna()
        if valid.any():
            axis.plot(
                rounds[valid],
                values[valid],
                marker="o",
                label=SPLIT_LABELS[split],
            )
            plotted = True
    if plotted:
        axis.set_xlabel("Communication round")
        axis.legend()
    else:
        axis.text(0.5, 0.5, "No Adaptive Hybrid data", ha="center", va="center")
        axis.set_xticks([])
    save_figure(figure, output_path)


def plot_adaptive_risk_scores(
    experiments: Sequence[ExperimentData], output_path: Path
) -> None:
    figure, axis = prepare_axis("Adaptive Risk Scores by Round", "Risk score")
    plotted = False
    for split in SPLIT_ORDER:
        experiment = select_curve_experiment(experiments, "adaptive_hybrid", split)
        if experiment is None:
            continue
        rounds = numeric_series(experiment.metrics, "round", np.nan)
        for column, suffix, line_style in [
            ("adaptive_avg_risk_score", "Avg", "-"),
            ("adaptive_max_risk_score", "Max", "--"),
        ]:
            if column not in experiment.metrics:
                continue
            values = numeric_series(experiment.metrics, column, np.nan)
            valid = rounds.notna() & values.notna()
            if valid.any():
                axis.plot(
                    rounds[valid],
                    values[valid],
                    marker="o",
                    linestyle=line_style,
                    label=f"{SPLIT_LABELS[split]} {suffix}",
                )
                plotted = True
    if plotted:
        axis.set_xlabel("Communication round")
        axis.legend()
    else:
        axis.text(0.5, 0.5, "No Adaptive Hybrid data", ha="center", va="center")
        axis.set_xticks([])
    save_figure(figure, output_path)


def select_curve_experiment(
    experiments: Sequence[ExperimentData], method: str, split: str
) -> Optional[ExperimentData]:
    return next(
        (
            experiment
            for experiment in experiments
            if experiment.method == method and experiment.split == split
        ),
        None,
    )


def plot_curves(
    experiments: Sequence[ExperimentData],
    split: str,
    metric: str,
    title: str,
    ylabel: str,
    output_path: Path,
) -> None:
    figure, axis = prepare_axis(title, ylabel)
    plotted = False

    for method in METHOD_ORDER:
        experiment = select_curve_experiment(experiments, method, split)
        if experiment is None or metric not in experiment.metrics.columns:
            continue
        rounds = numeric_series(experiment.metrics, "round", np.nan)
        values = numeric_series(experiment.metrics, metric, np.nan)
        valid = rounds.notna() & values.notna()
        if valid.any():
            axis.plot(
                rounds[valid],
                values[valid],
                marker="o",
                markersize=3,
                label=METHOD_LABELS[method],
            )
            plotted = True

    if plotted:
        axis.set_xlabel("Communication round")
        axis.legend()
    else:
        axis.text(0.5, 0.5, "No matching curve data", ha="center", va="center")
        axis.set_xticks([])
    save_figure(figure, output_path)


def generate_plots(
    summary: pd.DataFrame,
    experiments: Sequence[ExperimentData],
    plots_dir: Path,
) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_grouped_metric(
        summary,
        "final_accuracy_percent",
        "Final Test Accuracy",
        "Final accuracy (%)",
        plots_dir / "final_accuracy_comparison.png",
    )
    plot_grouped_metric(
        summary,
        "communication_mib_per_round",
        "Communication per Round",
        "Communication (MiB/round)",
        plots_dir / "communication_comparison.png",
    )
    plot_grouped_metric(
        summary,
        "avg_round_time_seconds",
        "Average Round Time",
        "Average time (seconds)",
        plots_dir / "avg_round_time_comparison.png",
    )
    plot_cancellation_error(
        summary, plots_dir / "cancellation_error_comparison.png"
    )
    plot_he_total_time(summary, plots_dir / "he_total_time_comparison.png")
    plot_adaptive_he_targets(
        experiments, plots_dir / "adaptive_he_targets_by_round.png"
    )
    plot_adaptive_risk_scores(
        experiments, plots_dir / "risk_score_by_round.png"
    )

    for split in SPLIT_ORDER:
        split_label = SPLIT_LABELS[split]
        plot_curves(
            experiments,
            split,
            "avg_test_accuracy",
            f"{split_label} Test Accuracy by Round",
            "Average test accuracy (%)",
            plots_dir / f"accuracy_curves_{split}.png",
        )
        plot_curves(
            experiments,
            split,
            "avg_test_loss",
            f"{split_label} Test Loss by Round",
            "Average test loss",
            plots_dir / f"loss_curves_{split}.png",
        )


def main() -> None:
    args = parse_args()
    logs_dir = resolve_project_path(args.logs_dir)
    output_dir = resolve_project_path(args.output_dir)
    if args.experiments:
        experiment_names = args.experiments
    else:
        experiment_names = list(DEFAULT_EXPERIMENTS)
        experiment_names.extend(
            experiment_name
            for experiment_name in OPTIONAL_SELECTIVE_HE_EXPERIMENTS
            if (logs_dir / f"{experiment_name}_metrics.csv").is_file()
        )
        if args.include_adaptive_ratios:
            ratio_experiments = sorted(
                path.name[: -len("_metrics.csv")]
                for path in logs_dir.glob("*_ratio_[0-9]*_metrics.csv")
                if "adaptive" in path.name
            )
            experiment_names.extend(
                name for name in ratio_experiments if name not in experiment_names
            )
        experiment_names.extend(
            experiment_name
            for experiment_name in OPTIONAL_ADAPTIVE_HYBRID_EXPERIMENTS
            if (logs_dir / f"{experiment_name}_metrics.csv").is_file()
        )

    experiments, warnings = load_experiments(logs_dir, experiment_names)
    summary = build_summary(experiments)
    save_summary_outputs(summary, experiments, warnings, output_dir)
    generate_plots(summary, experiments, output_dir / "plots")

    print(f"Loaded experiments: {len(experiments)}/{len(experiment_names)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Summary CSV: {output_dir / 'summary_results.csv'}")
    print(f"Summary Markdown: {output_dir / 'summary_results.md'}")
    print(f"Plots directory: {output_dir / 'plots'}")


if __name__ == "__main__":
    main()
