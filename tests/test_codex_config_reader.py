import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.codex_config_reader import (
    ResolvedProfileConfig,
    resolve_profile_from_codex_config,
    resolve_profile_model_metadata,
)


class CodexConfigReaderTests(unittest.TestCase):
    def test_resolve_profile_reads_explicit_profile_fields(self) -> None:
        config_text = """
model = "global-model"
model_provider = "global-provider"

[profiles.work]
model = "work-model"
model_provider = "work-provider"
"""

        resolved = self._resolve_from_temp_config(config_text, "work")

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="work-model", model_provider="work-provider"),
        )

    def test_resolve_profile_inherits_top_level_model_and_provider(self) -> None:
        config_text = """
model = "global-model"
model_provider = "global-provider"

[profiles.work]
"""

        resolved = self._resolve_from_temp_config(config_text, "work")

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="global-model", model_provider="global-provider"),
        )

    def test_resolve_profile_can_mix_profile_and_top_level_fields(self) -> None:
        config_text = """
model_provider = "global-provider"

[profiles.work]
model = "work-model"
"""

        resolved = self._resolve_from_temp_config(config_text, "work")

        self.assertEqual(
            resolved,
            ResolvedProfileConfig(model="work-model", model_provider="global-provider"),
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
            (codex_home / "config.toml").write_text(
                (
                    f"""
[profiles.zai]
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
        config_text = """
[profiles.work]
model = "work-model"
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(config_text.lstrip(), encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                metadata = resolve_profile_model_metadata("work")

        self.assertIsNone(metadata)

    def _resolve_from_temp_config(self, config_text: str, profile_name: str) -> ResolvedProfileConfig:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(config_text.lstrip(), encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                return resolve_profile_from_codex_config(profile_name)
