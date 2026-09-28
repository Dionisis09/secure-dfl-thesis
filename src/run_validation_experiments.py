"""Run robustness experiments and summarize their saved DFL metrics."""

from __future__ import annotations

import argparse
import itertools
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_SECURITY_MODES = (
    "none,pairwise_masking,selective_he,adaptive_hybrid"
)
ALLOWED_SECURITY_MODES = {
    "none",
    "masking",
    "pairwise_masking",
    "selective_he",
    "adaptive_hybrid",
}
ALLOWED_DATASETS = {"mnist", "fashion_mnist", "fmnist", "cifar10"}
ALLOWED_TOPOLOGIES = {"ring", "fully_connected", "star", "random", "small_world"}
ALLOWED_SPLITS = {"iid", "non_iid"}
METHOD_ORDER = [
    "none",
    "masking",
    "pairwise_masking",
    "selective_he",
    "adaptive_hybrid",
]
METHOD_LABELS = {
    "none": "Baseline",
    "masking": "Simple Masking",
    "pairwise_masking": "Pairwise Masking",
    "selective_he": "Selective HE",
    "adaptive_hybrid": "Adaptive Hybrid",
}
SPLIT_LABELS = {"iid": "IID", "non_iid": "Non-IID"}

RUN_SUMMARY_COLUMNS = [
    "experiment_name",
    "seed",
    "dataset",
    "num_clients",
    "topology",
    "split_type",
    "security_mode",
    "final_accuracy_percent",
    "final_test_loss",
    "final_train_loss",
    "communication_mib_per_round",
    "avg_round_time_seconds",
    "avg_masking_time_seconds",
    "avg_he_total_time_seconds",
    "avg_he_encryption_time_seconds",
    "avg_he_decryption_time_seconds",
    "avg_seed_overhead_bytes",
    "max_cancellation_error",
    "avg_adaptive_he_targets_count",
    "avg_adaptive_he_target_ratio_actual",
]

GROUPED_COLUMNS = [
    "security_mode",
    "dataset",
    "split_type",
    "topology",
    "num_clients",
    "runs_count",
    "accuracy_mean",
    "accuracy_std",
    "test_loss_mean",
    "test_loss_std",
    "communication_mib_mean",
    "communication_mib_std",
    "round_time_mean",
    "round_time_std",
    "masking_time_mean",
    "he_total_time_mean",
    "he_total_time_std",
    "cancellation_error_max_mean",
    "adaptive_he_targets_mean",
]


