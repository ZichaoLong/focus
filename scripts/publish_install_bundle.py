#!/usr/bin/env python3
"""Explicitly publish a prebuilt Focus install bundle to GitHub Releases."""

from __future__ import annotations

import argparse
import pathlib
import sys


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_support.github_publication import (  # noqa: E402
    DEFAULT_REPOSITORY,
    GitHubPublicationError,
    GitHubReleaseClient,
    publish_install_bundle,
    validate_publication_input,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish one already-built Focus install bundle. This is the only "
            "repository command that uploads install artifacts."
        )
    )
    parser.add_argument("--bundle", required=True, type=pathlib.Path)
    parser.add_argument("--channel-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        publication = validate_publication_input(
            channel="stable",
            bundle_path=args.bundle,
            channel_manifest_path=args.channel_manifest,
        )
        warnings = publish_install_bundle(
            publication,
            client=GitHubReleaseClient(repository=args.repository),
        )
    except GitHubPublicationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"published {publication.bundle_path.name} to "
        f"{args.repository}@{publication.manifest.release_tag}"
    )
    for warning in warnings:
        print(f"cleanup warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
