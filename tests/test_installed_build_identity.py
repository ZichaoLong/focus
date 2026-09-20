from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from bot.installed_build_identity import (
    InstalledBuildIdentity,
    InstalledBuildIdentityError,
    installed_build_identity_path,
    read_installed_build_identity,
    write_installed_build_identity,
)


class InstalledBuildIdentityTests(unittest.TestCase):
    def test_round_trip_preserves_every_install_channel(self) -> None:
        for channel in ("stable", "local"):
            with self.subTest(channel=channel):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = pathlib.Path(tmpdir)
                    identity = InstalledBuildIdentity(
                        version="5.0.0",
                        channel=channel,
                        build_id="build-123",
                        source_revision="a" * 40,
                    )

                    write_installed_build_identity(root, identity)

                    self.assertEqual(read_installed_build_identity(root), identity)
                    self.assertEqual(
                        installed_build_identity_path(root).stat().st_mode & 0o777,
                        0o600,
                    )

    def test_missing_record_is_an_explicit_legacy_install_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(read_installed_build_identity(pathlib.Path(tmpdir)))

    def test_reader_rejects_non_closed_or_untrusted_identity(self) -> None:
        valid = {
            "schema": "focus-installed-build",
            "schema_version": 1,
            "version": "5.0.0",
            "channel": "stable",
            "build_id": "build-123",
            "source_revision": "a" * 40,
        }
        cases = {
            "unknown field": {**valid, "extra": True},
            "unsupported channel": {**valid, "channel": "nightly"},
            "unsafe build": {**valid, "build_id": "build/id"},
            "boolean schema version": {**valid, "schema_version": True},
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = pathlib.Path(tmpdir)
                    path = installed_build_identity_path(root)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(InstalledBuildIdentityError):
                        read_installed_build_identity(root)

    def test_reader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            installed_build_identity_path(root).write_text(
                '{"schema":"focus-installed-build","schema":"duplicate"}',
                encoding="utf-8",
            )

            with self.assertRaises(InstalledBuildIdentityError):
                read_installed_build_identity(root)


if __name__ == "__main__":
    unittest.main()
