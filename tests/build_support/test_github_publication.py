from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from bot.installation.install_bundle import build_install_bundle, sha256_file
from scripts.build_support.github_publication import (
    GitHubPublicationError,
    GitHubReleaseClient,
    ReleaseAsset,
    ReleaseState,
    publish_install_bundle,
    validate_publication_input,
)


class _FakeGitHubClient:
    def __init__(self, release: ReleaseState, stored: dict[str, bytes]) -> None:
        self.current = release
        self.stored = dict(stored)
        self.uploads: list[str] = []

    def stable_release(self, tag: str, *, source_revision: str) -> ReleaseState:
        if self.current.tag != tag or self.current.target_commitish != source_revision:
            raise AssertionError((self.current, tag, source_revision))
        return self.current

    def asset_matches(
        self,
        *,
        release: ReleaseState,
        asset: ReleaseAsset,
        local_path: pathlib.Path,
    ) -> bool:
        del release
        return self.stored.get(asset.name) == local_path.read_bytes()

    def upload_asset(
        self,
        *,
        release: ReleaseState,
        local_path: pathlib.Path,
    ) -> ReleaseState:
        self.uploads.append(local_path.name)
        self.stored[local_path.name] = local_path.read_bytes()
        asset = ReleaseAsset(
            name=local_path.name,
            size=local_path.stat().st_size,
            digest=f"sha256:{sha256_file(local_path)}",
            created_at="9999-01-01T00:00:00Z",
        )
        assets = [item for item in release.assets if item.name != local_path.name]
        self.current = replace(release, assets=tuple((*assets, asset)))
        return self.current


