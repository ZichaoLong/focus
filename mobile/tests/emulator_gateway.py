"""Isolated Basic, trusted-proxy and local Focus gateways for an Android emulator."""
import argparse
from dataclasses import fields, MISSING
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bot.web_runtime.gateway import WebGateway, WebGatewayConfig, WebGatewayPorts
from bot.stores.web_gateway_runtime_store import WebGatewayRuntimeStore
from bot.stores.data_retention_store import DataRetentionStore
from bot.data_retention import DataRetentionService
from tests.web_runtime.harness import WebRuntimeControllerHarness


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(lab, disconnect_grace, forward_port, session_lifetime, second_basic):
    if not (ROOT / "bot/web_assets/dist/focus-connect.txt").is_file():
        raise SystemExit("Build web/ before running the emulator fixture")
    prefix = "https://10.0.2.2:"
    config = ["{", "admin off", "auto_https off", "persist_config off", "}"]
    gateways = []
    runtimes = []
    entries = []
    state = lab / "instances.json"
    previous = json.loads(state.read_text()) if state.exists() else []
    sample = lab / "sample.txt"
    sample.write_bytes(b"Focus mobile transfer\n" * 8000)
    gateway_options = {"static_dir": ROOT / "bot/web_assets/dist", "disconnect_grace_seconds": disconnect_grace}
    if session_lifetime is not None:
        gateway_options.update(session_ttl_seconds=session_lifetime, session_max_lifetime_seconds=session_lifetime)
    for index in range(3):
        runtime = WebRuntimeControllerHarness()
        runtime.setUp()
        runtimes.append(runtime)
        runtime.fake.history_mode = "legacy"
        runtime.fake.turns = [{"id": "mobile-read", "status": "completed", "items": [
            {"id": "question", "type": "userMessage", "content": [{"type": "text", "text": "Focus mobile export check"}]},
            {"id": "sample", "type": "agentMessage", "phase": "final_answer", "text": f"[Download sample]({sample})"}
        ]}]
        controller = runtime.controller
        retention = DataRetentionService(DataRetentionStore(runtime.workspace.parent, config_dir=runtime.workspace.parent / "config"), {})
        controller.run_prepared_thread_read(controller.prepare_read_thread("tab-1", "thread-1", open_in_browser=True))
        ports = {field.name: getattr(controller, field.name) for field in fields(WebGatewayPorts)
                 if field.default is MISSING and hasattr(controller, field.name)}
        ports.update(data_retention_read=retention.policy, data_retention_update=retention.update,
                     operator_status=lambda: {"status": "ok", "warnings": [], "observed_at": time.time(),
                                               "runtime_loop": {}, "poll_after_seconds": 15},
                     backend_reset_preview=lambda: {}, backend_reset_execute=lambda **_: {},
                     abandon_prepared_thread_read=lambda _: True, abandon_prepared_prompt=controller.abandon_prompt)
        if index == 2:
            # adb reverse can expose this exact loopback authority to the emulator.
            gateway = WebGateway(config=WebGatewayConfig(**gateway_options), data_dir=runtime.workspace.parent,
                                 projection=runtime.projection, ports=WebGatewayPorts(**ports))
            endpoint = gateway.start()
            gateways.append(gateway)
            record = WebGatewayRuntimeStore(runtime.workspace.parent).load()
            assert record is not None
            (lab / "local-link.txt").write_text(endpoint + "/#token=" + record.bootstrap_token)
            entries.append({"origin": endpoint, "password": ""})
            continue
        proof = secrets.token_urlsafe(32)
        upstream = port()
        origin = previous[index]['origin'] if previous else prefix + str(port())
        gateway = WebGateway(config=WebGatewayConfig(**gateway_options, port=upstream, trusted_proxy_origin=origin,
                             trusted_proxy_proof_sha256=hashlib.sha256(proof.encode()).hexdigest()),
                             data_dir=runtime.workspace.parent, projection=runtime.projection, ports=WebGatewayPorts(**ports))
        gateway.start()
        gateways.append(gateway)
        config += [origin + " {", "bind 127.0.0.1", f'tls "{lab / "server.pem"}" "{lab / "server.key"}"']
        password = ""
        if index == 0 or second_basic:
            password = (previous[index]["password"] if previous else "") or secrets.token_hex(6)
            hashed = subprocess.run(["caddy", "hash-password"], input=(password + "\n").encode(), capture_output=True, check=True).stdout.decode().strip()
            config += ["basic_auth {", "tester " + hashed, "}"]
        proxy_port = upstream
        if index == 0 and forward_port is not None:
            (lab / "forward-target.txt").write_text(str(upstream))
            proxy_port = forward_port
        config += [f"reverse_proxy 127.0.0.1:{proxy_port} {{", "header_up -Authorization",
                   "header_up X-Focus-Trusted-Proxy-Proof " + proof, "header_up X-Focus-Trusted-Proxy-Identity test",
                   "}", "}"]
        entries.append({"origin": origin, "password": password})
    path = lab / "Caddyfile"
    path.write_text("\n".join(config) + "\n")
    env = dict(os.environ, XDG_CONFIG_HOME=str(lab), XDG_DATA_HOME=str(lab))
    proxy = subprocess.Popen(["caddy", "run", "--adapter", "caddyfile", "--config", path], env=env)
    try:
        (lab / "instances.json").write_text(json.dumps(entries))
        proxy.wait()
    finally:
        proxy.terminate()
        for gateway, runtime in zip(gateways, runtimes):
            gateway.stop()
            runtime.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path, help="private temporary directory containing server.pem and server.key")
    parser.add_argument("--disconnect-grace", type=float, default=WebGatewayConfig().disconnect_grace_seconds,
                        help="seconds to retain disconnected documents (defaults to normal gateway policy)")
    parser.add_argument("--basic-forward-port", type=int, help="send the test Basic proxy upstream through this loopback forward")
    parser.add_argument("--session-lifetime", type=float, help="set both test session lifetimes in seconds (at least 60)")
    parser.add_argument("--second-basic", action="store_true", help="challenge the second HTTPS entry with a different password")
    args = parser.parse_args()
    serve(args.lab.resolve(), args.disconnect_grace, args.basic_forward_port, args.session_lifetime, args.second_basic)
