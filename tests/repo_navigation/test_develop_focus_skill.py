from __future__ import annotations

import unittest
from urllib.parse import unquote, urlsplit

import yaml

from scripts import check_document_integrity, focus_capabilities


class DevelopmentEntryPointTests(unittest.TestCase):
    def test_human_and_agent_entry_points_reach_the_repository_discipline(self) -> None:
        root = focus_capabilities.REPO_ROOT
        discipline = root / "docs/architecture/development-navigation.zh-CN.md"
        anchors = check_document_integrity.markdown_anchors(discipline.read_text(encoding="utf-8"))
        for entry in (
            root / "README.md",
            root / "mobile/README.md",
            root / ".agents/skills/develop-focus/SKILL.md",
            root / ".agents/skills/navigate-focus-development/SKILL.md",
        ):
            with self.subTest(entry=entry.relative_to(root)):
                links = check_document_integrity.markdown_links(entry.read_text(encoding="utf-8"))
                targets = [urlsplit(link.target) for link in links]
                self.assertTrue(any(
                    not target.scheme and not target.netloc
                    and (entry.parent / unquote(target.path)).resolve() == discipline
                    and (not target.fragment or unquote(target.fragment) in anchors)
                    for target in targets
                ), f"No working link to {discipline.name}")

    def test_develop_focus_requires_explicit_invocation(self) -> None:
        metadata = (
            focus_capabilities.REPO_ROOT / ".agents/skills/develop-focus/agents/openai.yaml"
        )
        policy = yaml.safe_load(metadata.read_text(encoding="utf-8"))["policy"]
        self.assertIs(policy["allow_implicit_invocation"], False)


if __name__ == "__main__":
    unittest.main()
