"""Operator-side demo runner. It orchestrates; it never aggregates models."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any, Mapping

import numpy as np

from .codec import decode_state, encode_state


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    admin_token: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if admin_token is not None:
        headers["X-DFL-Admin-Token"] = admin_token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def wait_for_nodes(nodes: Mapping[str, str], timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + timeout_seconds
    pending = set(nodes)
    while pending and time.time() < deadline:
        for node_id in list(pending):
            try:
                response = request_json(f"{nodes[node_id]}/health", timeout=1.0)
                if response.get("status") == "ok":
                    pending.remove(node_id)
            except Exception:
                pass
        if pending:
            time.sleep(0.25)
    if pending:
        raise TimeoutError(f"nodes did not become healthy: {sorted(pending)}")


def deterministic_state(node_index: int, round_number: int) -> OrderedDict[str, np.ndarray]:
    base = node_index * 10.0 + round_number
    return OrderedDict(
        [
            ("layer.bias", np.asarray([base, base + 0.5], dtype=np.float32)),
            ("layer.weight", np.arange(6, dtype=np.float32).reshape(2, 3) + base),
        ]
    )


def expected_neighbor_average(
    node_id: str,
    peer_ids: list[str],
    states: Mapping[str, Mapping[str, np.ndarray]],
) -> OrderedDict[str, np.ndarray]:
    contributors = [node_id, *sorted(peer_ids)]
    result: OrderedDict[str, np.ndarray] = OrderedDict()
    for name in states[node_id]:
        result[name] = sum(np.asarray(states[item][name]) for item in contributors) / len(
            contributors
        )
    return result


def run_demo(
    nodes: Mapping[str, str],
    *,
    rounds: int,
    admin_token: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    wait_for_nodes(nodes, timeout_seconds)
    node_metadata = {node_id: request_json(f"{url}/v1/node") for node_id, url in nodes.items()}
    summaries = []
    ordered_nodes = sorted(nodes)
    for round_number in range(1, rounds + 1):
        states = {
            node_id: deterministic_state(index, round_number)
            for index, node_id in enumerate(ordered_nodes)
        }
        registrations = {}
        for node_id in ordered_nodes:
            payload = encode_state(states[node_id])
            registrations[node_id] = request_json(
                f"{nodes[node_id]}/v1/rounds/{round_number}/local-state",
                method="POST",
                body={"payload_b64": base64.b64encode(payload).decode("ascii")},
                admin_token=admin_token,
            )

        deadline = time.time() + timeout_seconds
        statuses: dict[str, dict[str, Any]] = {}
        while time.time() < deadline:
            statuses = {
                node_id: request_json(
                    f"{nodes[node_id]}/v1/rounds/{round_number}/status"
                )
                for node_id in ordered_nodes
            }
            if all(status["ready"] for status in statuses.values()):
                break
            time.sleep(0.2)
        if not statuses or not all(status["ready"] for status in statuses.values()):
            raise TimeoutError(f"round {round_number} did not become ready: {statuses}")

        finalized = {}
        for node_id in ordered_nodes:
            response = request_json(
                f"{nodes[node_id]}/v1/rounds/{round_number}/finalize",
                method="POST",
                body={},
                admin_token=admin_token,
            )
            aggregate = decode_state(
                base64.b64decode(response.pop("aggregate_payload_b64"), validate=True),
                32 * 1024 * 1024,
            )
            expected = expected_neighbor_average(
                node_id,
                list(node_metadata[node_id]["peer_ids"]),
                states,
            )
            for name in aggregate:
                if not np.allclose(aggregate[name], expected[name], atol=1e-5):
                    raise AssertionError(
                        f"aggregate mismatch: node={node_id}, round={round_number}, tensor={name}"
                    )
            finalized[node_id] = response
        summaries.append(
            {
                "round_number": round_number,
                "registrations": registrations,
                "finalized": finalized,
                "verified": True,
            }
        )
    return {
        "status": "PASS",
        "nodes": ordered_nodes,
        "rounds": rounds,
        "network_exchanges": sum(
            len(node_metadata[node_id]["peer_ids"]) for node_id in ordered_nodes
        )
        * rounds,
        "summaries": summaries,
    }


def parse_nodes(value: str) -> dict[str, str]:
    nodes: dict[str, str] = {}
    for item in value.split(","):
        node_id, url = item.split("=", 1)
        nodes[node_id.strip()] = url.strip().rstrip("/")
    if not nodes:
        raise ValueError("at least one node is required")
    return nodes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the networked Secure DFL MVP demo")
    parser.add_argument(
        "--nodes",
        default="node0=http://localhost:9100,node1=http://localhost:9101,node2=http://localhost:9102",
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--admin-token", default="demo-admin-token")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    result = run_demo(
        parse_nodes(args.nodes),
        rounds=args.rounds,
        admin_token=args.admin_token,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
