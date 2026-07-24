"""HTTP node agent for signed peer exchange and neighborhood aggregation."""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .config import NodeConfig
from .crypto import (
    derive_demo_private_key,
    load_private_key,
    trusted_keys_from_file,
)
from .protocol import UpdateEnvelope, create_envelope
from .runtime import NodeRuntime


class NodeService:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        if config.private_key_file:
            private_key = load_private_key(config.private_key_file)
        else:
            assert config.demo_identity_seed is not None
            print("WARNING: deterministic demo identities are active; do not use them in production.")
            private_key = derive_demo_private_key(config.node_id, config.demo_identity_seed)
        if config.trusted_keys_file:
            trusted_keys = trusted_keys_from_file(config.trusted_keys_file)
        else:
            assert config.demo_identity_seed is not None
            trusted_keys = {
                peer_id: derive_demo_private_key(peer_id, config.demo_identity_seed).public_key()
                for peer_id in config.peer_urls
            }
        self.runtime = NodeRuntime(
            node_id=config.node_id,
            experiment_id=config.experiment_id,
            peer_ids=list(config.peer_urls),
            private_key=private_key,
            trusted_keys=trusted_keys,
            data_dir=config.data_dir,
            max_payload_bytes=config.max_payload_bytes,
            min_peer_updates_to_finalize=config.min_peer_updates_to_finalize,
            security_mode=config.security_mode,
        )

    def broadcast(self, round_number: int, payload: bytes) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for peer_id, base_url in self.config.peer_urls.items():
            envelope = create_envelope(
                private_key=self.runtime.private_key,
                experiment_id=self.config.experiment_id,
                round_number=round_number,
                sender_id=self.config.node_id,
                recipient_id=peer_id,
                payload=payload,
                security_mode=self.config.security_mode,
                max_payload_bytes=self.config.max_payload_bytes,
            )
            request = urllib.request.Request(
                f"{base_url}/v1/rounds/{round_number}/updates",
                data=json.dumps(envelope.to_dict()).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.config.request_timeout_seconds
                ) as response:
                    results[peer_id] = json.loads(response.read().decode("utf-8"))
                self.runtime.increment_metric("sent_updates_total")
                self.runtime.increment_metric("sent_bytes_total", len(payload))
                if envelope.security_mode == "masking":
                    self.runtime.increment_metric("masked_updates_sent_total")
                    self.runtime.increment_metric(
                        "sent_masking_overhead_bytes_total",
                        envelope.masking_overhead_bytes,
                    )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self.runtime.increment_metric("send_failures_total")
                results[peer_id] = {"accepted": False, "error": str(exc)}
        return results


class NodeRequestHandler(BaseHTTPRequestHandler):
    server_version = "SecureDFLNode/0.1"

    @property
    def service(self) -> NodeService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.service.config.node_id}] {self.address_string()} - {fmt % args}")

    def _json(self, status: int, body: MappingLike) -> None:
        payload = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.service.config.max_payload_bytes * 4:
            raise ValueError("invalid request size")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _require_admin(self) -> None:
        if self.headers.get("X-DFL-Admin-Token") != self.service.config.admin_token:
            raise PermissionError("invalid admin token")

    def _round_path(self, suffix: str) -> int | None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["v1", "rounds"] and parts[3] == suffix:
            return int(parts[2])
        return None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok", "node_id": self.service.config.node_id})
                return
            if path in {"/v1/node", "/v1/status"}:
                self._json(HTTPStatus.OK, self.service.runtime.node_status())
                return
            if path == "/metrics":
                payload = self.service.runtime.metrics_text().encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            round_number = self._round_path("status")
            if round_number is not None:
                self._json(HTTPStatus.OK, self.service.runtime.round_status(round_number))
                return
            if path == "/":
                html = dashboard_html(self.service.config.node_id).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            round_number = self._round_path("local-state")
            if round_number is not None:
                self._require_admin()
                body = self._read_json()
                payload = base64.b64decode(str(body["payload_b64"]), validate=True)
                digest = self.service.runtime.register_local_payload(round_number, payload)
                broadcasts = self.service.broadcast(round_number, payload)
                self._json(
                    HTTPStatus.OK,
                    {"registered": True, "payload_hash": digest, "broadcasts": broadcasts},
                )
                return
            round_number = self._round_path("updates")
            if round_number is not None:
                body = self._read_json()
                envelope = UpdateEnvelope.from_dict(body)
                if envelope.round_number != round_number:
                    raise ValueError("round number does not match request path")
                result = self.service.runtime.accept_peer_envelope(envelope)
                self._json(HTTPStatus.OK, result)
                return
            round_number = self._round_path("finalize")
            if round_number is not None:
                self._require_admin()
                payload, status = self.service.runtime.finalize_round(round_number)
                self._json(
                    HTTPStatus.OK,
                    {
                        **status,
                        "aggregate_payload_b64": base64.b64encode(payload).decode("ascii"),
                    },
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except PermissionError as exc:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


MappingLike = dict[str, Any]


class SecureDFLHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, service: NodeService):
        super().__init__(address, handler)
        self.service = service


def dashboard_html(node_id: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">
<title>Secure DFL Node {node_id}</title>
<style>body{{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#172033}}
pre{{background:#f2f4f7;padding:18px;border-radius:8px;overflow:auto}}h1{{color:#17365d}}</style></head>
<body><h1>Secure DFL Node: {node_id}</h1><p>Live node status, signed peer exchange and decentralized rounds.</p>
<pre id=\"status\">Loading...</pre><script>
async function refresh(){{const r=await fetch('/v1/status');document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2)}}
refresh();setInterval(refresh,2000);</script></body></html>"""


def build_server(config: NodeConfig) -> SecureDFLHTTPServer:
    service = NodeService(config)
    server = SecureDFLHTTPServer((config.host, config.port), NodeRequestHandler, service)
    if config.tls_cert_file:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(config.tls_cert_file, config.tls_key_file)
        if config.tls_ca_file:
            context.load_verify_locations(config.tls_ca_file)
        if config.tls_require_client_cert:
            context.verify_mode = ssl.CERT_REQUIRED
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Secure DFL network node")
    parser.add_argument("--print-config", action="store_true")
    args = parser.parse_args()
    config = NodeConfig.from_env()
    if args.print_config:
        print(config)
    server = build_server(config)
    scheme = "https" if config.tls_cert_file else "http"
    print(
        f"Secure DFL node {config.node_id} listening on {scheme}://{config.host}:{config.port}; "
        f"peers={sorted(config.peer_urls)}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
