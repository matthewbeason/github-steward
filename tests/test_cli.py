from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from github_steward.cli import main


class CliTests(unittest.TestCase):
    def test_validate_succeeds_without_token_for_public_user_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": [{"kind": "user", "username": "octocat"}]}), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = quiet_main(["validate", "--config", str(path)])

        self.assertEqual(result, 0)

    def test_validate_requires_token_for_authenticated_user_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": [{"kind": "authenticated_user"}]}), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = quiet_main(["validate", "--config", str(path)])

        self.assertEqual(result, 1)

    @patch("github_steward.cli.GitHubClient")
    def test_validate_probes_account_when_token_exists(self, client_class: object) -> None:
        client_class.return_value.get_with_headers.return_value = (  # type: ignore[attr-defined]
            {"login": "octocat"},
            {"X-RateLimit-Remaining": "4999"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steward.config.json"
            path.write_text(json.dumps({"targets": [{"kind": "authenticated_user"}]}), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}, clear=True):
                result = quiet_main(["validate", "--config", str(path)])

        self.assertEqual(result, 0)
        client_class.return_value.get_with_headers.assert_called_once_with("/user")  # type: ignore[attr-defined]


def quiet_main(argv: list[str]) -> int:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return main(argv)


if __name__ == "__main__":
    unittest.main()