class GitHubPublicationTests(unittest.TestCase):
    @staticmethod
    def _write_source(root: pathlib.Path) -> pathlib.Path:
        source = root / "source"
        dist = source / "bot" / "web_assets" / "dist"
        dist.mkdir(parents=True)
        for name in (
            "index.html",
            "THIRD_PARTY_NOTICES.html",
            "THIRD_PARTY_NOTICES.md",
            "THIRD_PARTY_SBOM.json",
        ):
            (dist / name).write_text(name, encoding="utf-8")
        (dist.parent / "THIRD_PARTY_NOTICES.md").write_text("notice", encoding="utf-8")
        (source / "requirements.lock").write_text("aiohttp==3.14.3\n", encoding="utf-8")
        return source

    @staticmethod
    def _wheel_builder(**kwargs) -> pathlib.Path:
        version = "4.0.0"
        wheel = kwargs["output_dir"] / f"focus-{version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("bot/__init__.py", "")
            for name in (
                "bot/web_assets/dist/index.html",
                "bot/web_assets/dist/THIRD_PARTY_NOTICES.html",
                "bot/web_assets/dist/THIRD_PARTY_NOTICES.md",
                "bot/web_assets/dist/THIRD_PARTY_SBOM.json",
                "bot/web_assets/THIRD_PARTY_NOTICES.md",
            ):
                archive.writestr(name, name)
            archive.writestr(
                f"focus-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.4\nName: focus\nVersion: {version}\n\n",
            )
        return wheel

    def _publication(self, root: pathlib.Path):
        with patch(
            "bot.installation.install_bundle.build_validated_wheel",
            side_effect=self._wheel_builder,
        ):
            built = build_install_bundle(
                source_dir=self._write_source(root),
                output_dir=root / "output",
                channel="stable",
                source_revision="a" * 40,
                build_id="build-1",
                release_tag="4.0.0",
            )
        assert built.channel_manifest_path is not None
        return validate_publication_input(
            channel="stable",
            bundle_path=built.bundle_path,
            channel_manifest_path=built.channel_manifest_path,
        )

    @staticmethod
    def _release(
        *,
        assets: tuple[ReleaseAsset, ...] = (),
        release_id: int = 1,
        draft: bool = False,
        prerelease: bool = False,
        tag: str = "4.0.0",
    ) -> ReleaseState:
        return ReleaseState(
            release_id=release_id,
            tag=tag,
            target_commitish="a" * 40,
            draft=draft,
            prerelease=prerelease,
            published_at="2026-01-01T00:00:00Z",
            assets=assets,
        )

    @staticmethod
    def _api_payload(release: ReleaseState) -> dict[str, object]:
        return {
            "id": release.release_id,
            "tag_name": release.tag,
            "target_commitish": release.target_commitish,
            "draft": release.draft,
            "prerelease": release.prerelease,
            "published_at": release.published_at,
            "assets": [
                {
                    "name": asset.name,
                    "size": asset.size,
                    "digest": asset.digest,
                    "created_at": asset.created_at,
                }
                for asset in release.assets
            ],
        }

    def test_stable_publishes_bundle_then_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            publication = self._publication(pathlib.Path(tmpdir))
            client = _FakeGitHubClient(self._release(), {})
            self.assertEqual(publish_install_bundle(publication, client=client), ())
        self.assertEqual(
            client.uploads,
            [publication.bundle_path.name, publication.channel_manifest_path.name],
        )

    def test_stable_publication_never_overwrites_different_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            publication = self._publication(root)
            existing = ReleaseAsset(
                name=publication.bundle_path.name,
                size=5,
                digest=None,
                created_at="2026-01-01T00:00:00Z",
            )
            client = _FakeGitHubClient(self._release(assets=(existing,)), {existing.name: b"wrong"})
            with self.assertRaisesRegex(GitHubPublicationError, "immutable"):
                publish_install_bundle(publication, client=client)
            self.assertEqual(client.uploads, [])

    def test_stable_publication_is_idempotent_for_identical_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            publication = self._publication(root)
            paths = (publication.bundle_path, publication.channel_manifest_path)
            assets = tuple(
                ReleaseAsset(
                    name=path.name,
                    size=path.stat().st_size,
                    digest=f"sha256:{sha256_file(path)}",
                    created_at="2026-01-01T00:00:00Z",
                )
                for path in paths
            )
            client = _FakeGitHubClient(
                self._release(assets=assets),
                {path.name: path.read_bytes() for path in paths},
            )
            self.assertEqual(publish_install_bundle(publication, client=client), ())
            self.assertEqual(client.uploads, [])

    def test_publication_preflight_rejects_dirty_source_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            publication = self._publication(root)
            payload = json.loads(publication.channel_manifest_path.read_text(encoding="utf-8"))
            payload["source_revision"] = "a" * 40 + "+dirty"
            publication.channel_manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GitHubPublicationError, "40位.*commit SHA"):
                validate_publication_input(
                    channel="stable",
                    bundle_path=publication.bundle_path,
                    channel_manifest_path=publication.channel_manifest_path,
                )

    def test_github_client_finds_release_when_tag_endpoint_returns_404(self) -> None:
        client = GitHubReleaseClient(repository="owner/repository")
        release = self._release(release_id=42)
        responses = (
            SimpleNamespace(returncode=1, stdout="", stderr="HTTP 404: Not Found"),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps([self._api_payload(release)]),
                stderr="",
            ),
        )
        with patch.object(client, "_run", side_effect=responses) as run:
            self.assertEqual(client.release(release.tag), release)
        self.assertIn("/releases/tags/4.0.0", run.call_args_list[0].args[1])
        self.assertIn("/releases?per_page=100&page=1", run.call_args_list[1].args[1])

    def test_github_client_resolves_annotated_release_tag_to_commit(self) -> None:
        client = GitHubReleaseClient(repository="owner/repository")
        tag_sha = "b" * 40
        revision = "a" * 40
        responses = (
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"ref": "refs/tags/4.0.0", "object": {"type": "tag", "sha": tag_sha}}),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"object": {"type": "commit", "sha": revision}}),
                stderr="",
            ),
        )
        with patch.object(client, "_run", side_effect=responses) as run:
            self.assertEqual(client.tag_commit("4.0.0"), revision)
        self.assertIn("/git/ref/tags/4.0.0", run.call_args_list[0].args[1])
        self.assertIn(f"/git/tags/{tag_sha}", run.call_args_list[1].args[1])


if __name__ == "__main__":
    unittest.main()
