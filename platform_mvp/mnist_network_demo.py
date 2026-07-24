"""Run real PyTorch decentralized training over the Secure DFL node network.

This is a product-facing demo layer. It does not modify the thesis runner in
``src/main.py``. Each client trains locally, submits its model state to its own
node, receives a signed decentralized aggregate from the network, then continues
training from that aggregate.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import Dataset, Subset
from torchvision import datasets, transforms

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from client import Client  # noqa: E402
from data_utils import (  # noqa: E402
    create_iid_client_loaders,
    create_non_iid_client_loaders,
    get_mnist_datasets,
    get_test_loader,
    set_seed,
)
from model import SimpleMLP  # noqa: E402
from train_utils import evaluate_all_clients  # noqa: E402

from secure_dfl_platform.orchestrator import request_json, wait_for_nodes  # noqa: E402
from secure_dfl_platform.training_adapter import (  # noqa: E402
    model_to_payload,
    payload_to_model_state,
)


MAX_PAYLOAD_BYTES = 32 * 1024 * 1024


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def select_device(value: str) -> str:
    if value == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if value == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return value


def limited_subset(dataset: Dataset, max_samples: int | None, seed: int) -> Dataset:
    if max_samples is None or max_samples <= 0 or max_samples >= len(dataset):
        return dataset
    generator = torch.Generator().manual_seed(seed)
    indices = torch.randperm(len(dataset), generator=generator)[:max_samples].tolist()
    return Subset(dataset, indices)


def load_demo_datasets(
    *,
    dataset_name: str,
    data_dir: Path,
    max_train_samples: int | None,
    max_test_samples: int | None,
    seed: int,
) -> tuple[Dataset, Dataset]:
    if dataset_name == "mnist":
        train_dataset, test_dataset = get_mnist_datasets(str(data_dir))
    elif dataset_name == "fake":
        transform = transforms.ToTensor()
        train_size = max(max_train_samples or 300, 30)
        test_size = max(max_test_samples or 120, 30)
        train_dataset = datasets.FakeData(
            size=train_size,
            image_size=(1, 28, 28),
            num_classes=10,
            transform=transform,
            random_offset=seed,
        )
        test_dataset = datasets.FakeData(
            size=test_size,
            image_size=(1, 28, 28),
            num_classes=10,
            transform=transform,
            random_offset=seed + 10_000,
        )
        train_dataset.targets = torch.tensor(  # type: ignore[attr-defined]
            [int(train_dataset[index][1]) for index in range(len(train_dataset))],
            dtype=torch.long,
        )
        test_dataset.targets = torch.tensor(  # type: ignore[attr-defined]
            [int(test_dataset[index][1]) for index in range(len(test_dataset))],
            dtype=torch.long,
        )
    else:
        raise ValueError(f"unsupported dataset: {dataset_name}")

    train_dataset = limited_subset(train_dataset, max_train_samples, seed)
    test_dataset = limited_subset(test_dataset, max_test_samples, seed + 1)
    return train_dataset, test_dataset


def build_peer_urls(nodes: Mapping[str, str], node_id: str, topology: str) -> dict[str, str]:
    ordered = sorted(nodes)
    if topology == "full":
        return {peer_id: url for peer_id, url in nodes.items() if peer_id != node_id}
    if topology == "ring":
        index = ordered.index(node_id)
        neighbors = {
            ordered[(index - 1) % len(ordered)],
            ordered[(index + 1) % len(ordered)],
        }
        neighbors.discard(node_id)
        return {peer_id: nodes[peer_id] for peer_id in sorted(neighbors)}
    raise ValueError(f"unsupported topology: {topology}")


def start_nodes(
    *,
    nodes: Mapping[str, str],
    ports: Mapping[str, int],
    topology: str,
    experiment_id: str,
    admin_token: str,
    runtime_dir: Path,
    min_peer_updates_to_finalize: int | None,
    security_mode: str,
) -> list[subprocess.Popen]:
    processes: list[subprocess.Popen] = []
    for node_id in sorted(nodes):
        env = os.environ.copy()
        env.update(
            {
                "DFL_NODE_ID": node_id,
                "DFL_HOST": "127.0.0.1",
                "DFL_PORT": str(ports[node_id]),
                "DFL_EXPERIMENT_ID": experiment_id,
                "DFL_PEERS_JSON": json.dumps(build_peer_urls(nodes, node_id, topology)),
                "DFL_DATA_DIR": str(runtime_dir / node_id),
                "DFL_ADMIN_TOKEN": admin_token,
                "DFL_DEMO_IDENTITY_SEED": f"{experiment_id}-demo-identities",
                "DFL_MAX_PAYLOAD_BYTES": str(MAX_PAYLOAD_BYTES),
                "DFL_SECURITY_MODE": security_mode,
            }
        )
        if min_peer_updates_to_finalize is not None:
            env["DFL_MIN_PEER_UPDATES_TO_FINALIZE"] = str(min_peer_updates_to_finalize)
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "secure_dfl_platform.server"],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        )
    return processes


def stop_nodes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.returncode not in {0, -15, 1} and process.stdout:
            print(process.stdout.read())


def register_all_local_states(
    *,
    nodes: Mapping[str, str],
    clients: Mapping[str, Client],
    round_number: int,
    admin_token: str,
) -> dict[str, Any]:
    registrations = {}
    for node_id in sorted(nodes):
        payload = model_to_payload(clients[node_id].model)
        registrations[node_id] = request_json(
            f"{nodes[node_id]}/v1/rounds/{round_number}/local-state",
            method="POST",
            body={"payload_b64": base64.b64encode(payload).decode("ascii")},
            admin_token=admin_token,
            timeout=20.0,
        )
    return registrations


def wait_until_round_ready(
    *,
    nodes: Mapping[str, str],
    round_number: int,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    statuses: dict[str, dict[str, Any]] = {}
    while time.time() < deadline:
        statuses = {
            node_id: request_json(f"{url}/v1/rounds/{round_number}/status", timeout=5.0)
            for node_id, url in nodes.items()
        }
        if all(status["ready"] for status in statuses.values()):
            return statuses
        time.sleep(0.2)
    raise TimeoutError(f"round {round_number} did not become ready: {statuses}")


def finalize_and_load_aggregates(
    *,
    nodes: Mapping[str, str],
    clients: Mapping[str, Client],
    round_number: int,
    admin_token: str,
    device: str,
) -> dict[str, Any]:
    finalized = {}
    for node_id in sorted(nodes):
        response = request_json(
            f"{nodes[node_id]}/v1/rounds/{round_number}/finalize",
            method="POST",
            body={},
            admin_token=admin_token,
            timeout=20.0,
        )
        aggregate_payload = base64.b64decode(response.pop("aggregate_payload_b64"), validate=True)
        aggregate_state = payload_to_model_state(
            aggregate_payload,
            clients[node_id].model,
            max_payload_bytes=MAX_PAYLOAD_BYTES,
            device=device,
        )
        clients[node_id].set_state_dict(aggregate_state)
        finalized[node_id] = response
    return finalized


def collect_network_metrics(nodes: Mapping[str, str]) -> dict[str, int]:
    totals = {
        "sent_updates_total": 0,
        "received_updates_total": 0,
        "sent_bytes_total": 0,
        "received_bytes_total": 0,
        "finalized_rounds_total": 0,
        "partial_finalizations_total": 0,
        "send_failures_total": 0,
        "masked_updates_received_total": 0,
        "received_masking_overhead_bytes_total": 0,
    }
    for url in nodes.values():
        status = request_json(f"{url}/v1/status", timeout=5.0)
        metrics = status.get("metrics", {})
        for key in totals:
            totals[key] += int(metrics.get(key, 0))
    return totals


def write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("cannot write empty metrics")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def maybe_write_plots(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - optional reporting dependency
        print(f"Plot generation skipped: {exc}")
        return

    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    rounds = [row["round"] for row in rows]
    figures = [
        ("accuracy.png", "test_accuracy_percent", "Test accuracy (%)"),
        ("loss.png", "test_loss", "Test loss"),
        ("round_time.png", "round_time_seconds", "Round time (s)"),
        ("network_bytes.png", "network_bytes_total", "Network bytes total"),
    ]
    for filename, column, ylabel in figures:
        plt.figure(figsize=(8, 4.5))
        plt.plot(rounds, [row[column] for row in rows], marker="o", linewidth=2)
        plt.xlabel("Round")
        plt.ylabel(ylabel)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plots_dir / filename, dpi=180)
        plt.close()


def run_network_training_demo(args: argparse.Namespace) -> dict[str, Any]:
    set_seed(args.seed)
    device = select_device(args.device)
    experiment_id = args.experiment_id or (
        f"mnist_network_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir = Path(args.output_dir) / experiment_id
    runtime_dir = output_dir / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    ports = {f"node{i}": free_port() for i in range(args.num_clients)}
    nodes = {node_id: f"http://127.0.0.1:{port}" for node_id, port in ports.items()}
    admin_token = f"{experiment_id}-admin-token"

    train_dataset, test_dataset = load_demo_datasets(
        dataset_name=args.dataset,
        data_dir=Path(args.data_dir),
        max_train_samples=args.max_train_samples,
        max_test_samples=args.max_test_samples,
        seed=args.seed,
    )
    if args.split_type == "iid":
        client_loaders = create_iid_client_loaders(
            train_dataset,
            args.num_clients,
            args.batch_size,
            seed=args.seed,
        )
    else:
        client_loaders = create_non_iid_client_loaders(
            train_dataset,
            args.num_clients,
            args.batch_size,
            seed=args.seed,
        )
    test_loader = get_test_loader(test_dataset, args.batch_size)
    clients = {
        f"node{i}": Client(
            client_id=i,
            model=SimpleMLP(),
            train_loader=client_loaders[i],
            device=device,
            learning_rate=args.learning_rate,
            test_loader=test_loader,
        )
        for i in range(args.num_clients)
    }

    processes = start_nodes(
        nodes=nodes,
        ports=ports,
        topology=args.topology,
        experiment_id=experiment_id,
        admin_token=admin_token,
        runtime_dir=runtime_dir,
        min_peer_updates_to_finalize=args.min_peer_updates_to_finalize,
        security_mode=args.security_mode,
    )
    rows: list[dict[str, Any]] = []
    try:
        wait_for_nodes(nodes, timeout_seconds=args.timeout)
        print(
            f"Network MNIST demo started: experiment={experiment_id}, "
            f"clients={args.num_clients}, topology={args.topology}, device={device}"
        )
        for round_number in range(1, args.rounds + 1):
            started = time.time()
            train_losses = [
                clients[node_id].train_local(args.local_epochs)
                for node_id in sorted(clients)
            ]
            register_all_local_states(
                nodes=nodes,
                clients=clients,
                round_number=round_number,
                admin_token=admin_token,
            )
            wait_until_round_ready(
                nodes=nodes,
                round_number=round_number,
                timeout_seconds=args.timeout,
            )
            finalize_and_load_aggregates(
                nodes=nodes,
                clients=clients,
                round_number=round_number,
                admin_token=admin_token,
                device=device,
            )
            test_loss, test_accuracy, _ = evaluate_all_clients(
                list(clients.values()),
                test_loader,
            )
            network_metrics = collect_network_metrics(nodes)
            row = {
                "round": round_number,
                "train_loss": sum(train_losses) / len(train_losses),
                "test_loss": test_loss,
                "test_accuracy_percent": test_accuracy,
                "round_time_seconds": time.time() - started,
                "sent_updates_total": network_metrics["sent_updates_total"],
                "received_updates_total": network_metrics["received_updates_total"],
                "network_bytes_total": (
                    network_metrics["sent_bytes_total"]
                    + network_metrics["received_bytes_total"]
                ),
                "finalized_rounds_total": network_metrics["finalized_rounds_total"],
                "partial_finalizations_total": network_metrics[
                    "partial_finalizations_total"
                ],
                "send_failures_total": network_metrics["send_failures_total"],
                "masked_updates_total": network_metrics.get("masked_updates_received_total", 0),
                "masking_overhead_bytes_total": network_metrics.get(
                    "received_masking_overhead_bytes_total", 0
                ),
            }
            rows.append(row)
            print(
                f"Round {round_number:02d}: "
                f"acc={test_accuracy:.2f}%, loss={test_loss:.4f}, "
                f"time={row['round_time_seconds']:.2f}s"
            )
    finally:
        stop_nodes(processes)

    metrics_path = output_dir / "metrics.csv"
    write_metrics_csv(metrics_path, rows)
    maybe_write_plots(output_dir, rows)
    summary = {
        "status": "PASS",
        "experiment_id": experiment_id,
        "dataset": args.dataset,
        "split_type": args.split_type,
        "topology": args.topology,
        "min_peer_updates_to_finalize": args.min_peer_updates_to_finalize,
        "security_mode": args.security_mode,
        "num_clients": args.num_clients,
        "rounds": args.rounds,
        "device": device,
        "metrics_csv": str(metrics_path),
        "final_accuracy_percent": rows[-1]["test_accuracy_percent"],
        "final_test_loss": rows[-1]["test_loss"],
        "output_dir": str(output_dir),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real PyTorch training over the Secure DFL Platform MVP network"
    )
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--dataset", choices=["mnist", "fake"], default="mnist")
    parser.add_argument("--num-clients", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--split-type", choices=["iid", "non_iid"], default="iid")
    parser.add_argument("--topology", choices=["full", "ring"], default="ring")
    parser.add_argument(
        "--min-peer-updates-to-finalize",
        type=int,
        default=None,
        help="Optional quorum threshold. Default waits for all configured peers.",
    )
    parser.add_argument("--security-mode", choices=["none", "masking"], default="none")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", default=str(ROOT_DIR / "data"))
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent / "results"))
    parser.add_argument("--max-train-samples", type=int, default=1500)
    parser.add_argument("--max-test-samples", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def main() -> None:
    run_network_training_demo(parse_args())


if __name__ == "__main__":
    main()
