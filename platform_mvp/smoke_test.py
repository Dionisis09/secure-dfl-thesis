"""Launch three real node processes and verify decentralized exchanges."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from secure_dfl_platform.orchestrator import run_demo


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    ports = [free_port() for _ in range(3)]
    nodes = {f"node{i}": f"http://127.0.0.1:{port}" for i, port in enumerate(ports)}
    processes: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="secure_dfl_mvp_") as tmp:
        try:
            for i, port in enumerate(ports):
                node_id = f"node{i}"
                peer_urls = {peer_id: url for peer_id, url in nodes.items() if peer_id != node_id}
                env = os.environ.copy()
                env.update(
                    {
                        "DFL_NODE_ID": node_id,
                        "DFL_HOST": "127.0.0.1",
                        "DFL_PORT": str(port),
                        "DFL_EXPERIMENT_ID": "multiprocess_smoke",
                        "DFL_PEERS_JSON": json.dumps(peer_urls),
                        "DFL_DATA_DIR": str(Path(tmp) / node_id),
                        "DFL_ADMIN_TOKEN": "smoke-admin",
                        "DFL_DEMO_IDENTITY_SEED": "smoke-identity-seed",
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
            result = run_demo(nodes, rounds=3, admin_token="smoke-admin", timeout_seconds=30)
            print(json.dumps(result, indent=2, sort_keys=True))
            if result["status"] != "PASS" or result["network_exchanges"] != 18:
                raise SystemExit(1)
            for i in range(3):
                audit = Path(tmp) / f"node{i}" / "node_audit.jsonl"
                if not audit.exists() or len(audit.read_text(encoding="utf-8").splitlines()) < 10:
                    raise AssertionError(f"missing audit evidence for node{i}")
        finally:
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


if __name__ == "__main__":
    main()