@dataclass(frozen=True)
class ValidationExperiment:
    seed: int
    dataset: str
    num_clients: int
    topology: str
    split_type: str
    security_mode: str
    num_rounds: int
    batch_size: int
    adaptive_policy: str
    adaptive_he_target_ratio: float

    @property
    def name(self) -> str:
        dataset_token = "" if self.dataset == "mnist" else f"{self.dataset}_"
        return (
            f"validation_{self.security_mode}_{dataset_token}{self.split_type}_{self.topology}_"
            f"{self.num_clients}c_{self.num_rounds}r_b{self.batch_size}_"
            f"seed{self.seed}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Part 5 robustness and validation experiment runner"
    )
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--datasets", default="mnist")
    parser.add_argument("--num_clients_list", default="5,10")
    parser.add_argument("--topologies", default="ring,fully_connected")
    parser.add_argument("--split_types", default="iid,non_iid")
    parser.add_argument("--security_modes", default=DEFAULT_SECURITY_MODES)
    parser.add_argument(
        "--include_simple_masking",
        action="store_true",
        help="Add the masking mode to the requested security modes",
    )
    parser.add_argument("--num_rounds", type=int, default=20)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--adaptive_he_target_ratio", type=float, default=0.4)
    parser.add_argument(
        "--adaptive_policy",
        choices=["topk_risk", "threshold", "periodic"],
        default="topk_risk",
    )
    parser.add_argument("--skip_existing", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--max_runs", type=int, default=None)
    parser.add_argument("--output_dir", default="results/validation")
    return parser.parse_args()


def parse_csv_values(value: str, name: str) -> List[str]:
    values: List[str] = []
    for item in value.split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


def parse_positive_ints(value: str, name: str) -> List[int]:
    try:
        values = [int(item) for item in parse_csv_values(value, name)]
    except ValueError as error:
        raise ValueError(f"{name} must contain comma-separated integers") from error
    if any(item <= 0 for item in values):
        raise ValueError(f"{name} values must be greater than zero")
    return values


def validate_choices(values: Sequence[str], allowed: set[str], name: str) -> None:
    invalid = [value for value in values if value not in allowed]
    if invalid:
        raise ValueError(
            f"unsupported {name}: {', '.join(invalid)}; "
            f"allowed values: {', '.join(sorted(allowed))}"
        )


def resolve_project_path(value: str, project_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def build_experiments(args: argparse.Namespace) -> List[ValidationExperiment]:
    seeds = parse_positive_ints(args.seeds, "seeds")
    datasets = parse_csv_values(args.datasets, "datasets")
    client_counts = parse_positive_ints(args.num_clients_list, "num_clients_list")
    topologies = parse_csv_values(args.topologies, "topologies")
    split_types = parse_csv_values(args.split_types, "split_types")
    security_modes = parse_csv_values(args.security_modes, "security_modes")
    if args.include_simple_masking and "masking" not in security_modes:
        security_modes.append("masking")
    validate_choices(datasets, ALLOWED_DATASETS, "datasets")
    validate_choices(topologies, ALLOWED_TOPOLOGIES, "topologies")
    validate_choices(split_types, ALLOWED_SPLITS, "split_types")
    validate_choices(security_modes, ALLOWED_SECURITY_MODES, "security_modes")
    if args.num_rounds <= 0 or args.batch_size <= 0:
        raise ValueError("num_rounds and batch_size must be greater than zero")
    if not 0.0 <= args.adaptive_he_target_ratio <= 1.0:
        raise ValueError("adaptive_he_target_ratio must be between zero and one")
    if args.max_runs is not None and args.max_runs < 0:
        raise ValueError("max_runs cannot be negative")

    experiments = [
        ValidationExperiment(
            seed=seed,
            dataset=dataset,
            num_clients=num_clients,
            topology=topology,
            split_type=split_type,
            security_mode=security_mode,
            num_rounds=args.num_rounds,
            batch_size=args.batch_size,
            adaptive_policy=args.adaptive_policy,
            adaptive_he_target_ratio=args.adaptive_he_target_ratio,
        )
        for seed, dataset, num_clients, topology, split_type, security_mode in itertools.product(
            seeds, datasets, client_counts, topologies, split_types, security_modes
        )
    ]
    if args.max_runs is not None:
        experiments = experiments[: args.max_runs]
    return experiments


def command_for(experiment: ValidationExperiment, main_path: Path) -> List[str]:
    return [
        sys.executable,
        str(main_path),
        "--num_clients",
        str(experiment.num_clients),
        "--num_rounds",
        str(experiment.num_rounds),
        "--batch_size",
        str(experiment.batch_size),
        "--dataset",
        experiment.dataset,
        "--split_type",
        experiment.split_type,
        "--topology",
        experiment.topology,
        "--security_mode",
        experiment.security_mode,
        "--adaptive_policy",
        experiment.adaptive_policy,
        "--adaptive_he_target_ratio",
        str(experiment.adaptive_he_target_ratio),
        "--seed",
        str(experiment.seed),
        "--experiment_name",
        experiment.name,
    ]


def command_text(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command))


def numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def summarize_run(
    csv_path: Path, experiment: ValidationExperiment
) -> Dict[str, object]:
    frame = pd.read_csv(csv_path)
    if frame.empty:
        raise ValueError("metrics CSV contains no rows")
    if "round" in frame.columns:
        frame = frame.assign(
            _round=pd.to_numeric(frame["round"], errors="coerce")
        ).sort_values("_round", kind="stable")
    final = frame.iloc[-1]
    communication = numeric_series(frame, "total_communication_bytes", np.nan)
    if communication.isna().all():
        communication = numeric_series(frame, "communication_bytes", 0.0)
    else:
        fallback = numeric_series(frame, "communication_bytes", 0.0)
        communication = communication.fillna(fallback)

    def final_number(column: str) -> float:
        return float(pd.to_numeric(pd.Series([final.get(column, np.nan)]), errors="coerce").iloc[0])

    return {
        "experiment_name": experiment.name,
        "seed": experiment.seed,
        "dataset": experiment.dataset,
        "num_clients": experiment.num_clients,
        "topology": experiment.topology,
        "split_type": experiment.split_type,
        "security_mode": experiment.security_mode,
        "final_accuracy_percent": final_number("avg_test_accuracy"),
        "final_test_loss": final_number("avg_test_loss"),
        "final_train_loss": final_number("avg_train_loss"),
        "communication_mib_per_round": float(communication.mean() / (1024**2)),
        "avg_round_time_seconds": float(numeric_series(frame, "round_time_seconds").mean()),
        "avg_masking_time_seconds": float(numeric_series(frame, "masking_time_seconds").mean()),
        "avg_he_total_time_seconds": float(numeric_series(frame, "he_total_time_seconds").mean()),
        "avg_he_encryption_time_seconds": float(numeric_series(frame, "he_encryption_time_seconds").mean()),
        "avg_he_decryption_time_seconds": float(numeric_series(frame, "he_decryption_time_seconds").mean()),
        "avg_seed_overhead_bytes": float(numeric_series(frame, "seed_overhead_bytes").mean()),
        "max_cancellation_error": float(numeric_series(frame, "pairwise_masking_cancellation_error").max()),
        "avg_adaptive_he_targets_count": float(numeric_series(frame, "adaptive_he_targets_count").mean()),
        "avg_adaptive_he_target_ratio_actual": float(numeric_series(frame, "adaptive_he_target_ratio_actual").mean()),
    }


def build_grouped_summary(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(columns=GROUPED_COLUMNS)
    groups = summary.groupby(
        ["security_mode", "dataset", "split_type", "topology", "num_clients"],
        sort=False,
        dropna=False,
    )
    records: List[Dict[str, object]] = []
    for keys, frame in groups:
        mode, dataset, split, topology, clients = keys

        def mean(column: str) -> float:
            return float(pd.to_numeric(frame[column], errors="coerce").mean())

        def std(column: str) -> float:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            return float(values.std(ddof=1)) if len(values) > 1 else 0.0

        records.append(
            {
                "security_mode": mode,
                "dataset": dataset,
                "split_type": split,
                "topology": topology,
                "num_clients": int(clients),
                "runs_count": int(len(frame)),
                "accuracy_mean": mean("final_accuracy_percent"),
                "accuracy_std": std("final_accuracy_percent"),
                "test_loss_mean": mean("final_test_loss"),
                "test_loss_std": std("final_test_loss"),
                "communication_mib_mean": mean("communication_mib_per_round"),
                "communication_mib_std": std("communication_mib_per_round"),
                "round_time_mean": mean("avg_round_time_seconds"),
                "round_time_std": std("avg_round_time_seconds"),
                "masking_time_mean": mean("avg_masking_time_seconds"),
                "he_total_time_mean": mean("avg_he_total_time_seconds"),
                "he_total_time_std": std("avg_he_total_time_seconds"),
                "cancellation_error_max_mean": mean("max_cancellation_error"),
                "adaptive_he_targets_mean": mean("avg_adaptive_he_targets_count"),
            }
        )
    grouped = pd.DataFrame(records, columns=GROUPED_COLUMNS)
    mode_rank = {mode: index for index, mode in enumerate(METHOD_ORDER)}
    grouped["_mode_rank"] = grouped["security_mode"].map(mode_rank).fillna(999)
    grouped = grouped.sort_values(
        ["dataset", "split_type", "topology", "num_clients", "_mode_rank"]
    ).drop(columns="_mode_rank")
    return grouped.reset_index(drop=True)


def markdown_value(value: object) -> str:
    if pd.isna(value):
        return "NaN"
    if isinstance(value, (float, np.floating)):
        if value != 0 and abs(value) < 0.0001:
            return f"{value:.3e}"
        return f"{value:.4f}"
    return str(value).replace("|", "\\|")


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No completed validation runs were available._"
    header = "| " + " | ".join(frame.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    rows = [
        "| " + " | ".join(markdown_value(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def mean_std_markdown(grouped: pd.DataFrame) -> str:
    if grouped.empty:
        return "_No grouped results were available._"
    display = pd.DataFrame(
        {
            "method": grouped["security_mode"].map(METHOD_LABELS),
            "dataset": grouped["dataset"],
            "split": grouped["split_type"].map(SPLIT_LABELS),
            "topology": grouped["topology"],
            "clients": grouped["num_clients"],
            "runs": grouped["runs_count"],
            "accuracy mean ± std": grouped.apply(
                lambda r: f"{r['accuracy_mean']:.3f} ± {r['accuracy_std']:.3f}", axis=1
            ),
            "test loss mean ± std": grouped.apply(
                lambda r: f"{r['test_loss_mean']:.4f} ± {r['test_loss_std']:.4f}", axis=1
            ),
            "communication MiB mean ± std": grouped.apply(
                lambda r: f"{r['communication_mib_mean']:.4f} ± {r['communication_mib_std']:.4f}", axis=1
            ),
            "round time mean ± std": grouped.apply(
                lambda r: f"{r['round_time_mean']:.4f} ± {r['round_time_std']:.4f}", axis=1
            ),
        }
    )
    return dataframe_to_markdown(display)


def automatic_observations(summary: pd.DataFrame, grouped: pd.DataFrame) -> List[str]:
    observations: List[str] = []
    multi_seed = grouped[grouped["runs_count"] >= 2]
    if multi_seed.empty:
        observations.append(
            "Seed stability cannot be assessed yet because every available group has fewer than two runs."
        )
    else:
        max_std = float(multi_seed["accuracy_std"].max())
        observations.append(
            f"The largest observed within-group accuracy standard deviation is {max_std:.4f} percentage points. "
            "This is a robustness measurement, not a proof of stability."
        )

    pivot = grouped.pivot_table(
        index=["dataset", "split_type", "topology", "num_clients"],
        columns="security_mode",
        values=["communication_mib_mean", "he_total_time_mean"],
        aggfunc="mean",
    )
    between_checks: List[bool] = []
    he_checks: List[bool] = []
    for _, values in pivot.iterrows():
        try:
            pairwise = values[("communication_mib_mean", "pairwise_masking")]
            adaptive = values[("communication_mib_mean", "adaptive_hybrid")]
            selective = values[("communication_mib_mean", "selective_he")]
            if not any(pd.isna(item) for item in [pairwise, adaptive, selective]):
                between_checks.append(pairwise <= adaptive <= selective)
        except KeyError:
            pass
        try:
            adaptive_he = values[("he_total_time_mean", "adaptive_hybrid")]
            selective_he = values[("he_total_time_mean", "selective_he")]
            if not any(pd.isna(item) for item in [adaptive_he, selective_he]):
                he_checks.append(selective_he > adaptive_he)
        except KeyError:
            pass
    if between_checks:
        observations.append(
            f"Adaptive Hybrid communication is between Pairwise Masking and Selective HE in "
            f"{sum(between_checks)}/{len(between_checks)} matched configurations."
        )
    else:
        observations.append(
            "The available runs are insufficient for a matched Pairwise–Adaptive–Selective communication comparison."
        )
    if he_checks:
        observations.append(
            f"Selective HE has higher mean HE time than Adaptive Hybrid in "
            f"{sum(he_checks)}/{len(he_checks)} matched configurations."
        )
    else:
        observations.append(
            "The available runs are insufficient for a matched Selective HE–Adaptive Hybrid time comparison."
        )

    split_means = summary.groupby("split_type")["final_accuracy_percent"].mean()
    if {"iid", "non_iid"}.issubset(split_means.index):
        difference = float(split_means["iid"] - split_means["non_iid"])
        observations.append(
            f"Mean IID accuracy exceeds mean non-IID accuracy by {difference:.4f} percentage points across available runs."
        )
    else:
        observations.append(
            "Both IID and non-IID runs are required before their difficulty can be compared."
        )

    client_means = summary.groupby("num_clients")["communication_mib_per_round"].mean()
    if len(client_means) >= 2:
        low_clients, high_clients = client_means.index.min(), client_means.index.max()
        observations.append(
            f"Average communication changes from {client_means.loc[low_clients]:.4f} MiB/round at "
            f"{low_clients} clients to {client_means.loc[high_clients]:.4f} MiB/round at {high_clients} clients."
        )
    else:
        observations.append("More than one client count is needed to measure client-scaling effects.")

    topology_means = summary.groupby("topology")["communication_mib_per_round"].mean()
    if len(topology_means) >= 2:
        text = ", ".join(f"{name}: {value:.4f} MiB/round" for name, value in topology_means.items())
        observations.append(f"Observed mean communication by topology is {text}.")
    else:
        observations.append("More than one topology is needed to measure topology effects.")
    return observations


def save_reports(
    summary: pd.DataFrame,
    grouped: pd.DataFrame,
    experiments: Sequence[ValidationExperiment],
    missing: Sequence[str],
    failures: pd.DataFrame,
    output_dir: Path,
) -> None:
    summary.to_csv(output_dir / "validation_summary.csv", index=False)
    grouped.to_csv(output_dir / "validation_grouped_summary.csv", index=False)
    grouped_report = (
        "# Part 5 - Grouped Validation Results\n\n"
        "Values are reported as mean ± standard deviation across completed seeds. "
        "A single-run group has a displayed standard deviation of zero.\n\n"
        + mean_std_markdown(grouped)
        + "\n"
    )
    (output_dir / "validation_grouped_summary.md").write_text(
        grouped_report, encoding="utf-8"
    )

    grid_rows = pd.DataFrame(
        [
            {
                "seeds": ",".join(str(item) for item in sorted({e.seed for e in experiments})),
                "datasets": ",".join(sorted({e.dataset for e in experiments})),
                "clients": ",".join(str(item) for item in sorted({e.num_clients for e in experiments})),
                "topologies": ",".join(sorted({e.topology for e in experiments})),
                "splits": ",".join(sorted({e.split_type for e in experiments})),
                "modes": ",".join(dict.fromkeys(e.security_mode for e in experiments)),
                "planned_runs": len(experiments),
            }
        ]
    )
    completed_table = summary[
        ["experiment_name", "final_accuracy_percent", "communication_mib_per_round", "avg_round_time_seconds"]
    ] if not summary.empty else summary
    missing_lines = [f"- {name}" for name in missing] or ["- None"]
    failure_lines = (
        [f"- {row.experiment_name}: return code {row.return_code}" for row in failures.itertuples()]
        if not failures.empty
        else ["- None"]
    )
    observations = [f"- {line}" for line in automatic_observations(summary, grouped)]
    report = "\n".join(
        [
            "# Part 5 - Robustness and Validation Experiments",
            "",
            "## 1. Purpose",
            "",
            "These experiments check whether the main observations remain similar across seeds, client counts, topologies and data splits. They are robustness checks, not formal proofs.",
            "",
            "## 2. Experiment grid",
            "",
            dataframe_to_markdown(grid_rows),
            "",
            "## 3. Completed runs",
            "",
            dataframe_to_markdown(completed_table),
            "",
            "## 4. Grouped results mean ± std",
            "",
            mean_std_markdown(grouped),
            "",
            "## 5. Main observations",
            "",
            *observations,
            "",
            "## 6. Missing or failed runs",
            "",
            "Missing CSV files:",
            *missing_lines,
            "",
            "Failed commands:",
            *failure_lines,
            "",
            "## 7. Limitations",
            "",
            "The measurements come from a single-machine research prototype. Runtime can vary with system load, and the validation does not establish a formal privacy or security guarantee.",
            "",
        ]
    )
    (output_dir / "validation_summary.md").write_text(report, encoding="utf-8")


def ordered_modes(values: Iterable[str]) -> List[str]:
    present = set(values)
    return [mode for mode in METHOD_ORDER if mode in present]


def finish_plot(path: Path) -> None:
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def empty_plot(path: Path, title: str, message: str = "No completed data") -> None:
    plt.figure(figsize=(8, 5.5))
    plt.title(title)
    plt.text(0.5, 0.5, message, ha="center", va="center")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def split_bar_plot(
    summary: pd.DataFrame,
    value: str,
    ylabel: str,
    title: str,
    path: Path,
    modes: Sequence[str] | None = None,
) -> None:
    data = summary if modes is None else summary[summary["security_mode"].isin(modes)]
    if data.empty:
        empty_plot(path, title)
        return
    mode_values = ordered_modes(data["security_mode"])
    x = np.arange(len(mode_values))
    width = 0.36
    plt.figure(figsize=(9, 5.5))
    for offset, split in enumerate(["iid", "non_iid"]):
        means, errors = [], []
        for mode in mode_values:
            values = pd.to_numeric(
                data[(data["security_mode"] == mode) & (data["split_type"] == split)][value],
                errors="coerce",
            ).dropna()
            means.append(float(values.mean()) if len(values) else np.nan)
            errors.append(float(values.std(ddof=1)) if len(values) > 1 else 0.0)
        plt.bar(
            x + (offset - 0.5) * width,
            means,
            width,
            yerr=errors,
            capsize=4,
            label=SPLIT_LABELS[split],
        )
    plt.xticks(x, [METHOD_LABELS[mode] for mode in mode_values], rotation=15)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend()
    finish_plot(path)


def metric_by_clients_plot(summary: pd.DataFrame, value: str, ylabel: str, title: str, path: Path) -> None:
    if summary.empty:
        empty_plot(path, title)
        return
    plt.figure(figsize=(9, 5.5))
    for mode in ordered_modes(summary["security_mode"]):
        grouped = summary[summary["security_mode"] == mode].groupby("num_clients")[value].agg(["mean", "std"])
        if grouped.empty:
            continue
        errors = grouped["std"].fillna(0.0)
        plt.errorbar(grouped.index, grouped["mean"], yerr=errors, marker="o", capsize=4, label=METHOD_LABELS[mode])
    plt.xlabel("Number of clients")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def topology_plot(summary: pd.DataFrame, path: Path) -> None:
    title = "Validation Communication by Topology"
    if summary.empty:
        empty_plot(path, title)
        return
    modes = ordered_modes(summary["security_mode"])
    topologies = list(dict.fromkeys(summary["topology"]))
    x = np.arange(len(modes))
    width = 0.8 / max(1, len(topologies))
    plt.figure(figsize=(9, 5.5))
    for index, topology in enumerate(topologies):
        means = [
            summary[(summary["security_mode"] == mode) & (summary["topology"] == topology)]["communication_mib_per_round"].mean()
            for mode in modes
        ]
        plt.bar(x + (index - (len(topologies) - 1) / 2) * width, means, width, label=topology.replace("_", " ").title())
    plt.xticks(x, [METHOD_LABELS[mode] for mode in modes], rotation=15)
    plt.ylabel("Communication (MiB/round)")
    plt.title(title)
    plt.legend()
    finish_plot(path)


def tradeoff_plot(summary: pd.DataFrame, path: Path) -> None:
    title = "Adaptive Hybrid vs Selective HE Trade-off"
    data = summary[summary["security_mode"].isin(["selective_he", "adaptive_hybrid"])]
    if data.empty:
        empty_plot(path, title)
        return
    grouped = data.groupby(["security_mode", "split_type", "topology", "num_clients"])[
        ["communication_mib_per_round", "avg_he_total_time_seconds"]
    ].mean().reset_index()
    plt.figure(figsize=(9, 6))
    for mode in ordered_modes(grouped["security_mode"]):
        subset = grouped[grouped["security_mode"] == mode]
        plt.scatter(subset["communication_mib_per_round"], subset["avg_he_total_time_seconds"], s=55, label=METHOD_LABELS[mode])
        for item in subset.itertuples():
            label = f"{SPLIT_LABELS[item.split_type]}, {item.topology}, {item.num_clients}c"
            plt.annotate(label, (item.communication_mib_per_round, item.avg_he_total_time_seconds), fontsize=7, xytext=(4, 3), textcoords="offset points")
    plt.xlabel("Communication (MiB/round)")
    plt.ylabel("HE total time (seconds/round)")
    plt.title(title)
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def accuracy_distribution_plot(summary: pd.DataFrame, path: Path) -> None:
    title = "Validation Accuracy Distribution"
    if summary.empty:
        empty_plot(path, title)
        return
    data, labels = [], []
    for mode in ordered_modes(summary["security_mode"]):
        for split in ["iid", "non_iid"]:
            values = pd.to_numeric(
                summary[(summary["security_mode"] == mode) & (summary["split_type"] == split)]["final_accuracy_percent"],
                errors="coerce",
            ).dropna().to_numpy()
            if len(values):
                data.append(values)
                labels.append(f"{METHOD_LABELS[mode]}\n{SPLIT_LABELS[split]}")
    if not data:
        empty_plot(path, title)
        return
    plt.figure(figsize=(11, 6))
    plt.boxplot(data, tick_labels=labels, showmeans=True)
    plt.ylabel("Final accuracy (%)")
    plt.title(title)
    plt.xticks(rotation=20)
    finish_plot(path)


def create_plots(summary: pd.DataFrame, plots_dir: Path) -> List[Path]:
    plots_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "accuracy": plots_dir / "validation_accuracy_by_method.png",
        "communication": plots_dir / "validation_communication_by_method.png",
        "he_time": plots_dir / "validation_he_time_by_method.png",
        "accuracy_clients": plots_dir / "validation_accuracy_by_clients.png",
        "communication_clients": plots_dir / "validation_communication_by_clients.png",
        "topology": plots_dir / "validation_topology_communication.png",
        "splits": plots_dir / "validation_iid_vs_non_iid_accuracy.png",
        "tradeoff": plots_dir / "validation_adaptive_vs_selective_tradeoff.png",
        "distribution": plots_dir / "validation_accuracy_distribution.png",
    }
    split_bar_plot(summary, "final_accuracy_percent", "Final accuracy (%)", "Validation Accuracy by Method", paths["accuracy"])
    split_bar_plot(summary, "communication_mib_per_round", "Communication (MiB/round)", "Validation Communication by Method", paths["communication"])
    split_bar_plot(summary, "avg_he_total_time_seconds", "HE time (seconds/round)", "Validation HE Time by Method", paths["he_time"], ["selective_he", "adaptive_hybrid"])
    metric_by_clients_plot(summary, "final_accuracy_percent", "Final accuracy (%)", "Validation Accuracy by Client Count", paths["accuracy_clients"])
    metric_by_clients_plot(summary, "communication_mib_per_round", "Communication (MiB/round)", "Validation Communication by Client Count", paths["communication_clients"])
    topology_plot(summary, paths["topology"])
    split_bar_plot(summary, "final_accuracy_percent", "Final accuracy (%)", "IID vs Non-IID Validation Accuracy", paths["splits"])
    tradeoff_plot(summary, paths["tradeoff"])
    accuracy_distribution_plot(summary, paths["distribution"])
    return list(paths.values())


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    main_path = project_root / "src" / "main.py"
    logs_dir = project_root / "results" / "logs"
    output_dir = resolve_project_path(args.output_dir, project_root)
    all_experiments = build_experiments(args)

    print(f"Planned experiment count: {len(all_experiments)}", flush=True)
    commands = [(experiment, command_for(experiment, main_path)) for experiment in all_experiments]
    if args.dry_run:
        for index, (experiment, command) in enumerate(commands, start=1):
            print(f"[DRY RUN {index}/{len(commands)}] {experiment.name}", flush=True)
            print(command_text(command), flush=True)
        print("Dry run complete. No experiments were executed.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    failures: List[Dict[str, object]] = []
    for index, (experiment, command) in enumerate(commands, start=1):
        csv_path = logs_dir / f"{experiment.name}_metrics.csv"
        if args.skip_existing and csv_path.is_file():
            print(f"[SKIP {index}/{len(commands)}] Existing CSV: {csv_path}", flush=True)
            continue
        print(f"[RUN {index}/{len(commands)}] {experiment.name}", flush=True)
        print(command_text(command), flush=True)
        try:
            completed = subprocess.run(command, cwd=project_root, check=False)
            if completed.returncode != 0:
                failures.append(
                    {
                        "experiment_name": experiment.name,
                        "return_code": completed.returncode,
                        "command": command_text(command),
                    }
                )
                print(f"Warning: experiment failed with return code {completed.returncode}")
        except OSError as error:
            failures.append(
                {
                    "experiment_name": experiment.name,
                    "return_code": -1,
                    "command": command_text(command),
                    "error": str(error),
                }
            )
            print(f"Warning: could not start experiment: {error}")

    records: List[Dict[str, object]] = []
    missing: List[str] = []
    for experiment in all_experiments:
        csv_path = logs_dir / f"{experiment.name}_metrics.csv"
        if not csv_path.is_file():
            missing.append(experiment.name)
            continue
        try:
            records.append(summarize_run(csv_path, experiment))
        except (OSError, ValueError, pd.errors.ParserError) as error:
            missing.append(experiment.name)
            failures.append(
                {
                    "experiment_name": experiment.name,
                    "return_code": -2,
                    "command": "summary parsing",
                    "error": str(error),
                }
            )
            print(f"Warning: could not summarize {csv_path}: {error}")

    summary = pd.DataFrame(records, columns=RUN_SUMMARY_COLUMNS)
    grouped = build_grouped_summary(summary)
    failure_frame = pd.DataFrame(
        failures,
        columns=["experiment_name", "return_code", "command", "error"],
    )
    failure_frame.to_csv(output_dir / "validation_failures.csv", index=False)
    save_reports(summary, grouped, all_experiments, missing, failure_frame, output_dir)
    plot_paths = create_plots(summary, output_dir / "plots")

    print(f"Completed run count: {len(summary)}")
    print(f"Missing run count: {len(missing)}")
    print(f"Failed command count: {len(failure_frame)}")
    print(f"Validation summary: {output_dir / 'validation_summary.csv'}")
    print(f"Grouped summary: {output_dir / 'validation_grouped_summary.csv'}")
    print("Created plot files:")
    for path in plot_paths:
        print(f"  {path}")
    return 0 if failure_frame.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
