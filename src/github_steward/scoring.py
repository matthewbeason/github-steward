from __future__ import annotations

from datetime import UTC, datetime

from .models import Bucket, RepoAssessment, RepoRecord


def assess_repo(repo: RepoRecord, thresholds: dict[str, int], now: datetime | None = None) -> RepoAssessment:
    now = now or datetime.now(UTC)
    score = 100
    reasons: list[str] = []
    stale_days = days_since(repo.pushed_at, now)

    def deduct(points: int, reason: str) -> None:
        nonlocal score
        score -= points
        reasons.append(reason)

    if stale_days is None:
        deduct(20, "Missing last-push timestamp")
    elif stale_days >= thresholds["delete_review_after_days"]:
        deduct(40, f"Last push is {stale_days} days old")
    elif stale_days >= thresholds["archive_after_days"]:
        deduct(25, f"Last push is {stale_days} days old")
    elif stale_days >= thresholds["portfolio_recent_days"]:
        deduct(8, f"Last push is {stale_days} days old")

    if repo.has_readme is False:
        deduct(15, "Missing README")
    elif repo.has_readme == "unknown":
        deduct(5, "README status unknown")

    if repo.has_license is False:
        deduct(10, "Missing license")
    elif repo.has_license == "unknown":
        deduct(3, "License status unknown")

    if not repo.default_branch:
        deduct(5, "Missing default branch")
    elif repo.default_branch not in {"main", "master"}:
        deduct(2, f"Non-standard default branch: {repo.default_branch}")

    if repo.archived:
        deduct(10, "Repository is already archived")
    if repo.fork:
        deduct(5, "Repository is a fork")
    if repo.open_issues_count >= 25:
        deduct(8, f"High open issue count: {repo.open_issues_count}")
    if repo.open_pr_count is not None and repo.open_pr_count > 0:
        deduct(min(repo.open_pr_count * 2, 10), f"Open pull requests: {repo.open_pr_count}")
    if repo.primary_language is None:
        deduct(5, "Primary language unknown")
    if not repo.topics:
        deduct(5, "No repository topics")
    if repo.has_workflows is False:
        deduct(7, "Missing Actions workflows")
    elif repo.has_workflows == "unknown":
        deduct(2, "Actions workflow status unknown")

    score = max(0, min(100, score))
    bucket = classify_repo(repo, score, stale_days, thresholds)
    recommendation = recommendation_for(bucket)
    return RepoAssessment(repo, score, bucket, stale_days, reasons, recommendation)


def classify_repo(
    repo: RepoRecord,
    score: int,
    stale_days: int | None,
    thresholds: dict[str, int],
) -> Bucket:
    no_open_work = repo.open_issues_count == 0 and repo.open_pr_count == 0
    if (
        stale_days is not None
        and stale_days >= thresholds["delete_review_after_days"]
        and repo.has_readme is False
        and repo.has_license is False
        and repo.size_kb <= thresholds["small_repo_kb"]
        and no_open_work
    ):
        return "DELETE_REVIEW"

    if (
        stale_days is not None
        and stale_days >= thresholds["archive_after_days"]
        and no_open_work
        and not repo.archived
    ):
        return "ARCHIVE_CANDIDATE"

    if (
        repo.visibility == "public"
        and not repo.fork
        and not repo.archived
        and repo.has_readme is True
        and repo.has_license is True
        and stale_days is not None
        and stale_days <= thresholds["portfolio_recent_days"]
        and score >= 85
    ):
        return "PORTFOLIO_CANDIDATE"

    if score < 80:
        return "IMPROVE"
    return "KEEP"


def recommendation_for(bucket: Bucket) -> str:
    return {
        "KEEP": "Keep as-is; no cleanup action recommended.",
        "IMPROVE": "Review documentation, metadata, and maintenance signals.",
        "ARCHIVE_CANDIDATE": "Dry run: review for possible archive; no GitHub changes were made.",
        "DELETE_REVIEW": "Dry run: manual review queue for possible deletion; no GitHub changes were made.",
        "PORTFOLIO_CANDIDATE": "Consider featuring as a portfolio repository.",
    }[bucket]


def days_since(timestamp: str | None, now: datetime | None = None) -> int | None:
    if timestamp is None:
        return None
    now = now or datetime.now(UTC)
    value = timestamp.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0, (now - parsed).days)
