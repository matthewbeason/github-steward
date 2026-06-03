from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from github_steward.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_valid_minimal_config_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": [{"kind": "user", "username": "octocat"}]}), encoding="utf-8")

            config = load_config(path)

        self.assertEqual(config.version, 1)
        self.assertEqual(config.token_env, "GITHUB_TOKEN")
        self.assertEqual(config.output_dir, "reports")
        self.assertTrue(config.checks["readme"])

    def test_missing_targets_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": []}), encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(path)

    def test_secrets_in_config_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(
                json.dumps({"targets": [{"kind": "user", "username": "octocat"}], "github_token": "ghp_bad"}),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(path)

    def test_invalid_target_shape_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": [{"kind": "org"}]}), encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(path)

    def test_invalid_classification_order_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(
                json.dumps(
                    {
                        "targets": [{"kind": "user", "username": "octocat"}],
                        "classification": {"archive_after_days": 1000, "delete_review_after_days": 100},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
