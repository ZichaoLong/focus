"""Single configuration authority, migration checkpoints and instance isolation."""

import json
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch

import pytest
import yaml

from bot.codex_config import CodexConfig
from bot.data_retention_contract import DataRetentionPolicy
from bot.stores.data_retention_store import DataRetentionStore


def legacy(root, **overrides):
    path = root / 'data_retention.json'
    path.write_text(json.dumps({'schema_version': 1, 'records_days': 7, 'attachments_days': 90, **overrides}))
    return path


def _update(data_dir, config_dir, changes):
    return DataRetentionStore(data_dir, config_dir=config_dir).update(changes)


@pytest.mark.parametrize('key', ['records_retention_days', 'attachments_retention_days'])
@pytest.mark.parametrize('value', [True, 30.0, '30', None, 0, 14, 365])
def test_yaml_schema_rejects_non_options(key, value):
    with pytest.raises(ValueError, match=key):
        CodexConfig.from_dict({key: value})


def test_defaults_are_read_only_and_external_yaml_edits_are_live(tmp_path):
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    assert store.load() == DataRetentionPolicy()
    assert list(tmp_path.iterdir()) == []
    store.update({'records_days': 7})
    raw = yaml.safe_load(store.path.read_text())
    assert raw == {'records_retention_days': 7}
    store.path.write_text('records_retention_days: 90\nattachments_retention_days: 7\n')
    assert store.load() == DataRetentionPolicy(90, 7)
    assert not (tmp_path / 'data_retention.json').exists()


def test_migration_fills_only_missing_yaml_keys_and_retires_legacy(tmp_path):
    old = legacy(tmp_path)
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    store.path.parent.mkdir()
    store.path.write_text('model: custom-model\nrecords_retention_days: 30\nsource_kinds: [cli, appServer]\n')
    assert store.load() == DataRetentionPolicy(30, 90)
    assert not old.exists()
    assert yaml.safe_load(store.path.read_text()) == {
        'model': 'custom-model', 'records_retention_days': 30,
        'attachments_retention_days': 90, 'source_kinds': ['cli', 'appServer'],
    }
    assert DataRetentionStore(tmp_path, config_dir=store.path.parent).load() == DataRetentionPolicy(30, 90)


def test_failed_migration_write_keeps_original_settings_and_retry_is_safe(tmp_path):
    old = legacy(tmp_path)
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    with patch('bot.stores.data_retention_store.atomic_write_text', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            store.load()
    assert old.exists() and not store.path.exists()
    assert store.load() == DataRetentionPolicy(7, 90)
    assert not old.exists()


def test_committed_yaml_survives_interrupted_legacy_retirement(tmp_path):
    old = legacy(tmp_path)
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    real_unlink = type(old).unlink
    def fail_retirement(path, *args, **kwargs):
        if path == old:
            raise OSError('interrupted after YAML commit')
        return real_unlink(path, *args, **kwargs)
    with patch.object(type(old), 'unlink', fail_retirement):
        with pytest.raises(OSError):
            store.load()
    assert store.path.exists() and old.exists()
    # Committed explicit YAML is authoritative even if the obsolete file is corrupt.
    old.write_text('{broken')
    assert store.load() == DataRetentionPolicy(7, 90)
    assert not old.exists()


@pytest.mark.parametrize('content', ['{broken', '{"schema_version": 2}',
                                   '{"schema_version":1,"records_days":true,"attachments_days":90}'])
def test_unmigratable_legacy_never_authorizes_defaults_or_overwrite(tmp_path, content):
    old = tmp_path / 'data_retention.json'
    old.write_text(content)
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.update({'records_days': 30})
    assert old.read_text() == content and not store.path.exists()


def test_concurrent_process_updates_migration_and_unrelated_config_are_preserved(tmp_path):
    old = legacy(tmp_path)
    directory = tmp_path / 'config'
    directory.mkdir()
    (directory / 'codex.yaml').write_text('model: keep-model\n')
    with ProcessPoolExecutor(2) as pool:
        results = [pool.submit(_update, tmp_path, directory, change)
                   for change in ({'records_days': 90}, {'attachments_days': 7})]
        for result in results:
            result.result(timeout=20)
    assert DataRetentionStore(tmp_path, config_dir=directory).load() == DataRetentionPolicy(90, 7)
    assert yaml.safe_load((directory / 'codex.yaml').read_text())['model'] == 'keep-model'
    assert not old.exists()


def test_explicit_replacement_of_both_periods_can_repair_corrupt_legacy(tmp_path):
    old = tmp_path / 'data_retention.json'
    old.write_text('{broken')
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    assert store.update({'records_days': 30, 'attachments_days': 90}) == DataRetentionPolicy(30, 90)
    assert not old.exists()
    assert store.load() == DataRetentionPolicy(30, 90)


def test_named_instance_policy_does_not_inherit_caller_or_default(tmp_path, monkeypatch):
    monkeypatch.setenv('FOCUS_CONFIG_ROOT', str(tmp_path / 'config'))
    monkeypatch.setenv('FOCUS_DATA_ROOT', str(tmp_path / 'data'))
    monkeypatch.setenv('FOCUS_INSTANCE', 'default')
    default = DataRetentionStore(tmp_path / 'data')
    named = DataRetentionStore(tmp_path / 'data' / 'instances' / 'named')
    default.update({'records_days': 7})
    assert named.load() == DataRetentionPolicy()
    named.update({'attachments_days': 90})
    assert named.load() == DataRetentionPolicy(30, 90)
    assert default.load() == DataRetentionPolicy(7, 30)
