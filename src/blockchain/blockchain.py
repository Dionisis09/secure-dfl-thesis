"""Independent blockchain audit layer for DFL experiments."""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch

from .block import finalized_block
from .hashing import hash_client_states
from .serialization import (
    canonical_config_hash,
    load_chain_json,
    save_chain_json,
    save_summary_csv,
)
from .hashing import stable_json_dumps
from .signatures import build_round_signatures, generate_client_key_pairs
from .verification import build_verification_report, verify_chain_data


PROJECT_VERSION = "secure-dfl-thesis-part6-blockchain-audit"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class AuditBlockchain:
    """In-memory ledger that records one audit block per communication round."""

    def __init__(
        self,
        experiment_name: str,
        configuration: Dict[str, Any],
        project_root: Path,
    ) -> None:
        self.experiment_name = experiment_name
        self.configuration = configuration
        self.project_root = project_root
        self.configuration_hash = canonical_config_hash(configuration)
        self.client_key_pairs = generate_client_key_pairs(
            num_clients=int(configuration.get("num_clients", 0)),
            seed=int(configuration.get("seed", 0)),
        )
        self.client_public_keys = {
            f"client_{client_id}": key_pair["public_key_id"]
            for client_id, key_pair in sorted(self.client_key_pairs.items())
        }
        self.blocks = []
        self._create_genesis_block()

    def _create_genesis_block(self) -> None:
        generation_start = time.perf_counter()
        block = {
            "block_index": 0,
            "timestamp": utc_now_iso(),
            "experiment_name": self.experiment_name,
            "round_number": 0,
            "previous_hash": "GENESIS",
            "current_hash": "",
            "security_mode": self.configuration.get("security_mode", ""),
            "split_type": self.configuration.get("split_type", ""),
            "topology": self.configuration.get("topology", ""),
            "num_clients": int(self.configuration.get("num_clients", 0)),
            "batch_size": int(self.configuration.get("batch_size", 0)),
            "num_rounds": int(self.configuration.get("num_rounds", 0)),
            "adaptive_policy": self.configuration.get("adaptive_policy", ""),
            "adaptive_he_target_ratio": float(
                self.configuration.get("adaptive_he_target_ratio", 0.0)
            ),
            "adaptive_selected_targets": [],
            "adaptive_risk_scores": {},
            "train_loss": 0.0,
            "test_loss": 0.0,
            "test_accuracy": 0.0,
            "communication_bytes": 0,
            "masking_time_seconds": 0.0,
            "he_total_time_seconds": 0.0,
            "he_encryption_time_seconds": 0.0,
            "he_decryption_time_seconds": 0.0,
            "he_ciphertext_bytes": 0,
            "pairwise_cancellation_error": 0.0,
            "model_hashes": {},
            "client_signatures": {},
            "configuration_hash": self.configuration_hash,
            "block_generation_time_seconds": 0.0,
            "nonce": 0,
            "extra_metadata": {
                "project_version": PROJECT_VERSION,
                "git_commit": get_git_commit(self.project_root),
                "purpose": "independent audit and integrity layer",
            },
        }
        block["block_generation_time_seconds"] = time.perf_counter() - generation_start
        self.blocks.append(finalized_block(block))

    @property
    def previous_hash(self) -> str:
        return self.blocks[-1]["current_hash"]

    def add_round_block(
        self,
        round_number: int,
        metrics: Mapping[str, Any],
        client_states: Mapping[int, Mapping[str, torch.Tensor]],
        adaptive_risk_scores: Optional[Mapping[int, float]] = None,
        adaptive_selected_targets: Optional[Any] = None,
    ) -> None:
        generation_start = time.perf_counter()
        model_hashes = hash_client_states(client_states)
        client_signatures = build_round_signatures(
            round_number=round_number,
            model_hashes=model_hashes,
            public_keys={
                client_id: key_pair["public_key_id"]
                for client_id, key_pair in self.client_key_pairs.items()
            },
        )
        selected_targets = adaptive_selected_targets
        if isinstance(selected_targets, str):
            selected_targets = [
                int(value)
                for value in selected_targets.split(";")
                if value.strip()
            ]
        if selected_targets is None:
            selected_targets = []
        risk_scores = {
            str(client_id): float(score)
            for client_id, score in (adaptive_risk_scores or {}).items()
        }

        block = {
            "block_index": len(self.blocks),
            "timestamp": utc_now_iso(),
            "experiment_name": self.experiment_name,
            "round_number": int(round_number),
            "previous_hash": self.previous_hash,
            "current_hash": "",
            "security_mode": self.configuration.get("security_mode", ""),
            "split_type": self.configuration.get("split_type", ""),
            "topology": self.configuration.get("topology", ""),
            "num_clients": int(self.configuration.get("num_clients", 0)),
            "batch_size": int(self.configuration.get("batch_size", 0)),
            "num_rounds": int(self.configuration.get("num_rounds", 0)),
            "adaptive_policy": self.configuration.get("adaptive_policy", ""),
            "adaptive_he_target_ratio": float(
                self.configuration.get("adaptive_he_target_ratio", 0.0)
            ),
            "adaptive_selected_targets": selected_targets,
            "adaptive_risk_scores": risk_scores,
            "train_loss": float(metrics.get("avg_train_loss", 0.0)),
            "test_loss": float(metrics.get("avg_test_loss", 0.0)),
            "test_accuracy": float(metrics.get("avg_test_accuracy", 0.0)),
            "communication_bytes": int(
                metrics.get("total_communication_bytes")
                or metrics.get("communication_bytes", 0)
            ),
            "masking_time_seconds": float(
                metrics.get("masking_time_seconds", 0.0)
            ),
            "he_total_time_seconds": float(
                metrics.get("he_total_time_seconds", 0.0)
            ),
            "he_encryption_time_seconds": float(
                metrics.get("he_encryption_time_seconds", 0.0)
            ),
            "he_decryption_time_seconds": float(
                metrics.get("he_decryption_time_seconds", 0.0)
            ),
            "he_ciphertext_bytes": int(metrics.get("he_ciphertext_bytes", 0)),
            "pairwise_cancellation_error": float(
                metrics.get("pairwise_masking_cancellation_error", 0.0)
            ),
            "model_hashes": model_hashes,
            "client_signatures": client_signatures,
            "configuration_hash": self.configuration_hash,
            "block_generation_time_seconds": 0.0,
            "nonce": round_number,
            "extra_metadata": {},
        }
        block["block_generation_time_seconds"] = time.perf_counter() - generation_start
        self.blocks.append(finalized_block(block))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_name": self.experiment_name,
            "created_at": self.blocks[0]["timestamp"],
            "project_version": PROJECT_VERSION,
            "configuration": self.configuration,
            "configuration_hash": self.configuration_hash,
            "client_public_keys": self.client_public_keys,
            "blocks": self.blocks,
        }

    def save_artifacts(self, output_dir: Path) -> Dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        chain_data = self.to_dict()
        in_memory_result = verify_chain_data(chain_data)

        chain_path = output_dir / f"{self.experiment_name}_blockchain.json"
        summary_path = output_dir / f"{self.experiment_name}_blockchain_summary.csv"
        report_path = output_dir / f"{self.experiment_name}_verification_report.md"
        latest_report_path = output_dir / "verification_report.md"
        statistics_path = output_dir / "blockchain_statistics.md"

        save_chain_json(chain_data, chain_path)
        exported_chain_data = load_chain_json(chain_path)
        exported_result = verify_chain_data(exported_chain_data)

        save_summary_csv(chain_data["blocks"], summary_path, exported_result.status)

        report = build_verification_report(
            exported_chain_data,
            exported_result,
            in_memory_result=in_memory_result,
            exported_result=exported_result,
        )
        report_path.write_text(report, encoding="utf-8")
        latest_report_path.write_text(report, encoding="utf-8")

        statistics = self._build_statistics_report(exported_chain_data, exported_result)
        statistics_path.write_text(statistics, encoding="utf-8")

        plot_dir = output_dir / "plots"
        self._save_plots(plot_dir)

        return {
            "chain": chain_path,
            "summary": summary_path,
            "report": report_path,
            "latest_report": latest_report_path,
            "statistics": statistics_path,
            "plots": plot_dir,
        }

    def _round_blocks(self):
        return [block for block in self.blocks if int(block.get("round_number", 0)) > 0]

    def _save_plots(self, plot_dir: Path) -> None:
        plot_dir.mkdir(parents=True, exist_ok=True)
        blocks = self.blocks
        round_blocks = self._round_blocks()

        indices = [int(block["block_index"]) for block in blocks]
        cumulative = list(range(1, len(blocks) + 1))
        plt.figure()
        plt.plot(indices, cumulative, marker="o")
        plt.xlabel("Block index")
        plt.ylabel("Cumulative blocks")
        plt.title("Blockchain Block Count")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "block_count.png", dpi=150)
        plt.close()

        prefixes = [block["current_hash"][:12] for block in blocks]
        plt.figure(figsize=(max(6, len(prefixes) * 0.8), 4))
        plt.plot(indices, range(len(prefixes)), marker="o", linestyle="-")
        plt.yticks(range(len(prefixes)), prefixes)
        plt.xlabel("Block index")
        plt.ylabel("Hash prefix")
        plt.title("Hash Prefix Timeline")
        plt.grid(True, axis="x", alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "hash_prefix_timeline.png", dpi=150)
        plt.close()

        rounds = [int(block["round_number"]) for block in round_blocks]
        communication = [
            int(block.get("communication_bytes", 0)) / (1024**2)
            for block in round_blocks
        ]
        accuracy = [float(block.get("test_accuracy", 0.0)) for block in round_blocks]
        avg_risk = []
        for block in round_blocks:
            scores = [float(value) for value in block.get("adaptive_risk_scores", {}).values()]
            avg_risk.append(sum(scores) / len(scores) if scores else 0.0)

        plt.figure()
        plt.plot(rounds, communication, marker="o")
        plt.xlabel("Communication round")
        plt.ylabel("Communication (MiB)")
        plt.title("Communication vs Block")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "communication_vs_block.png", dpi=150)
        plt.close()

        plt.figure()
        plt.plot(rounds, accuracy, marker="o")
        plt.xlabel("Communication round")
        plt.ylabel("Average test accuracy (%)")
        plt.title("Accuracy vs Block")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "accuracy_vs_block.png", dpi=150)
        plt.close()

        plt.figure()
        plt.plot(rounds, avg_risk, marker="o")
        plt.xlabel("Communication round")
        plt.ylabel("Average adaptive risk score")
        plt.title("Adaptive Risk vs Block")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "risk_vs_block.png", dpi=150)
        plt.close()

        generation_times = [
            float(block.get("block_generation_time_seconds", 0.0))
            for block in blocks
        ]
        block_sizes = [
            len(stable_json_dumps(block).encode("utf-8")) for block in blocks
        ]
        plt.figure()
        plt.plot(indices, generation_times, marker="o")
        plt.xlabel("Block index")
        plt.ylabel("Generation time (seconds)")
        plt.title("Block Generation Time")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "block_generation_time.png", dpi=150)
        plt.close()

        first_hex_chars = [block["current_hash"][0] for block in blocks if block.get("current_hash")]
        labels = sorted(set(first_hex_chars))
        counts = [first_hex_chars.count(label) for label in labels]
        plt.figure()
        plt.bar(labels, counts)
        plt.xlabel("First hash hex character")
        plt.ylabel("Block count")
        plt.title("Hash Prefix Distribution")
        plt.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "hash_prefix_distribution.png", dpi=150)
        plt.close()

        plt.figure()
        plt.plot(indices, block_sizes, marker="o")
        plt.xlabel("Block index")
        plt.ylabel("Block size (bytes)")
        plt.title("Block Size by Round")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "block_size_by_round.png", dpi=150)
        plt.close()

        verification = verify_chain_data(self.to_dict())
        plt.figure()
        colors = ["#2ca02c" if verification.valid else "#d62728"]
        plt.bar([verification.status], [1], color=colors)
        plt.ylabel("Status flag")
        plt.title("Blockchain Verification Status")
        plt.ylim(0, 1.2)
        plt.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        plt.savefig(plot_dir / "verification_status.png", dpi=150)
        plt.close()

    def _build_statistics_report(
        self, chain_data: Dict[str, Any], verification_result
    ) -> str:
        blocks = chain_data.get("blocks", [])
        block_sizes = [
            len(stable_json_dumps(block).encode("utf-8")) for block in blocks
        ]
        hash_lengths = [
            len(block.get("current_hash", ""))
            for block in blocks
            if block.get("current_hash")
        ]
        generation_time = sum(
            float(block.get("block_generation_time_seconds", 0.0))
            for block in blocks
        )
        average_block_size = (
            sum(block_sizes) / len(block_sizes) if block_sizes else 0.0
        )
        average_hash_length = (
            sum(hash_lengths) / len(hash_lengths) if hash_lengths else 0.0
        )
        broken_blocks = (
            "None"
            if verification_result.broken_block is None
            else str(verification_result.broken_block)
        )

        return "\n".join(
            [
                "Blockchain Statistics",
                "",
                f"Experiment: {chain_data.get('experiment_name', '')}",
                f"Number of blocks: {len(blocks)}",
                f"Chain valid: {'YES' if verification_result.valid else 'NO'}",
                f"Average block size: {average_block_size:.2f} bytes",
                f"Average hash length: {average_hash_length:.2f} characters",
                f"Verification result: {verification_result.status}",
                f"Broken blocks: {broken_blocks}",
                f"Generation time: {generation_time:.6f} seconds",
                "",
            ]
        )
