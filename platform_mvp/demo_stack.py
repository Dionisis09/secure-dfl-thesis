"""One-command Secure DFL product demo stack.

The script starts a complete local deployment:
- generated Ed25519 deployment keys
- three independent node processes
- operator dashboard
- signed decentralized demo rounds
- audit-log verification
- reproducible result artifacts
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from secure_dfl_platform.key_management import write_node_keys
from secure_dfl_platform.orchestrator import run_demo, wait_for_nodes
from verify_audit_logs import discover_audit_logs, verify_audit_file


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    timeout: float = 5.0,
    dashboard_token: str | None = None,
) -> dict[str, Any]:
    headers = {}
    if dashboard_token:
        headers["X-DFL-Dashboard-Token"] = dashboard_token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def start_nodes(
    *,
    node_ids: list[str],
    nodes: dict[str, str],
    ports: dict[str, int],
    keys_dir: Path,
    runtime_dir: Path,
    admin_token: str,
    experiment_id: str,
    min_peer_updates_to_finalize: int | None,
    security_mode: str,
) -> list[subprocess.Popen]:
    trusted_keys = keys_dir / "trusted_keys.json"
    processes: list[subprocess.Popen] = []
    for node_id in node_ids:
        peer_urls = {
            peer_id: url for peer_id, url in nodes.items() if peer_id != node_id
        }
        env = os.environ.copy()
        env.update(
            {
                "DFL_NODE_ID": node_id,
                "DFL_HOST": "127.0.0.1",
                "DFL_PORT": str(ports[node_id]),
                "DFL_EXPERIMENT_ID": experiment_id,
                "DFL_PEERS_JSON": json.dumps(peer_urls),
                "DFL_DATA_DIR": str(runtime_dir / node_id),
                "DFL_ADMIN_TOKEN": admin_token,
                "DFL_PRIVATE_KEY_FILE": str(
                    keys_dir / "nodes" / f"{node_id}_private_key.pem"
                ),
                "DFL_TRUSTED_KEYS_FILE": str(trusted_keys),
                "DFL_SECURITY_MODE": security_mode,
            }
        )
        if min_peer_updates_to_finalize is not None:
            env["DFL_MIN_PEER_UPDATES_TO_FINALIZE"] = str(
                min_peer_updates_to_finalize
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
    return processes


def start_dashboard(
    *,
    nodes: dict[str, str],
    dashboard_port: int,
    dashboard_token: str,
) -> subprocess.Popen:
    node_arg = ",".join(f"{node_id}={url}" for node_id, url in sorted(nodes.items()))
    return subprocess.Popen(
        [
            sys.executable,
            "operator_dashboard.py",
            "--nodes",
            node_arg,
            "--host",
            "127.0.0.1",
            "--port",
            str(dashboard_port),
            "--admin-token",
            dashboard_token,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_markdown_report(summary: dict[str, Any]) -> str:
    dashboard_after = summary["dashboard_after"]
    audit_report = summary["audit_report"]
    security_mode = summary["security_mode"]
    lines = [
        "# Secure DFL Demo Stack Run Report",
        "",
        f"Experiment id: `{summary['experiment_id']}`",
        f"Status: `{summary['status']}`",
        f"Security mode: `{security_mode}`",
        f"Rounds: `{summary['rounds']}`",
        f"Nodes online: `{dashboard_after['nodes_online']}/{dashboard_after['nodes_total']}`",
        f"Finalized node-rounds: `{dashboard_after['finalized_rounds']}`",
        f"Partial node-rounds: `{dashboard_after['partial_rounds']}`",
        f"Masked updates received: `{dashboard_after.get('masked_updates_total', 0)}`",
        f"Masking overhead bytes: `{dashboard_after.get('masking_overhead_bytes_total', 0)}`",
        f"Audit verification: `{audit_report['status']}`",
        f"Audit logs checked: `{audit_report['audit_logs_checked']}`",
        f"Audit records checked: `{audit_report['total_records']}`",
        "",
        "## Dashboard",
        "",
        f"Open: `{summary['dashboard_url']}`",
        "",
        "## Result files",
        "",
        f"- Runtime directory: `{summary['runtime_dir']}`",
        f"- Trusted keys: `{summary['trusted_keys_file']}`",
        "- `summary.json`",
        "- `dashboard_snapshot.json`",
        "- `audit_verification.json`",
        "",
        "## Interpretation",
        "",
    ]
    if security_mode == "masking":
        lines.extend(
            [
                "This run used the platform masking mode. Each outgoing model-state payload was additively masked before transport, signed inside the update envelope, unmasked by the receiver, and then used for normal decentralized aggregation.",
                "",
                "The current implementation is a controlled masking simulation. It demonstrates protected-sharing workflow and overhead accounting, but it is not yet a full cryptographic secure aggregation protocol because the mask is transported to the receiver for reconstruction.",
            ]
        )
    elif security_mode == "pairwise_masking":
        lines.extend(
            [
                "This run used pairwise masking. Each outgoing model-state payload was masked for a specific target aggregate. The raw masks were not transported in the update envelope.",
                "",
                "During finalization, the target node applies its own local target-specific mask and averages the masked contributor states. The pairwise masks cancel over the complete contributor set, so the final aggregate remains valid while individual transmitted payloads stay masked.",
                "",
                "Current limitation: this mode requires the complete configured contributor set for the target round. Quorum finalization with missing contributors should use baseline or controlled masking until a dropout-resilient pairwise protocol is added.",
            ]
        )
    else:
        lines.append(
            "This run used baseline signed transport without masking. It is the compatibility mode and should remain the default behavior."
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-command Secure DFL demo stack")
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--num-nodes", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output-dir", default="results/demo_stack")
    parser.add_argument("--keep-alive-seconds", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--min-peer-updates-to-finalize",
        type=int,
        default=None,
        help="Optional quorum threshold. Default waits for all configured peers.",
    )
    parser.add_argument(
        "--security-mode",
        choices=["none", "masking", "pairwise_masking"],
        default="none",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.num_nodes < 2:
        raise ValueError("num-nodes must be at least 2")

    experiment_id = args.experiment_id or (
        f"demo_stack_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir = Path(args.output_dir) / experiment_id
    keys_dir = output_dir / "deployment_keys"
    runtime_dir = output_dir / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)

    node_ids = [f"node{i}" for i in range(args.num_nodes)]
    ports = {node_id: free_port() for node_id in node_ids}
    nodes = {node_id: f"http://127.0.0.1:{ports[node_id]}" for node_id in node_ids}
    dashboard_port = free_port()
    dashboard_base_url = f"http://127.0.0.1:{dashboard_port}"
    admin_token = f"{experiment_id}-admin"
    dashboard_token = f"{experiment_id}-dashboard"
    processes: list[subprocess.Popen] = []

    write_node_keys(node_ids=node_ids, output_dir=keys_dir)
    trusted_keys = keys_dir / "trusted_keys.json"

    try:
        processes.extend(
            start_nodes(
                node_ids=node_ids,
                nodes=nodes,
                ports=ports,
                keys_dir=keys_dir,
                runtime_dir=runtime_dir,
                admin_token=admin_token,
                experiment_id=experiment_id,
                min_peer_updates_to_finalize=args.min_peer_updates_to_finalize,
                security_mode=args.security_mode,
            )
        )
        wait_for_nodes(nodes, timeout_seconds=args.timeout)
        dashboard_process = start_dashboard(
            nodes=nodes,
            dashboard_port=dashboard_port,
            dashboard_token=dashboard_token,
        )
        processes.append(dashboard_process)
        time.sleep(0.5)
        before_status = request_json(
            f"{dashboard_base_url}/api/status",
            dashboard_token=dashboard_token,
        )

        dashboard_url = f"{dashboard_base_url}?token={dashboard_token}"
        print(f"Dashboard running at {dashboard_url}")
        demo_result = run_demo(
            nodes,
            rounds=args.rounds,
            admin_token=admin_token,
            timeout_seconds=args.timeout,
        )
        after_status = request_json(
            f"{dashboard_base_url}/api/status",
            dashboard_token=dashboard_token,
        )
        audit_results = [
            verify_audit_file(path, trusted_keys)
            for path in discover_audit_logs(runtime_dir)
        ]
        audit_report = {
            "status": "PASS" if all(item["valid"] for item in audit_results) else "FAIL",
            "audit_logs_checked": len(audit_results),
            "total_records": sum(int(item["records"]) for item in audit_results),
            "results": audit_results,
        }
        summary = {
            "status": "PASS"
            if demo_result["status"] == "PASS" and audit_report["status"] == "PASS"
            else "FAIL",
            "experiment_id": experiment_id,
            "node_ids": node_ids,
            "nodes": nodes,
            "dashboard_url": dashboard_url,
            "dashboard_api_url": dashboard_base_url,
            "dashboard_token_enabled": True,
            "security_mode": args.security_mode,
            "rounds": args.rounds,
            "trusted_keys_file": str(trusted_keys),
            "runtime_dir": str(runtime_dir),
            "demo_result": demo_result,
            "dashboard_before": before_status,
            "dashboard_after": after_status,
            "audit_report": audit_report,
        }

        write_text(output_dir / "summary.json", json.dumps(summary, indent=2, sort_keys=True))
        write_text(
            output_dir / "dashboard_snapshot.json",
            json.dumps(after_status, indent=2, sort_keys=True),
        )
        write_text(
            output_dir / "audit_verification.json",
            json.dumps(audit_report, indent=2, sort_keys=True),
        )
        write_text(
            output_dir / "run_commands.txt",
            "\n".join(
                [
                    f"Dashboard URL: {dashboard_url}",
                    f"Verify audit logs: {sys.executable} verify_audit_logs.py --runtime-dir {runtime_dir} --trusted-keys {trusted_keys}",
                    f"Output directory: {output_dir.resolve()}",
                ]
            )
            + "\n",
        )
        write_text(output_dir / "demo_stack_report.md", build_markdown_report(summary))
        print(json.dumps(summary, indent=2, sort_keys=True))

        if args.keep_alive_seconds > 0:
            print(
                f"Keeping stack alive for {args.keep_alive_seconds:.0f}s at {dashboard_url}"
            )
            deadline = time.time() + args.keep_alive_seconds
            while time.time() < deadline:
                time.sleep(min(1.0, deadline - time.time()))
        if summary["status"] != "PASS":
            raise SystemExit(1)
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    main()
