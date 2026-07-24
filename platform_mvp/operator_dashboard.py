"""Small operator web UI for Secure DFL platform nodes."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


DASHBOARD_TOKEN_HEADER = "X-DFL-Dashboard-Token"


def parse_nodes(value: str) -> dict[str, str]:
    nodes: dict[str, str] = {}
    for item in value.split(","):
        node_id, url = item.split("=", 1)
        nodes[node_id.strip()] = url.strip().rstrip("/")
    if not nodes:
        raise ValueError("at least one node is required")
    return nodes


def fetch_json(url: str, timeout: float = 2.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def is_dashboard_request_authorized(
    configured_token: str,
    provided_token: str | None,
) -> bool:
    """Return True when dashboard API access is allowed.

    An empty configured token intentionally keeps local demos frictionless and
    preserves backwards compatibility. When a token is configured, callers must
    provide it through the dashboard header or the `token` query parameter.
    """

    if not configured_token:
        return True
    if not provided_token:
        return False
    return hmac.compare_digest(configured_token, provided_token)


def token_from_request(path: str, headers: Any) -> str | None:
    header_value = headers.get(DASHBOARD_TOKEN_HEADER)
    if header_value:
        return str(header_value)
    query = parse_qs(urlparse(path).query)
    values = query.get("token", [])
    return str(values[0]) if values else None


def collect_status(nodes: dict[str, str]) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    online = 0
    partial_rounds = 0
    finalized_rounds = 0
    send_failures = 0
    masked_updates = 0
    masking_overhead_bytes = 0
    for node_id, base_url in nodes.items():
        try:
            status = fetch_json(f"{base_url}/v1/status")
            online += 1
            rounds = status.get("rounds", {})
            for round_status in rounds.values():
                if round_status.get("partial_ready"):
                    partial_rounds += 1
                if round_status.get("finalized"):
                    finalized_rounds += 1
            metrics = status.get("metrics", {})
            send_failures += int(metrics.get("send_failures_total", 0))
            masked_updates += int(metrics.get("masked_updates_received_total", 0))
            masking_overhead_bytes += int(
                metrics.get("received_masking_overhead_bytes_total", 0)
            )
            collected[node_id] = {"online": True, "url": base_url, "status": status}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            collected[node_id] = {
                "online": False,
                "url": base_url,
                "error": str(exc),
            }
    return {
        "generated_at_unix": time.time(),
        "nodes_total": len(nodes),
        "nodes_online": online,
        "nodes_offline": len(nodes) - online,
        "finalized_rounds": finalized_rounds,
        "partial_rounds": partial_rounds,
        "send_failures_total": send_failures,
        "masked_updates_total": masked_updates,
        "masking_overhead_bytes_total": masking_overhead_bytes,
        "nodes": collected,
    }


def dashboard_html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Secure DFL Operator Dashboard</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f6f8fb;color:#172033;margin:0}
    header{background:#16213e;color:white;padding:24px 36px}
    main{padding:24px 36px;max-width:1280px;margin:auto}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:20px}
    .card{background:white;border:1px solid #dde3ee;border-radius:14px;padding:18px;box-shadow:0 6px 18px rgba(20,30,60,.06)}
    .metric{font-size:34px;font-weight:750;margin-top:6px}.label{color:#667085;font-size:13px}
    .node{margin-bottom:16px}.ok{color:#047857;font-weight:700}.bad{color:#b42318;font-weight:700}
    table{width:100%;border-collapse:collapse;margin-top:10px}th,td{padding:8px;border-bottom:1px solid #e5eaf3;text-align:left;font-size:14px}
    code,pre{background:#eef2f7;border-radius:8px;padding:10px;display:block;overflow:auto}
    button{background:#2563eb;color:white;border:0;border-radius:10px;padding:10px 14px;cursor:pointer}
    input{border:1px solid #cbd5e1;border-radius:10px;padding:10px;min-width:260px}
    .auth{margin:16px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .warn{color:#b45309;font-weight:650}
  </style>
</head>
<body>
  <header>
    <h1>Secure DFL Operator Dashboard</h1>
    <p>Live view of node health, rounds, quorum status and network metrics.</p>
  </header>
  <main>
    <div class="card auth">
      <span class="label">Dashboard token</span>
      <input id="token" type="password" placeholder="Optional token">
      <button onclick="saveToken()">Save token</button>
      <span id="auth-status"></span>
    </div>
    <button onclick="refresh()">Refresh now</button>
    <p id="stamp"></p>
    <section class="grid" id="summary"></section>
    <section id="nodes"></section>
  </main>
<script>
const tokenInput = document.getElementById('token');
const initialToken = new URLSearchParams(location.search).get('token') || localStorage.getItem('secure_dfl_dashboard_token') || '';
tokenInput.value = initialToken;
function saveToken(){
  localStorage.setItem('secure_dfl_dashboard_token', tokenInput.value);
  refresh();
}
async function refresh(){
  const headers = {};
  if(tokenInput.value){ headers['X-DFL-Dashboard-Token'] = tokenInput.value; }
  const res = await fetch('/api/status', {headers});
  if(res.status === 401){
    document.getElementById('auth-status').innerHTML = '<span class="warn">Invalid or missing dashboard token.</span>';
    return;
  }
  const data = await res.json();
  document.getElementById('auth-status').innerHTML = 'Connected';
  document.getElementById('stamp').textContent = 'Updated: ' + new Date(data.generated_at_unix * 1000).toLocaleString();
  const metrics = [
    ['Nodes online', data.nodes_online + '/' + data.nodes_total],
    ['Offline nodes', data.nodes_offline],
    ['Finalized rounds', data.finalized_rounds],
    ['Partial rounds', data.partial_rounds],
    ['Masked updates', data.masked_updates_total],
    ['Mask overhead', data.masking_overhead_bytes_total + ' B'],
    ['Send failures', data.send_failures_total]
  ];
  document.getElementById('summary').innerHTML = metrics.map(([label,value]) =>
    `<div class="card"><div class="label">${label}</div><div class="metric">${value}</div></div>`
  ).join('');
  document.getElementById('nodes').innerHTML = Object.entries(data.nodes).map(([id,item]) => {
    if(!item.online){
      return `<div class="card node"><h2>${id} <span class="bad">OFFLINE</span></h2><p>${item.url}</p><pre>${item.error}</pre></div>`;
    }
    const st = item.status;
    const rounds = Object.values(st.rounds || {});
    const rows = rounds.map(r => `<tr><td>${r.round_number}</td><td>${r.ready}</td><td>${r.finalized}</td><td>${r.received_peer_count}/${r.required_peer_updates}</td><td>${(r.missing_peers||[]).join(', ')}</td><td>${r.partial_ready}</td></tr>`).join('');
    return `<div class="card node"><h2>${id} <span class="ok">ONLINE</span></h2>
      <p>${item.url} - mode: ${st.security_mode || 'none'} - peers: ${(st.peer_ids||[]).join(', ')} - key: ${st.public_key_id}</p>
      <table><thead><tr><th>Round</th><th>Ready</th><th>Finalized</th><th>Peers</th><th>Missing</th><th>Partial</th></tr></thead><tbody>${rows || '<tr><td colspan="6">No rounds yet</td></tr>'}</tbody></table>
      <pre>${JSON.stringify(st.metrics, null, 2)}</pre></div>`;
  }).join('');
}
refresh(); setInterval(refresh, 2000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    nodes: dict[str, str] = {}
    admin_token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/status":
            if not is_dashboard_request_authorized(
                self.admin_token,
                token_from_request(self.path, self.headers),
            ):
                body = json.dumps({"error": "invalid dashboard token"}).encode("utf-8")
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps(collect_status(self.nodes), sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/":
            body = dashboard_html().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Secure DFL operator dashboard")
    parser.add_argument(
        "--nodes",
        default=os.getenv(
            "DASHBOARD_NODES",
            "node0=http://localhost:9100,node1=http://localhost:9101,node2=http://localhost:9102",
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9200)
    parser.add_argument(
        "--admin-token",
        default=os.getenv("DASHBOARD_ADMIN_TOKEN", ""),
        help="Optional token required for /api/status. Also accepts DASHBOARD_ADMIN_TOKEN.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    DashboardHandler.nodes = parse_nodes(args.nodes)
    DashboardHandler.admin_token = args.admin_token
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Operator dashboard: http://{args.host}:{args.port}")
    if args.admin_token:
        print("Dashboard API token protection is enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
