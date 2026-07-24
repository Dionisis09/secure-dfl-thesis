"""Run a signed network demo with generated Ed25519 deployment keys."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from secure_dfl_platform.key_management import write_node_keys
from secure_dfl_platform.orchestrator import run_demo
from verify_audit_logs import discover_audit_logs, verify_audit_file


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    node_ids = ["node0", "node1", "node2"]
    ports = {node_id: free_port() for node_id in node_ids}
    nodes = {node_id: f"http://127.0.0.1:{ports[node_id]}" for node_id in node_ids}
    processes: list[subprocess.Popen] = []

    with tempfile.TemporaryDirectory(prefix="secure_dfl_real_keys_") as tmp:
        tmp_path = Path(tmp)
        keys_dir = tmp_path / "keys"
        runtime_dir = tmp_path / "runtime"
        write_node_keys(node_ids=node_ids, output_dir=keys_dir)
        trusted_keys = keys_dir / "trusted_keys.json"

        try:
            for node_id in node_ids:
                env = os.environ.copy()
                peer_urls = {
                    peer_id: url for peer_id, url in nodes.items() if peer_id != node_id
                }
                env.update(
                    {
                        "DFL_NODE_ID": node_id,
                        "DFL_HOST": "127.0.0.1",
                        "DFL_PORT": str(ports[node_id]),
                        "DFL_EXPERIMENT_ID": "real_keys_demo",
                        "DFL_PEERS_JSON": json.dumps(peer_urls),
                        "DFL_DATA_DIR": str(runtime_dir / node_id),
                        "DFL_ADMIN_TOKEN": "real-keys-admin",
                        "DFL_PRIVATE_KEY_FILE": str(
                            keys_dir / "nodes" / f"{node_id}_private_key.pem"
                        ),
                        "DFL_TRUSTED_KEYS_FILE": str(trusted_keys),
                    }
                )
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "secure_dfl_platform.server"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                )

            demo_result = run_demo(
                nodes,
                rounds=2,
                admin_token="real-keys-admin",
                timeout_seconds=30,
            )
            audit_results = [
                verify_audit_file(path, trusted_keys)
                for path in discover_audit_logs(runtime_dir)
            ]
            report = {
                "status": "PASS"
                if demo_result["status"] == "PASS"
                and all(item["valid"] for item in audit_results)
                else "FAIL",
                "nodes": node_ids,
                "rounds": 2,
                "trusted_keys_file": str(trusted_keys),
                "audit_logs_checked": len(audit_results),
                "audit_records": sum(int(item["records"]) for item in audit_results),
                "demo": demo_result,
                "audit_verification": audit_results,
            }
            print(json.dumps(report, indent=2, sort_keys=True))
            if report["status"] != "PASS":
                raise SystemExit(1)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
