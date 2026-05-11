import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.codex_config_reader import ResolvedProfileConfig, resolve_profile_from_codex_config


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

    def _resolve_from_temp_config(self, config_text: str, profile_name: str) -> ResolvedProfileConfig:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            (codex_home / "config.toml").write_text(config_text.lstrip(), encoding="utf-8")
            with patch.dict("os.environ", {"CODEX_HOME": tmpdir}):
                return resolve_profile_from_codex_config(profile_name)
