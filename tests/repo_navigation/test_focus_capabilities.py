from __future__ import annotations

import copy
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import focus_capabilities


class FocusCapabilityCatalogTests(unittest.TestCase):
    def _fixture(self) -> tuple[pathlib.Path, pathlib.Path, dict[str, object]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)

        files = {
            "bot/__init__.py": "",
            "bot/sample.py": "class Entry:\n    def act(self):\n        return None\n\nclass Owner:\n    pass\n",
            "docs/contracts/sample.md": "# Sample Contract\n\n## Boundary\n",
            "tests/test_sample.py": "def test_sample():\n    assert True\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        payload: dict[str, object] = {
            "schema_version": 1,
            "capabilities": {
                "sample": {
                    "entry": [{"path": "bot/sample.py", "symbol": "Entry.act"}],
                    "owner": [{"path": "bot/sample.py", "symbol": "Owner"}],
                    "contract": [
                        {"path": "docs/contracts/sample.md", "heading": "Boundary"}
                    ],
                    "focused-test": [
                        {"runner": "pytest", "targets": ["tests/test_sample.py"]}
                    ],
                    "sentinel": [
                        {
                            "runner": "pytest",
                            "targets": ["tests/test_sample.py::test_sample"],
                        }
                    ],
                    "guard": ["source-context"],
                }
            },
        }
        catalog_path = root / "scripts/focus_capabilities.json"
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text(json.dumps(payload), encoding="utf-8")
        return root, catalog_path, payload

    def _write_payload(
        self, catalog_path: pathlib.Path, payload: dict[str, object]
    ) -> None:
        catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_repository_catalog_resolves_every_reviewed_reference(self) -> None:
        catalog = focus_capabilities.load_catalog()

        names = [item.name for item in catalog.capabilities]
        self.assertEqual(names, sorted(set(names)))
        self.assertIn(
            focus_capabilities.SourceReference(
                "web/src/focus/focusHistoryNavigation.ts", "createFocusHistoryNavigation"
            ),
            catalog.require("focus-web-history-navigation").owners,
        )
        for name in ("focus-web-client-state", "focus-web-mutations"):
            with self.subTest(capability=name):
                self.assertIn("web-dependency-direction", catalog.require(name).guards)

    def test_mobile_file_and_guide_refs_resolve_live_without_weakening_symbol_refs(self) -> None:
        root, catalog_path, payload = self._fixture()
        java = "mobile/android/src/org/focus/mobile/Sample.java"
        device = "mobile/tests/device.py"
        guide = "mobile/README.md"
        for relative, content in (
            (java, "class Sample {}\n"),
            (device, "def main():\n    pass\n"),
            (guide, "# Mobile\n\n## Verify\nUse the device.\n"),
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        sample = payload["capabilities"]["sample"]
        sample["owner"] = [{"path": java}]
        sample["platform-check"] = [{"path": guide, "heading": "Verify"}, {"path": device}]
        self._write_payload(catalog_path, payload)
        capability = focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path).require("sample")
        (root / java).write_text("class Sample {\n}\n", encoding="utf-8")
        for ref, start, end in (
            (capability.owners[0], 1, 2),
            (capability.platform_checks[0], 3, 4),
            (capability.platform_checks[1], 1, 2),
        ):
            self.assertEqual(focus_capabilities.source_reference_location(ref, repo_root=root),
                             focus_capabilities.ReferenceLocation(ref.path, start, end))
        for role, ref in (
            ("owner", {"path": "bot/sample.py"}),
            ("owner", {"path": device}),
            ("owner", {"path": java, "symbol": "Sample"}),
            ("contract", {"path": guide, "heading": "Verify"}),
            ("platform-check", {"path": guide}),
            ("platform-check", {"path": guide, "heading": "Missing"}),
            ("platform-check", {"path": java}),
            ("platform-check", {"path": device, "command": "run this"}),
        ):
            with self.subTest(role=role, ref=ref):
                invalid = copy.deepcopy(payload)
                invalid["capabilities"]["sample"][role] = [ref]
                self._write_payload(catalog_path, invalid)
                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_shared_checks_follow_one_guide_in_each_capability(self) -> None:
        root, catalog_path, payload = self._fixture()
        guide = root / "mobile/README.md"
        guide.parent.mkdir()
        guide.write_text("# Mobile\n## Build\n## On device\n", encoding="utf-8")
        build = {"path": "mobile/README.md", "heading": "Build"}
        device = {"path": "mobile/README.md", "heading": "On device"}
        script = {"path": "mobile/android/build.py"}
        (root / script["path"]).parent.mkdir()
        (root / script["path"]).write_text("print('build')\n", encoding="utf-8")
        payload["shared-platform-checks"] = {"build": [build, script]}
        sample = payload["capabilities"]["sample"]
        sample["platform-check"] = [device, "build"]
        payload["capabilities"]["another"] = {**sample, "platform-check": ["build", device]}

        def check_both() -> None:
            self._write_payload(catalog_path, payload)
            catalog = focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
            for name, expected in (
                ("sample", [device, build, script]),
                ("another", [build, script, device]),
            ):
                with self.subTest(name=name, heading=build["heading"]):
                    view = focus_capabilities.capability_payload(catalog.require(name))
                    self.assertEqual(view["platform-check"], expected)

        check_both()
        guide.write_text("# Mobile\n## New build instructions\n## On device\n", encoding="utf-8")
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        build["heading"] = "New build instructions"
        check_both()

    def test_new_capability_is_discoverable_in_a_checkout_without_skills(self) -> None:
        root, catalog_path, payload = self._fixture()
        shutil.copytree(
            focus_capabilities.REPO_ROOT / "scripts",
            catalog_path.parent,
            ignore=shutil.ignore_patterns(catalog_path.name, "__pycache__"),
            dirs_exist_ok=True,
        )
        guide = root / "mobile/README.md"
        guide.parent.mkdir()
        guide.write_text("# Mobile\n## Device\n", encoding="utf-8")
        check = {"path": "mobile/README.md", "heading": "Device"}

        def run(script: str, *args: str) -> dict:
            output = subprocess.check_output(
                [sys.executable, "-E", "-S", f"scripts/{script}.py", *args],
                cwd=root, encoding="utf-8",
            )
            return json.loads(output)

        query = ("list", "--under", "mobile/", "--json")
        self.assertEqual(run("focus_nav", *query)["capabilities"], [])
        name = "new-capability"
        payload["shared-platform-checks"] = {"device": [check]}
        payload["capabilities"][name] = {
            **payload["capabilities"]["sample"], "platform-check": ["device"],
        }
        self._write_payload(catalog_path, payload)

        self.assertEqual(run("focus_nav", *query)["capabilities"], [name])
        self.assertEqual(run("focus_nav", "show", name, "--json")["platform-check"], [check])
        paths = run("focus_nav", "paths", check["path"], "--locations", "--json")["paths"]
        (match,) = paths[0]["matches"]
        self.assertEqual(match["capability"], name)
        self.assertEqual(match["ref"], check)
        self.assertEqual(match["location"]["start_line"], 2)
        plan = run("focus_verify", name, "--dry-run")
        self.assertEqual(plan["platform-check"], [check])
        self.assertTrue(plan["commands"])

    def test_shared_checks_reject_invalid_definitions_and_overlapping_references(self) -> None:
        root, catalog_path, payload = self._fixture()
        guide = root / "mobile/README.md"
        guide.parent.mkdir()
        guide.write_text("# Mobile\n## Build\n", encoding="utf-8")
        ref = {"path": "mobile/README.md", "heading": "Build"}
        cases = (
            ({"build": [ref]}, ["missing"], "unknown platform check"),
            ({"one": [ref], "two": ["one"]}, ["two"], "must be an object"),
            ({"build": [{**ref, "command": "run"}]}, ["build"], "unknown="),
            ({"build": []}, ["build"], "nonempty array"),
            ({"build": [ref, ref]}, ["build"], "duplicate references"),
            ({"build": [ref]}, [ref, "build"], "duplicate references after expansion"),
            ({"one": [ref], "two": [ref]}, ["one", "two"], "duplicate references after expansion"),
        )
        for groups, members, error in cases:
            with self.subTest(groups=groups, members=members):
                payload["shared-platform-checks"] = groups
                payload["capabilities"]["sample"]["platform-check"] = members
                self._write_payload(catalog_path, payload)
                with self.assertRaisesRegex(focus_capabilities.CapabilityMapError, error):
                    focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_reference_locations_are_computed_from_current_sources(self) -> None:
        root, catalog_path, _ = self._fixture()
        (root / "docs/contracts/sample.md").write_text(
            "# Sample Contract\n\n"
            "## Boundary\n"
            "Normative text.\n"
            "### Detail\n"
            "More text.\n"
            "## Next\n",
            encoding="utf-8",
        )
        capability = focus_capabilities.load_catalog(
            repo_root=root, catalog_path=catalog_path
        ).require("sample")

        self.assertEqual(
            focus_capabilities.source_reference_location(
                capability.entries[0], repo_root=root
            ),
            focus_capabilities.ReferenceLocation("bot/sample.py", 2, 3),
        )
        self.assertEqual(
            focus_capabilities.contract_reference_location(
                capability.contracts[0], repo_root=root
            ),
            focus_capabilities.ReferenceLocation("docs/contracts/sample.md", 3, 6),
        )
        self.assertEqual(
            focus_capabilities.verification_target_location(
                "pytest", "tests/test_sample.py::test_sample", repo_root=root
            ),
            focus_capabilities.ReferenceLocation("tests/test_sample.py", 1, 2),
        )

        source_path = root / "bot/sample.py"
        source_path.write_text(
            "\n" + source_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        self.assertEqual(
            focus_capabilities.source_reference_location(
                capability.entries[0], repo_root=root
            ),
            focus_capabilities.ReferenceLocation("bot/sample.py", 3, 4),
        )

    def test_script_locations_use_the_validated_declaration_line(self) -> None:
        root, _, _ = self._fixture()
        ts_path = root / "web/src/focus/sample.ts"
        ts_path.parent.mkdir(parents=True)
        ts_path.write_text(
            "export const OTHER = 1;\n"
            "export function locateMe() {\n"
            "  return OTHER;\n"
            "}\n",
            encoding="utf-8",
        )
        vue_path = root / "web/src/focus/Sample.vue"
        vue_path.write_text(
            '<script setup lang="ts">\n'
            "const other = 1;\n"
            "function locateVue() {}\n"
            "</script>\n"
            "<template><div /></template>\n",
            encoding="utf-8",
        )

        self.assertEqual(
            focus_capabilities.source_reference_location(
                focus_capabilities.SourceReference(
                    "web/src/focus/sample.ts", "locateMe"
                ),
                repo_root=root,
            ),
            focus_capabilities.ReferenceLocation("web/src/focus/sample.ts", 2, 2),
        )
        self.assertEqual(
            focus_capabilities.source_reference_location(
                focus_capabilities.SourceReference(
                    "web/src/focus/Sample.vue", "locateVue"
                ),
                repo_root=root,
            ),
            focus_capabilities.ReferenceLocation("web/src/focus/Sample.vue", 3, 3),
        )

        ts_path.write_text("export const renamed = 1;\n", encoding="utf-8")
        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "resolve exactly once"
        ):
            focus_capabilities.source_reference_location(
                focus_capabilities.SourceReference(
                    "web/src/focus/sample.ts", "locateMe"
                ),
                repo_root=root,
            )

    def test_python_locations_include_decorators(self) -> None:
        root, _, _ = self._fixture()
        source_path = root / "bot/decorated.py"
        source_path.write_text(
            "def register(value):\n"
            "    return value\n\n"
            "@register\n"
            "class Owner:\n"
            "    pass\n",
            encoding="utf-8",
        )
        test_path = root / "tests/test_decorated.py"
        test_path.write_text(
            "import pytest\n\n"
            '@pytest.mark.parametrize("value", [1])\n'
            "def test_case(value):\n"
            "    assert value\n",
            encoding="utf-8",
        )

        self.assertEqual(
            focus_capabilities.source_reference_location(
                focus_capabilities.SourceReference("bot/decorated.py", "Owner"),
                repo_root=root,
            ),
            focus_capabilities.ReferenceLocation("bot/decorated.py", 4, 6),
        )
        self.assertEqual(
            focus_capabilities.verification_target_location(
                "pytest", "tests/test_decorated.py::test_case", repo_root=root
            ),
            focus_capabilities.ReferenceLocation("tests/test_decorated.py", 3, 5),
        )

    def test_directory_verification_target_has_no_false_line_range(self) -> None:
        root, _, _ = self._fixture()
        target = root / "tests/package"
        target.mkdir()

        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "directory-level"
        ):
            focus_capabilities.verification_target_location(
                "pytest", "tests/package", repo_root=root
            )

    def test_duplicate_json_key_is_rejected_before_schema_validation(self) -> None:
        root, catalog_path, _ = self._fixture()
        catalog_path.write_text(
            '{"schema_version":1,"schema_version":1,"capabilities":{}}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "duplicate JSON key"
        ):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_unknown_schema_fields_runner_and_guard_are_rejected(self) -> None:
        mutations = (
            lambda payload: payload.update({"extra": True}),
            lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                {"extra": True}
            ),
            lambda payload: payload["capabilities"]["sample"]["focused-test"][0].update(  # type: ignore[index]
                {"runner": "python"}
            ),
            lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                {"guard": ["arbitrary-command"]}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                root, catalog_path, payload = self._fixture()
                mutate(payload)
                self._write_payload(catalog_path, payload)

                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

    def test_narrative_mutable_and_cached_fields_are_rejected_at_every_level(
        self,
    ) -> None:
        mutations = (
            (
                "capability-description",
                lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                    {"description": "behavior narrative"}
                ),
            ),
            (
                "capability-status",
                lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                    {"status": "reviewed"}
                ),
            ),
            (
                "capability-digest",
                lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                    {"digest": "mutable-content-hash"}
                ),
            ),
            (
                "capability-imports",
                lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                    {"imports": ["bot.other"]}
                ),
            ),
            (
                "capability-commands",
                lambda payload: payload["capabilities"]["sample"].update(  # type: ignore[index]
                    {"commands": ["pytest -q"]}
                ),
            ),
            (
                "source-reason",
                lambda payload: payload["capabilities"]["sample"]["owner"][0].update(  # type: ignore[index]
                    {"reason": "owns the mutable fact"}
                ),
            ),
            (
                "source-semantics",
                lambda payload: payload["capabilities"]["sample"]["entry"][0].update(  # type: ignore[index]
                    {"semantics": "starts the behavior"}
                ),
            ),
            (
                "contract-summary",
                lambda payload: payload["capabilities"]["sample"]["contract"][0].update(  # type: ignore[index]
                    {"summary": "copied contract behavior"}
                ),
            ),
            (
                "verification-command",
                lambda payload: payload["capabilities"]["sample"]["focused-test"][
                    0
                ].update(  # type: ignore[index]
                    {"command": "pytest tests/test_sample.py"}
                ),
            ),
            (
                "verification-result",
                lambda payload: payload["capabilities"]["sample"]["sentinel"][0].update(  # type: ignore[index]
                    {"result": "passed"}
                ),
            ),
            (
                "verification-count",
                lambda payload: payload["capabilities"]["sample"]["sentinel"][0].update(  # type: ignore[index]
                    {"count": 1}
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(field=name):
                root, catalog_path, payload = self._fixture()
                mutate(payload)
                self._write_payload(catalog_path, payload)

                with self.assertRaisesRegex(
                    focus_capabilities.CapabilityMapError, "unknown="
                ):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

    def test_structural_migrations_require_catalog_refs_to_close_together(
        self,
    ) -> None:
        root, catalog_path, payload = self._fixture()

        source = root / "bot/sample.py"
        renamed_source = root / "bot/renamed.py"
        source.rename(renamed_source)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        payload["capabilities"]["sample"]["entry"][0]["path"] = "bot/renamed.py"  # type: ignore[index]
        payload["capabilities"]["sample"]["owner"][0]["path"] = "bot/renamed.py"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        renamed_source.write_text(
            renamed_source.read_text(encoding="utf-8").replace(
                "class Owner:", "class RenamedOwner:"
            ),
            encoding="utf-8",
        )
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        payload["capabilities"]["sample"]["owner"][0]["symbol"] = "RenamedOwner"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        contract = root / "docs/contracts/sample.md"
        renamed_contract = root / "docs/contracts/renamed.md"
        contract.rename(renamed_contract)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        payload["capabilities"]["sample"]["contract"][0]["path"] = (  # type: ignore[index]
            "docs/contracts/renamed.md"
        )
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        renamed_contract.write_text(
            "# Sample Contract\n\n## Renamed Boundary\n", encoding="utf-8"
        )
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        payload["capabilities"]["sample"]["contract"][0]["heading"] = (  # type: ignore[index]
            "Renamed Boundary"
        )
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        test_path = root / "tests/test_sample.py"
        renamed_test = root / "tests/test_renamed.py"
        test_path.rename(renamed_test)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)
        payload["capabilities"]["sample"]["focused-test"][0]["targets"] = [  # type: ignore[index]
            "tests/test_renamed.py"
        ]
        payload["capabilities"]["sample"]["sentinel"][0]["targets"] = [  # type: ignore[index]
            "tests/test_renamed.py::test_sample"
        ]
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_reference_validation_does_not_claim_semantic_equivalence(self) -> None:
        root, catalog_path, _ = self._fixture()

        (root / "bot/sample.py").write_text(
            "class Entry:\n"
            "    def act(self):\n"
            "        return 'changed implementation'\n\n"
            "class Owner:\n"
            "    changed_fact = True\n",
            encoding="utf-8",
        )
        (root / "docs/contracts/sample.md").write_text(
            "# Sample Contract\n\n## Boundary\n\nChanged normative prose.\n",
            encoding="utf-8",
        )
        (root / "tests/test_sample.py").write_text(
            "def test_sample():\n    assert 1 + 1 == 2\n", encoding="utf-8"
        )

        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_noncanonical_missing_and_escaped_source_paths_are_rejected(self) -> None:
        root, catalog_path, baseline = self._fixture()
        outside = root.parent / f"{root.name}-outside.py"
        outside.write_text("class Owner:\n    pass\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        (root / "bot/escape.py").symlink_to(outside)
        invalid_paths = (
            ".",
            "/absolute.py",
            "bot\\sample.py",
            "bot/../bot/sample.py",
            "bot/missing.py",
            "bot/escape.py",
            "docs/_work/history.py",
        )
        for invalid in invalid_paths:
            with self.subTest(path=invalid):
                payload = copy.deepcopy(baseline)
                payload["capabilities"]["sample"]["owner"][0]["path"] = invalid  # type: ignore[index]
                self._write_payload(catalog_path, payload)

                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

    def test_repository_internal_symlink_cannot_change_reference_authority(
        self,
    ) -> None:
        root, catalog_path, baseline = self._fixture()
        work_path = root / "docs/_work/evidence.md"
        work_path.parent.mkdir(parents=True)
        work_path.write_text("# Hidden Authority\n", encoding="utf-8")
        link_path = root / "docs/contracts/link.md"
        link_path.symlink_to(work_path)
        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["contract"][0] = {  # type: ignore[index]
            "path": "docs/contracts/link.md",
            "heading": "Hidden Authority",
        }
        self._write_payload(catalog_path, payload)

        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "must not traverse"
        ):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_python_symbol_and_markdown_heading_must_resolve_exactly_once(self) -> None:
        root, catalog_path, baseline = self._fixture()
        cases = (
            ("symbol", "Missing", None),
            ("symbol", "Owner", "class Owner:\n    pass\n\nclass Owner:\n    pass\n"),
            ("heading", "Missing", None),
            ("heading", "Boundary", "# Boundary\n\n## Boundary\n"),
        )
        for kind, value, replacement in cases:
            with self.subTest(kind=kind, value=value):
                payload = copy.deepcopy(baseline)
                if kind == "symbol":
                    payload["capabilities"]["sample"]["owner"][0]["symbol"] = value  # type: ignore[index]
                    if replacement is not None:
                        (root / "bot/sample.py").write_text(
                            replacement, encoding="utf-8"
                        )
                else:
                    payload["capabilities"]["sample"]["contract"][0]["heading"] = value  # type: ignore[index]
                    if replacement is not None:
                        (root / "docs/contracts/sample.md").write_text(
                            replacement, encoding="utf-8"
                        )
                self._write_payload(catalog_path, payload)

                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

                # Restore source files for the next subtest sharing this fixture.
                (root / "bot/sample.py").write_text(
                    "class Entry:\n    def act(self):\n        return None\n\nclass Owner:\n    pass\n",
                    encoding="utf-8",
                )
                (root / "docs/contracts/sample.md").write_text(
                    "# Sample Contract\n\n## Boundary\n", encoding="utf-8"
                )

    def test_script_comments_vue_templates_and_markdown_fences_do_not_define_refs(
        self,
    ) -> None:
        root, catalog_path, baseline = self._fixture()
        source_path = root / "web/src/focus/fake.ts"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "/*\nexport function Phantom() {}\n*/\n"
            "const text = `function Phantom() {}`;\n"
            "function Outer() {\nfunction NestedOnly() {}\n}\n",
            encoding="utf-8",
        )
        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["owner"][0] = {  # type: ignore[index]
            "path": "web/src/focus/fake.ts",
            "symbol": "Phantom",
        }
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        payload["capabilities"]["sample"]["owner"][0]["symbol"] = "NestedOnly"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        vue_path = root / "web/src/focus/Fake.vue"
        vue_path.write_text(
            '<script setup lang="ts">\n'
            "const holder = (\nfunction NestedOnly() {}\n);\n"
            "function Real() {}\n"
            "</script>\n"
            "<template>\n"
            "<!-- <script setup>\nfunction CommentOnly() {}\n</script> -->\n"
            "function TemplateOnly() {}\n"
            "</template>\n",
            encoding="utf-8",
        )
        payload["capabilities"]["sample"]["owner"][0] = {  # type: ignore[index]
            "path": "web/src/focus/Fake.vue",
            "symbol": "TemplateOnly",
        }
        for symbol in ("TemplateOnly", "CommentOnly", "NestedOnly"):
            with self.subTest(vue_symbol=symbol):
                payload["capabilities"]["sample"]["owner"][0]["symbol"] = symbol  # type: ignore[index]
                self._write_payload(catalog_path, payload)
                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

        payload["capabilities"]["sample"]["owner"][0]["symbol"] = "Real"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        (root / "docs/contracts/sample.md").write_text(
            "<!--\n## Comment Only\n-->\n", encoding="utf-8"
        )
        payload["capabilities"]["sample"]["contract"][0]["heading"] = "Comment Only"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        (root / "docs/contracts/sample.md").write_text(
            "text <!--\n## Inline Comment Only\n-->\n", encoding="utf-8"
        )
        payload["capabilities"]["sample"]["contract"][0]["heading"] = (
            "Inline Comment Only"  # type: ignore[index]
        )
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        (root / "docs/contracts/sample.md").write_text(
            "<pre>\n## Raw HTML Only\n</pre>\n", encoding="utf-8"
        )
        payload["capabilities"]["sample"]["contract"][0]["heading"] = "Raw HTML Only"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        (root / "docs/contracts/sample.md").write_text(
            "```md\n## Fenced Only\n```\n", encoding="utf-8"
        )
        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["contract"][0]["heading"] = "Fenced Only"  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_runner_targets_reject_options_globs_and_unknown_nodes(self) -> None:
        root, catalog_path, baseline = self._fixture()
        invalid_targets = (
            "--collect-only",
            "tests/test_*.py",
            "tests/test_sample.py::missing_test",
            "bot/sample.py",
        )
        for invalid in invalid_targets:
            with self.subTest(target=invalid):
                payload = copy.deepcopy(baseline)
                payload["capabilities"]["sample"]["focused-test"][0]["targets"] = [
                    invalid
                ]  # type: ignore[index]
                self._write_payload(catalog_path, payload)

                with self.assertRaises(focus_capabilities.CapabilityMapError):
                    focus_capabilities.load_catalog(
                        repo_root=root, catalog_path=catalog_path
                    )

    def test_vitest_accepts_only_existing_web_test_files(self) -> None:
        root, catalog_path, baseline = self._fixture()
        test_path = root / "web/src/focus/sample.test.ts"
        test_path.parent.mkdir(parents=True)
        test_path.write_text("export const value = 1;\n", encoding="utf-8")
        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["focused-test"] = [  # type: ignore[index]
            {"runner": "vitest", "targets": ["web/src/focus/sample.test.ts"]}
        ]
        self._write_payload(catalog_path, payload)

        catalog = focus_capabilities.load_catalog(
            repo_root=root, catalog_path=catalog_path
        )
        self.assertEqual(catalog.require("sample").focused_tests[0].runner, "vitest")

        payload["capabilities"]["sample"]["focused-test"][0]["targets"] = [  # type: ignore[index]
            "web/src/focus/not-a-test.ts"
        ]
        (root / "web/src/focus/not-a-test.ts").write_text("", encoding="utf-8")
        self._write_payload(catalog_path, payload)
        with self.assertRaises(focus_capabilities.CapabilityMapError):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

    def test_duplicate_references_and_targets_are_rejected(self) -> None:
        root, catalog_path, baseline = self._fixture()
        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["owner"] *= 2  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "duplicate references"
        ):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        payload = copy.deepcopy(baseline)
        payload["capabilities"]["sample"]["focused-test"][0]["targets"] *= 2  # type: ignore[index]
        self._write_payload(catalog_path, payload)
        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "contains duplicates"
        ):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)

        payload = copy.deepcopy(baseline)
        (root / "tests/test_other.py").write_text(
            "def test_other():\n    assert True\n", encoding="utf-8"
        )
        payload["capabilities"]["sample"]["focused-test"] = [  # type: ignore[index]
            {"runner": "pytest", "targets": ["tests/test_sample.py"]},
            {
                "runner": "pytest",
                "targets": ["tests/test_sample.py", "tests/test_other.py"],
            },
        ]
        self._write_payload(catalog_path, payload)
        with self.assertRaisesRegex(
            focus_capabilities.CapabilityMapError, "duplicate runner target"
        ):
            focus_capabilities.load_catalog(repo_root=root, catalog_path=catalog_path)


if __name__ == "__main__":
    unittest.main()
