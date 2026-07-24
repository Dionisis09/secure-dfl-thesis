"""Append-only audit ledger for secure federated learning experiments."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch

from .hashing import hash_client_states, stable_json
from .merkle import build_merkle_proofs, merkle_root
from .reporting import build_audit_report, build_audit_summary_csv, build_statistics
from .schema import AUDIT_SCHEMA_VERSION, configuration_hash, finalize_record, utc_now_iso
from .signing import (
    create_keyring,
    key_manifest_hash,
    public_keys_manifest,
    sign_payload,
    signing_payload,
)
from .verifier import verify_audit_package


class FederatedAuditLedger:
    """Advanced audit package with JSONL ledger and real Ed25519 signatures."""

    def __init__(
        self,
        experiment_name: str,
        configuration: Mapping[str, Any],
        output_root: Path,
    ) -> None:
        self.experiment_name = experiment_name
        self.configuration = dict(configuration)
        self.output_root = output_root
        self.package_dir = output_root / experiment_name
        self.ledger_path = self.package_dir / "ledger.jsonl"
        self.public_keys_path = self.package_dir / "public_keys.json"
        self.summary_csv_path = self.package_dir / "audit_summary.csv"
        self.report_path = self.package_dir / "verification_report.md"
        self.statistics_path = self.package_dir / "audit_statistics.md"
        self.plots_dir = self.package_dir / "plots"

        self.config_hash = configuration_hash(self.configuration)
        self.keyring = create_keyring(
            num_clients=int(self.configuration.get("num_clients", 0)),
            seed=int(self.configuration.get("seed", 0)),
        )
        self.public_keys = public_keys_manifest(self.keyring)
        self.public_keys_hash = key_manifest_hash(self.public_keys)
        self.records = []
        self._last_hash = "GENESIS"

        self.package_dir.mkdir(parents=True, exist_ok=True)
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        self._start_experiment()

    def _append_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        finalized = finalize_record(record)
        self.records.append(finalized)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(finalized, ensure_ascii=False) + "\n")
        self._last_hash = finalized["record_hash"]
        return finalized

    def _start_experiment(self) -> None:
        if self.ledger_path.exists():
            self.ledger_path.unlink()
        self.public_keys_path.write_text(
            json.dumps(self.public_keys, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._append_record(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "record_type": "experiment_start",
                "record_index": 0,
                "timestamp": utc_now_iso(),
                "experiment_name": self.experiment_name,
                "round_number": 0,
                "previous_hash": "GENESIS",
                "configuration": self.configuration,
                "configuration_hash": self.config_hash,
                "public_keys_hash": self.public_keys_hash,
                "security_mode": self.configuration.get("security_mode", ""),
                "num_clients": int(self.configuration.get("num_clients", 0)),
                "topology": self.configuration.get("topology", ""),
                "split_type": self.configuration.get("split_type", ""),
                "adaptive_policy": self.configuration.get("adaptive_policy", ""),
                "metadata": {
                    "purpose": "advanced federated learning audit package",
                    "signature_algorithm": "Ed25519",
                    "ledger_format": "append-only JSONL",
                },
            }
        )

    def record_round(
        self,
        round_number: int,
        metrics: Mapping[str, Any],
        client_states: Mapping[int, Mapping[str, torch.Tensor]],
        adaptive_risk_scores: Optional[Mapping[int, float]] = None,
        adaptive_selected_targets: Optional[Any] = None,
    ) -> None:
        start = time.perf_counter()
        client_hashes = hash_client_states(client_states)
        root = merkle_root(client_hashes)
        proofs = build_merkle_proofs(client_hashes)
        signatures = {}
        security_mode = str(self.configuration.get("security_mode", ""))

        for client_id, key_pair in sorted(self.keyring.items()):
            client_key = f"client_{client_id}"
            model_hash = client_hashes[client_key]
            payload = signing_payload(
                experiment_name=self.experiment_name,
                client_id=client_id,
                round_number=round_number,
                model_hash=model_hash,
                security_mode=security_mode,
                merkle_root=root,
            )
            signatures[client_key] = {
                "public_key_id": key_pair.public_key_id,
                "signature": sign_payload(key_pair.private_key, payload),
                "algorithm": "Ed25519",
            }

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

        generation_time = time.perf_counter() - start
        record = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "record_type": "round",
                "record_index": len(self.records),
                "timestamp": utc_now_iso(),
                "experiment_name": self.experiment_name,
                "round_number": int(round_number),
                "previous_hash": self._last_hash,
                "configuration_hash": self.config_hash,
                "public_keys_hash": self.public_keys_hash,
                "security_mode": security_mode,
                "num_clients": int(self.configuration.get("num_clients", 0)),
                "topology": self.configuration.get("topology", ""),
                "split_type": self.configuration.get("split_type", ""),
                "adaptive_policy": self.configuration.get("adaptive_policy", ""),
                "adaptive_selected_targets": selected_targets,
                "adaptive_risk_scores": risk_scores,
                "metrics": {
                    "avg_train_loss": float(metrics.get("avg_train_loss", 0.0)),
                    "avg_test_loss": float(metrics.get("avg_test_loss", 0.0)),
                    "avg_test_accuracy": float(
                        metrics.get("avg_test_accuracy", 0.0)
                    ),
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
                    "he_ciphertext_bytes": int(
                        metrics.get("he_ciphertext_bytes", 0)
                    ),
                    "pairwise_cancellation_error": float(
                        metrics.get("pairwise_masking_cancellation_error", 0.0)
                    ),
                },
                "client_model_hashes": client_hashes,
                "merkle_root": root,
                "merkle_proofs": proofs,
                "client_signatures": signatures,
                "generation_time_seconds": generation_time,
                "record_size_bytes": 0,
            }
        record["record_size_bytes"] = len(stable_json(record).encode("utf-8"))
        self._append_record(record)

    def finalize(self) -> Dict[str, Path]:
        self._append_record(
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "record_type": "experiment_end",
                "record_index": len(self.records),
                "timestamp": utc_now_iso(),
                "experiment_name": self.experiment_name,
                "round_number": int(self.configuration.get("num_rounds", 0)),
                "previous_hash": self._last_hash,
                "configuration_hash": self.config_hash,
                "public_keys_hash": self.public_keys_hash,
                "security_mode": self.configuration.get("security_mode", ""),
                "num_clients": int(self.configuration.get("num_clients", 0)),
                "topology": self.configuration.get("topology", ""),
                "split_type": self.configuration.get("split_type", ""),
                "adaptive_policy": self.configuration.get("adaptive_policy", ""),
                "metadata": {"status": "completed"},
            }
        )

        verification = verify_audit_package(self.package_dir)
        build_audit_summary_csv(self.records, self.summary_csv_path, verification)
        report = build_audit_report(
            experiment_name=self.experiment_name,
            records=self.records,
            verification=verification,
        )
        self.report_path.write_text(report, encoding="utf-8")
        self.statistics_path.write_text(
            build_statistics(self.records, verification), encoding="utf-8"
        )
        self._save_plots()

        return {
            "package": self.package_dir,
            "ledger": self.ledger_path,
            "public_keys": self.public_keys_path,
            "summary": self.summary_csv_path,
            "report": self.report_path,
            "statistics": self.statistics_path,
            "plots": self.plots_dir,
        }

    def _round_records(self):
        return [record for record in self.records if record.get("record_type") == "round"]

    def _save_plots(self) -> None:
        rounds = self._round_records()
        if not rounds:
            return

        x = [int(record["round_number"]) for record in rounds]
        acc = [record["metrics"]["avg_test_accuracy"] for record in rounds]
        communication = [
            record["metrics"]["communication_bytes"] / (1024**2)
            for record in rounds
        ]
        gen_time = [record.get("generation_time_seconds", 0.0) for record in rounds]
        size = [record.get("record_size_bytes", 0) for record in rounds]
        he_targets = [len(record.get("adaptive_selected_targets", [])) for record in rounds]

        def finish(name: str):
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(self.plots_dir / name, dpi=150)
            plt.close()

        plt.figure()
        plt.plot(x, acc, marker="o")
        plt.xlabel("Round")
        plt.ylabel("Average test accuracy (%)")
        plt.title("Audit Package Accuracy Trace")
        finish("audit_accuracy_trace.png")

        plt.figure()
        plt.plot(x, communication, marker="o")
        plt.xlabel("Round")
        plt.ylabel("Communication (MiB)")
        plt.title("Audited Communication per Round")
        finish("audit_communication_trace.png")

        plt.figure()
        plt.plot(x, gen_time, marker="o")
        plt.xlabel("Round")
        plt.ylabel("Generation time (seconds)")
        plt.title("Audit Record Generation Time")
        finish("audit_generation_time.png")

        plt.figure()
        plt.plot(x, size, marker="o")
        plt.xlabel("Round")
        plt.ylabel("Record size (bytes)")
        plt.title("Audit Record Size by Round")
        finish("audit_record_size.png")

        plt.figure()
        plt.bar(x, he_targets)
        plt.xlabel("Round")
        plt.ylabel("Selected adaptive targets")
        plt.title("Audited Adaptive Security Decisions")
        finish("audit_adaptive_targets.png")
