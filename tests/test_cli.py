from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Iterator
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

    def test_validate_ignores_cwd_dotenv_when_dotenv_loading_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "steward.config.json").write_text(
                json.dumps({"targets": [{"kind": "authenticated_user"}]}),
                encoding="utf-8",
            )
            (tmp_path / ".env").write_text("GITHUB_TOKEN=local-machine-secret\n", encoding="utf-8")
            with chdir(tmp_path), patch.dict(os.environ, {}, clear=True):
                result = quiet_main(["validate", "--config", "steward.config.json"])

        self.assertEqual(result, 1)

    @patch("github_steward.cli.GitHubClient")
    def test_validate_loads_explicit_dotenv_without_printing_token(self, client_class: object) -> None:
        token = "DO_NOT_PRINT_TEST_TOKEN"
        client_class.return_value.get_with_headers.return_value = (  # type: ignore[attr-defined]
            {"login": "octocat"},
            {"X-RateLimit-Remaining": "4999"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "steward.config.json"
            env_path = tmp_path / ".env"
            config_path.write_text(json.dumps({"targets": [{"kind": "authenticated_user"}]}), encoding="utf-8")
            env_path.write_text(f"GITHUB_TOKEN={token}\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result, stdout, stderr = quiet_main_with_output(
                    ["validate", "--config", str(config_path)],
                    dotenv_path=env_path,
                )

        self.assertEqual(result, 0)
        self.assertNotIn(token, stdout)
        self.assertNotIn(token, stderr)
        client_class.return_value.get_with_headers.assert_called_once_with("/user")  # type: ignore[attr-defined]


def quiet_main(argv: list[str]) -> int:
    result, _stdout, _stderr = quiet_main_with_output(argv, dotenv_path=None)
    return result


def quiet_main_with_output(argv: list[str], *, dotenv_path: str | Path | None) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = main(argv, dotenv_path=dotenv_path)
    return result, stdout.getvalue(), stderr.getvalue()


@contextmanager
def chdir(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
