from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.installed_build_identity import InstalledBuildIdentity, write_installed_build_identity
from bot.installation import installer, update, update_discovery
from bot.installation.update import FocusUpdateController, UpdateError


REV = "a" * 40
REQUEST = "b" * 32


def identity(root, rev=REV, channel="local"):
    write_installed_build_identity(root, InstalledBuildIdentity("1.0", channel, "build1", rev))


@pytest.fixture
def batch(tmp_path, monkeypatch):
    client = FocusUpdateController(global_data_root=tmp_path)
    monkeypatch.setattr(update, "unavailable_reason", lambda: "")
    launch = Mock()
    monkeypatch.setattr(update, "launch_worker", launch)
    candidate = Mock(return_value=dict(revision=REV, version="", build_id="", digest=""))
    monkeypatch.setattr(update, "resolve_candidate", candidate)
    return client, launch, candidate


def prepare(client, target="installed", previous="", request=REQUEST):
    return client.prepare_latest(client.installation_status()["installation_id"], target, previous, request)


def test_identity_is_scoped_to_the_shared_installation(tmp_path):
    def identify(root):
        return FocusUpdateController(global_data_root=root).installation_status()["installation_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        observed = list(pool.map(identify, [tmp_path] * 8))
    assert len(set(observed)) == 1
    assert identify(tmp_path / "other") != observed[0]
    (tmp_path / "web-update-installation-id").write_text("damaged")
    with pytest.raises(UpdateError):
        identify(tmp_path)


def test_current_channel_only_reads_verified_metadata(batch, tmp_path):
    client, launch, resolve = batch
    identity(tmp_path)
    assert prepare(client)["outcome"] == "current"
    assert resolve.call_args.args == ("main", {"url": update.DEFAULT_SOURCE, "branch": "main"}, tmp_path)
    identity(tmp_path, channel="stable")
    resolve.return_value.update(version="1.0", build_id="build1", digest="c" * 64)
    assert prepare(client)["outcome"] == "current"
    assert resolve.call_args.args == ("stable", None, tmp_path)
    launch.assert_not_called()
    assert not client.journal.path.exists()


def test_exact_selection_and_reconciliation_after_a_lost_reply(batch, tmp_path):
    client, launch, _ = batch
    with pytest.raises(UpdateError, match="渠道"):
        prepare(client)
    result = prepare(client, "main")
    op = result["operation"]["operation_id"]
    assert op != REQUEST and result["operation"]["requested_commit"] == REV
    restored = FocusUpdateController(global_data_root=tmp_path).installation_status()
    assert (restored["request_id"], restored["operation"]["operation_id"]) == (REQUEST, op)
    with pytest.raises(UpdateError):
        prepare(client, "main")
    client.journal.settle(op, "checking", state="ready", phase="ready", resolved_commit=REV,
                          preflight={"batch_request_id": REQUEST, "python_runtime": {"version": "3.11"}})
    assert prepare(client, "main", op)["operation"]["operation_id"] == op
    assert launch.call_count == 1
    with pytest.raises(UpdateError):
        client.apply(REQUEST, REQUEST)
    client.apply(op, op)
    with pytest.raises(UpdateError):
        client.apply(op, op)
    assert launch.call_count == 2


def test_old_ready_without_current_preflight_is_prepared_again(batch):
    client, launch, _ = batch
    op = prepare(client, "main")["operation"]["operation_id"]
    client.journal.settle(op, "checking", state="ready", phase="ready", resolved_commit=REV, preflight={})
    new = prepare(client, "main", op)
    assert new["operation"]["operation_id"] != op
    assert new["operation"]["state"] == "checking"
    assert launch.call_count == 2


def test_parallel_alias_checks_and_source_change_cannot_race_admission(batch, tmp_path):
    client, launch, resolve = batch
    barrier = Barrier(2)

    def discover(*args):
        barrier.wait(timeout=3)
        return dict(revision=REV, version="", build_id="", digest="")

    resolve.side_effect = discover
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = [pool.submit(prepare, client, "main", "", c * 32) for c in "cd"]
        assert sum(isinstance(f.exception(timeout=5), UpdateError) for f in checks) == 1
    assert launch.call_count == 1
    current = client.journal.read()
    client.journal.settle(current["operation_id"], "checking", state="failed", phase="failed")

    def change_source(*args):
        client.configure_source("https://example.org/another.git", "change-source")
        return dict(revision=REV, version="", build_id="", digest="")

    resolve.side_effect = change_source
    with pytest.raises(UpdateError, match="变化"):
        prepare(client, "main", current["operation_id"])
    assert launch.call_count == 1


def test_stable_pins_the_verified_artifact_and_rejects_a_moved_release(batch, tmp_path, monkeypatch):
    client, _, resolve = batch
    identity(tmp_path, channel="local")
    digest = "d" * 64
    resolve.return_value.update(version="1.0", build_id="build1", digest=digest)
    assert prepare(client, "stable")["outcome"] == "prepared"  # same commit, different channel
    assert client.journal.read()["preflight"]["stable_sha256"] == digest
    manifest = SimpleNamespace(bundle=SimpleNamespace(sha256="e" * 64))
    monkeypatch.setattr(installer, "stable_bundle_metadata", lambda progress: (manifest, "", 1))
    with pytest.raises(SystemExit, match="changed"):
        with installer._resolved_install_bundle(SimpleNamespace(artifact=None), expected_digest=digest):
            pytest.fail("released different bytes")


def test_discovery_resolves_only_the_configured_exact_main_ref(tmp_path, monkeypatch):
    source = {"url": "ssh://git@example.org/fork.git", "branch": "main"}
    lookup = Mock(return_value=REV + "\trefs/heads/main")
    monkeypatch.setattr(update_discovery, "run", lookup)
    assert update_discovery.resolve_candidate("main", source, tmp_path)["revision"] == REV
    assert lookup.call_args.args[0][-2:] == [source["url"], "refs/heads/main"]
    lookup.return_value = REV + "\trefs/tags/main"
    with pytest.raises(UpdateError):
        update_discovery.resolve_candidate("main", source, tmp_path)
