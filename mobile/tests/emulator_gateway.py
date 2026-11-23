"""Isolated Basic, trusted-proxy and local Focus gateways for an Android emulator."""
# ruff: noqa: E402 -- Direct execution adds the repository root before importing the gateway fixture.
import argparse
from dataclasses import fields, MISSING, replace
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


def serve(lab, disconnect_grace, forward_port, session_lifetime, second_basic, https_count, navigation, records=False):
    if not (ROOT / "bot/web_assets/dist/focus-connect.txt").is_file():
        raise SystemExit("Build web/ before running the emulator fixture")
    prefix = "https://10.0.2.2:"
    config = ["{", "admin off", "auto_https off", "persist_config off", "default_sni 10.0.2.2", "}"]
    gateways = []
    runtimes = []
    entries = []
    state = lab / "instances.json"
    previous = json.loads(state.read_text()) if state.exists() else []
    sample = lab / "sample.txt"
    sample.write_bytes(b"Focus mobile transfer\n" * 8000)
    guest = prefix + str(port()) if navigation else ""
    catalog = lab / "navigation.md"
    if navigation:
        catalog.write_text(f"# Navigation catalog\n\n[Open child](sample.txt)\n\n[Open article]({guest}/jump)\n")
    gateway_options = {"static_dir": ROOT / "bot/web_assets/dist", "disconnect_grace_seconds": disconnect_grace}
    if session_lifetime is not None:
        gateway_options.update(session_ttl_seconds=session_lifetime, session_max_lifetime_seconds=session_lifetime)
    for index in range(https_count + 1):
        runtime = WebRuntimeControllerHarness()
        runtime.setUp()
        runtimes.append(runtime)
        runtime.fake.history_mode = "legacy"
        runtime.fake.extra_summaries.append(replace(runtime.fake.summary(), thread_id="thread-2", name="Second conversation"))
        runtime.fake.turns = [
            {"id": f"mobile-{n}", "status": "completed", "items": [
                {"id": f"q-{n}", "type": "userMessage", "content": [
                    {"type": "text", "text": f"Focus mobile export check {n}"}]},
                {"id": f"a-{n}", "type": "agentMessage", "phase": "final_answer",
                 "text": f"Reading position {n}. " + "A paragraph in the mobile test conversation. " * 14},
            ]} for n in range(12)
        ]
        runtime.fake.turns[-1]["items"][-1]["text"] += f"\n\n[Download sample]({sample})"
        if navigation:
            runtime.fake.turns[-1]["items"][-1]["text"] += f"\n\n[Navigation catalog]({catalog})\n\n[Open article]({guest}/jump)"
        if records:
            from records_history import install_record_history
            install_record_history(runtime.fake, index)
        controller = runtime.controller
        retention = DataRetentionService(DataRetentionStore(runtime.workspace.parent, config_dir=runtime.workspace.parent / "config"), {})
        for tid in ("thread-1", "thread-2"):
            controller.run_prepared_thread_read(controller.prepare_read_thread("tab-1", tid, open_in_browser=True))
        ports = {field.name: getattr(controller, field.name) for field in fields(WebGatewayPorts)
                 if field.default is MISSING and hasattr(controller, field.name)}
        ports.update(mobile_record_states=controller.mobile_record_states, data_retention_read=retention.policy, data_retention_update=retention.update,
                     operator_status=lambda: {"status": "ok", "warnings": [], "observed_at": time.time(),
                                               "runtime_loop": {}, "poll_after_seconds": 15},
                     backend_reset_preview=lambda: {}, backend_reset_execute=lambda **_: {},
                     abandon_prepared_thread_read=lambda _: True, abandon_prepared_prompt=controller.abandon_prompt)
        if index == https_count:
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
        old = previous[index] if index < len(previous) and previous[index]['origin'].startswith(prefix) else {}
        origin = old.get('origin') or prefix + str(port())
        gateway = WebGateway(config=WebGatewayConfig(**gateway_options, port=upstream, trusted_proxy_origin=origin,
                             trusted_proxy_proof_sha256=hashlib.sha256(proof.encode()).hexdigest()),
                             data_dir=runtime.workspace.parent, projection=runtime.projection, ports=WebGatewayPorts(**ports))
        gateway.start()
        gateways.append(gateway)
        config += [origin + " {", "bind 127.0.0.1", f'tls "{lab / "server.pem"}" "{lab / "server.key"}"']
        if navigation:
            config.append(f"redir /test-sso {guest}/signin-{index} 302")
        password = ""
        if index == 0 or (index == 1 and second_basic):
            password = old.get("password") or secrets.token_hex(6)
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
    if navigation:
        config += [guest + " {", "bind 127.0.0.1", f'tls "{lab / "server.pem"}" "{lab / "server.key"}"',
                   "redir /jump /article 302", "route /article {",
                   "@credential header Authorization *", 'respond @credential "Unexpected credentials" 403',
                   "@cookie header Cookie *", 'respond @cookie "Unexpected cookies" 403',
                   'respond "External article" 200', "}"]
        for index, entry in enumerate(entries[:https_count]):
            config += [f"header /signin-{index} Content-Type text/html",
                       f'respond /signin-{index} `<a href="/return-{index}">Continue to Focus</a>`',
                       f"redir /return-{index} {entry['origin']}/?focusApp=1&thread=thread-1 302"]
        config += ["}"]
        (lab / "guest-origin.txt").write_text(guest)
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
    parser.add_argument("--https-count", type=int, choices=range(2, 7), default=2,
                        help="number of HTTPS entries for page retention and LRU tests")
    parser.add_argument("--navigation", action="store_true", help="add an isolated redirected article, sign-in round trip and nested file")
    parser.add_argument("--records", action="store_true", help="serve long paginated transcripts with two groups of 80 tools")
    args = parser.parse_args()
    serve(args.lab.resolve(), args.disconnect_grace, args.basic_forward_port, args.session_lifetime, args.second_basic, args.https_count, args.navigation, args.records)
