from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_steward.cli import main
from github_steward.release_status import inspect_repository


class ReleaseStatusTests(unittest.TestCase):
    def test_clean_released_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = init_repo(root / "released")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            add_origin(repo, root / "remote.git")

            status = inspect_repository(repo)

        self.assertEqual(status.latest_local_tag, "v1.0.0")
        self.assertEqual(status.commits_since_latest_tag, 0)
        self.assertEqual(status.classifications, ["released"])

    def test_repo_ahead_of_latest_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "ahead-tag")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            write_file(repo / "feature.txt", "new work\n")
            git(repo, "add", "feature.txt")
            git(repo, "commit", "-m", "feature")

            status = inspect_repository(repo)

        self.assertEqual(status.commits_since_latest_tag, 1)
        self.assertIn("unreleased commits", status.classifications)

    def test_repo_ahead_of_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = init_repo(root / "ahead-origin")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            remote = root / "remote.git"
            git(root, "init", "--bare", str(remote))
            git(repo, "remote", "add", "origin", str(remote))
            git(repo, "push", "-u", "origin", "main", "--tags")
            write_file(repo / "feature.txt", "new work\n")
            git(repo, "add", "feature.txt")
            git(repo, "commit", "-m", "feature")

            status = inspect_repository(repo)

        self.assertEqual(status.ahead_origin, 1)
        self.assertEqual(status.behind_origin, 0)
        self.assertEqual(status.latest_remote_tag, "v1.0.0")
        self.assertIn("ahead of remote", status.classifications)

    def test_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "dirty")
            tracked = repo / "README.md"
            write_file(tracked, "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            write_file(tracked, "Current release: v1.0.0\nchanged\n")

            status = inspect_repository(repo)

        self.assertEqual(status.dirty_tracked_files, 1)
        self.assertIn("dirty worktree", status.classifications)

    def test_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "untracked")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            write_file(repo / "notes.txt", "untracked\n")

            status = inspect_repository(repo)

        self.assertEqual(status.untracked_files, 1)
        self.assertIn("dirty worktree", status.classifications)

    def test_no_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "no-tags")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")

            status = inspect_repository(repo)

        self.assertIsNone(status.latest_local_tag)
        self.assertIn("untagged", status.classifications)

    def test_no_origin_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "no-origin")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")

            status = inspect_repository(repo)

        self.assertIsNone(status.origin)
        self.assertIn("no origin configured", status.classifications)

    def test_version_surface_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "version-mismatch")
            write_file(repo / "README.md", "Current release: v0.7.2\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v0.7.1")

            status = inspect_repository(repo)

        self.assertEqual(status.version_surfaces[0].version, "v0.7.2")
        self.assertIn("version mismatch", status.classifications)

    def test_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = init_repo(root / "json-repo")
            write_file(repo / "README.md", "Current release: v1.0.0\n")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            git(repo, "tag", "v1.0.0")
            add_origin(repo, root / "remote.git")
            config = root / "steward.config.json"
            config.write_text(
                json.dumps({"targets": [{"kind": "user", "username": "octocat"}], "local_repositories": [str(repo)]}),
                encoding="utf-8",
            )

            result, stdout, stderr = run_cli(["release-status", "--config", str(config), "--json"])

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload[0]["repo"], "json-repo")
        self.assertEqual(payload[0]["classifications"], ["released"])


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "tests@example.invalid")
    git(path, "config", "user.name", "Release Status Tests")
    return path


def add_origin(repo: Path, remote: Path) -> None:
    git(remote.parent, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main", "--tags")


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = main(argv, dotenv_path=None)
    return result, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
