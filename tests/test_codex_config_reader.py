import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.codex_config_reader import (
    ResolvedProfileConfig,
    list_profile_v2_names,
    materialize_profile_v2_text,
    resolve_profile_from_codex_config,
    resolve_profile_model_metadata,
)


class CodexConfigReaderTests(unittest.TestCase):
    def test_resolve_profile_reads_profile_v2_fields(self) -> None:
        resolved = self._resolve_from_temp_config(
            base_config="""
model = "global-model"
model_provider = "global-provider"
""",
            profile_name="work",
            profile_config="""
model = "work-model"
model_provider = "work-provider"
""",
        )

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="work-model", model_provider="work-provider"),
        )

    def test_resolve_profile_reads_reasoning_effort(self) -> None:
        resolved = self._resolve_from_temp_config(
            base_config="""
model = "global-model"
model_provider = "global-provider"
model_reasoning_effort = "medium"
""",
            profile_name="work",
            profile_config="""
model = "work-model"
model_provider = "work-provider"
model_reasoning_effort = "high"
""",
        )

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(
                model="work-model",
                model_provider="work-provider",
                reasoning_effort="high",
            ),
        )

    def test_resolve_profile_inherits_top_level_model_and_provider(self) -> None:
        resolved = self._resolve_from_temp_config(
            base_config="""
model = "global-model"
model_provider = "global-provider"
""",
            profile_name="work",
            profile_config="",
        )

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="global-model", model_provider="global-provider"),
        )

    def test_resolve_profile_can_mix_profile_and_top_level_fields(self) -> None:
        resolved = self._resolve_from_temp_config(
            base_config='model_provider = "global-provider"\n',
            profile_name="work",
            profile_config='model = "work-model"\n',
        )

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="work-model", model_provider="global-provider"),
        )

    def test_materialize_profile_v2_text_merges_base_and_profile_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(
                """
model_provider = "custom"
model = "gpt-5.4"

[mcp_servers.docs]
command = "docs-base"
args = ["--shared"]
""".lstrip(),
                encoding="utf-8",
            )
            (codex_home / "moonbridge.config.toml").write_text(
                """
model_provider = "moonbridge"
model = "deepseek-v4-flash"

[mcp_servers.docs]
args = ["--profile"]
env = { MODE = "moonbridge" }
""".lstrip(),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                merged_text = materialize_profile_v2_text("moonbridge")

        merged = tomllib.loads(merged_text)
        self.assertEqual(merged["model_provider"], "moonbridge")
        self.assertEqual(merged["model"], "deepseek-v4-flash")
        self.assertEqual(merged["mcp_servers"]["docs"]["command"], "docs-base")
        self.assertEqual(merged["mcp_servers"]["docs"]["args"], ["--profile"])
        self.assertEqual(merged["mcp_servers"]["docs"]["env"]["MODE"], "moonbridge")

    def test_materialize_profile_v2_text_works_without_base_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "work.config.toml").write_text(
                'model_provider = "work-provider"\nmodel = "work-model"\n',
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                merged_text = materialize_profile_v2_text("work")

        merged = tomllib.loads(merged_text)
        self.assertEqual(merged["model_provider"], "work-provider")
        self.assertEqual(merged["model"], "work-model")

    def test_resolve_profile_works_without_base_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "work.config.toml").write_text(
                """
model = "work-model"
model_provider = "work-provider"
""".lstrip(),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                resolved = resolve_profile_from_codex_config("work")

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="work-model", model_provider="work-provider"),
        )

    def test_resolve_profile_model_metadata_reads_profile_catalog_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            catalog_path = codex_home / "catalog.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "glm-5-turbo",
                                "display_name": "GLM 5 Turbo",
                                "supports_reasoning_summaries": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (codex_home / "config.toml").write_text("", encoding="utf-8")
            (codex_home / "zai.config.toml").write_text(
                (
                    f"""
model = "glm-5-turbo"
model_catalog_json = "{catalog_path}"
"""
                ).lstrip(),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                metadata = resolve_profile_model_metadata("zai")

        self.assertEqual(
            metadata,
            {
                "slug": "glm-5-turbo",
                "display_name": "GLM 5 Turbo",
                "supports_reasoning_summaries": False,
                "model": "glm-5-turbo",
                "displayName": "GLM 5 Turbo",
            },
        )

    def test_resolve_profile_model_metadata_returns_none_without_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text("", encoding="utf-8")
            (codex_home / "work.config.toml").write_text('model = "work-model"\n', encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                metadata = resolve_profile_model_metadata("work")

        self.assertIsNone(metadata)

    def test_list_profile_v2_names_scans_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text("", encoding="utf-8")
            (codex_home / "work.config.toml").write_text("", encoding="utf-8")
            (codex_home / "zai.config.toml").write_text("", encoding="utf-8")
            (codex_home / "bad.name.config.toml").write_text("", encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                names = list_profile_v2_names()

        self.assertEqual(names, ["work", "zai"])

    def test_resolve_profile_rejects_matching_legacy_top_level_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text('profile = "work"\n', encoding="utf-8")
            (codex_home / "work.config.toml").write_text('model = "work-model"\n', encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                with self.assertRaisesRegex(ValueError, "legacy profile"):
                    resolve_profile_from_codex_config("work")

    def test_resolve_profile_rejects_matching_legacy_profile_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(
                """
[profiles.work]
model = "old-work-model"
""".lstrip(),
                encoding="utf-8",
            )
            (codex_home / "work.config.toml").write_text('model = "work-model"\n', encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                with self.assertRaisesRegex(ValueError, "legacy profile"):
                    resolve_profile_from_codex_config("work")

    def _resolve_from_temp_config(
        self,
        *,
        base_config: str,
        profile_name: str,
        profile_config: str,
    ) -> ResolvedProfileConfig:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(base_config.lstrip(), encoding="utf-8")
            (codex_home / f"{profile_name}.config.toml").write_text(profile_config.lstrip(), encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                return resolve_profile_from_codex_config(profile_name)
