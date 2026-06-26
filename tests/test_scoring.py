from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_steward.models import RepoRecord
from github_steward.scoring import assess_repo


THRESHOLDS = {
    "archive_after_days": 730,
    "delete_review_after_days": 1460,
    "portfolio_recent_days": 365,
    "small_repo_kb": 256,
}


class ScoringTests(unittest.TestCase):
    def test_healthy_recent_public_repo_becomes_portfolio_candidate(self) -> None:
        assessment = assess_repo(repo(days_old=30), THRESHOLDS, now())

        self.assertEqual(assessment.bucket, "PORTFOLIO_CANDIDATE")
        self.assertGreaterEqual(assessment.score, 85)

    def test_stale_inactive_repo_becomes_archive_candidate(self) -> None:
        assessment = assess_repo(repo(days_old=900, has_license=False, topics=[]), THRESHOLDS, now())

        self.assertEqual(assessment.bucket, "ARCHIVE_CANDIDATE")

    def test_very_old_small_undocumented_repo_becomes_delete_review(self) -> None:
        assessment = assess_repo(
            repo(days_old=1800, has_readme=False, has_license=False, size_kb=12, language=None, topics=[]),
            THRESHOLDS,
            now(),
        )

        self.assertEqual(assessment.bucket, "DELETE_REVIEW")

    def test_unknown_permission_signals_do_not_force_delete_review(self) -> None:
        assessment = assess_repo(
            repo(days_old=1800, has_readme="unknown", has_license="unknown", has_workflows="unknown", open_pr_count=None),
            THRESHOLDS,
            now(),
        )

        self.assertNotEqual(assessment.bucket, "DELETE_REVIEW")


def now() -> datetime:
    return datetime(2026, 6, 3, tzinfo=UTC)


def repo(
    *,
    days_old: int,
    has_readme: bool | str = True,
    has_license: bool | str = True,
    has_workflows: bool | str = True,
    open_pr_count: int | None = 0,
    size_kb: int = 512,
    language: str | None = "Python",
    topics: list[str] | None = None,
) -> RepoRecord:
    pushed_at = (now() - timedelta(days=days_old)).isoformat().replace("+00:00", "Z")
    return RepoRecord(
        full_name="example/repo",
        html_url="https://github.com/example/repo",
        description=None,
        pushed_at=pushed_at,
        default_branch="main",
        archived=False,
        fork=False,
        open_issues_count=0,
        open_pr_count=open_pr_count,
        primary_language=language,
        topics=["sample"] if topics is None else topics,
        visibility="public",
        size_kb=size_kb,
        has_readme=has_readme,  # type: ignore[arg-type]
        has_license=has_license,  # type: ignore[arg-type]
        has_workflows=has_workflows,  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    unittest.main()
