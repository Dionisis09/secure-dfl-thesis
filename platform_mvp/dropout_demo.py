"""Demonstrate quorum finalization when one configured peer is offline.

The demo starts node0 and node1 only, while both are configured as if node2 also
exists. With ``DFL_MIN_PEER_UPDATES_TO_FINALIZE=1``, node0 and node1 can finalize
after receiving each other's signed update. This is intentionally a platform
resilience demonstration, not a change to the thesis training pipeline.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

import numpy as np

from secure_dfl_platform.codec import decode_state, encode_state
from secure_dfl_platform.orchestrator import request_json, wait_for_nodes


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def state(value: float) -> OrderedDict[str, np.ndarray]:
    return OrderedDict([("weight", np.asarray([value], dtype=np.float32))])


def main() -> None:
    ports = {"node0": free_port(), "node1": free_port(), "node2": free_port()}
    all_nodes = {
        node_id: f"http://127.0.0.1:{port}" for node_id, port in ports.items()
    }
    live_nodes = {node_id: all_nodes[node_id] for node_id in ["node0", "node1"]}
    admin_token = "dropout-admin"
    processes: list[subprocess.Popen] = []

    with tempfile.TemporaryDirectory(prefix="secure_dfl_dropout_") as tmp:
        try:
            for node_id in live_nodes:
                peer_urls = {
                    peer_id: url for peer_id, url in all_nodes.items() if peer_id != node_id
                }
                env = os.environ.copy()
                env.update(
                    {
                        "DFL_NODE_ID": node_id,
                        "DFL_HOST": "127.0.0.1",
                        "DFL_PORT": str(ports[node_id]),
                        "DFL_EXPERIMENT_ID": "dropout_tolerance_demo",
                        "DFL_PEERS_JSON": json.dumps(peer_urls),
                        "DFL_DATA_DIR": str(Path(tmp) / node_id),
                        "DFL_ADMIN_TOKEN": admin_token,
                        "DFL_DEMO_IDENTITY_SEED": "dropout-demo-seed",
                        "DFL_MIN_PEER_UPDATES_TO_FINALIZE": "1",
                        "DFL_REQUEST_TIMEOUT_SECONDS": "0.5",
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

            wait_for_nodes(live_nodes, timeout_seconds=20)
            for node_id, value in {"node0": 1.0, "node1": 3.0}.items():
                payload = encode_state(state(value))
                request_json(
                    f"{live_nodes[node_id]}/v1/rounds/1/local-state",
                    method="POST",
                    body={"payload_b64": base64.b64encode(payload).decode("ascii")},
                    admin_token=admin_token,
                    timeout=5.0,
                )

            results = {}
            for node_id, url in live_nodes.items():
                response = request_json(
                    f"{url}/v1/rounds/1/finalize",
                    method="POST",
                    body={},
                    admin_token=admin_token,
                    timeout=5.0,
                )
                aggregate = decode_state(
                    base64.b64decode(response.pop("aggregate_payload_b64"), validate=True),
                    1024 * 1024,
                )
                if not np.allclose(aggregate["weight"], [2.0]):
                    raise AssertionError(f"unexpected aggregate for {node_id}: {aggregate}")
                results[node_id] = response

            report = {
                "status": "PASS",
                "scenario": "node2 configured but offline",
                "live_nodes": sorted(live_nodes),
                "offline_nodes": ["node2"],
                "required_peer_updates": 1,
                "expected_aggregate_weight": 2.0,
                "results": results,
            }
            print(json.dumps(report, indent=2, sort_keys=True))
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
