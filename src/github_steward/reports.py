from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Bucket, Inventory, RepoAssessment, RepoRecord
from .scoring import assess_repo

SAFETY_STATUS = "READ_ONLY_RECOMMENDATION"


def write_reports(inventory: Inventory, config: Any) -> list[RepoAssessment]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    assessments = [assess_repo(repo, config.classification) for repo in inventory.repositories]
    assessments.sort(key=lambda assessment: assessment.repo.full_name.lower())

    inventory_path = output_dir / "repo-inventory.json"
    inventory_path.write_text(json.dumps(_inventory_payload(inventory), indent=2) + "\n", encoding="utf-8")

    (output_dir / "repo-health.md").write_text(render_health(inventory, assessments), encoding="utf-8")
    (output_dir / "archive-candidates.md").write_text(render_bucket("ARCHIVE_CANDIDATE", assessments), encoding="utf-8")
    (output_dir / "delete-candidates.md").write_text(render_bucket("DELETE_REVIEW", assessments), encoding="utf-8")
    (output_dir / "portfolio-candidates.md").write_text(render_bucket("PORTFOLIO_CANDIDATE", assessments), encoding="utf-8")

    ledger = build_decision_ledger(assessments, inventory.generated_at, config.classification)
    (output_dir / "decision-ledger.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    (output_dir / "decision-ledger.md").write_text(render_decision_ledger_md(ledger), encoding="utf-8")
    return assessments


def render_health(inventory: Inventory, assessments: list[RepoAssessment]) -> str:
    counts = {bucket: 0 for bucket in _bucket_order()}
    for assessment in assessments:
        counts[assessment.bucket] += 1

    lines = [
        "# Repository Health",
        "",
        f"Generated: {inventory.generated_at}",
        f"Source: {inventory.source}",
        f"Safety mode: {inventory.safety_mode}",
        "",
        "## Account Summary",
        "",
    ]
    if inventory.account_summary:
        for key, value in inventory.account_summary.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- unavailable")
    lines.extend(["", "## Classification Counts", ""])
    for bucket in _bucket_order():
        lines.append(f"- {bucket}: {counts[bucket]}")
    lines.extend(
        [
            "",
            "## Repositories",
            "",
            "| Repository | Score | Bucket | Last Push Age | Reasons | Recommendation |",
            "| --- | ---: | --- | ---: | --- | --- |",
        ]
    )
    for assessment in assessments:
        age = "unknown" if assessment.stale_days is None else str(assessment.stale_days)
        reasons = "; ".join(assessment.reasons) or "No deductions"
        lines.append(
            f"| [{assessment.repo.full_name}]({assessment.repo.html_url}) "
            f"| {assessment.score} | {assessment.bucket} | {age} | {reasons} | {assessment.recommendation} |"
        )
    return "\n".join(lines) + "\n"


def render_bucket(bucket: Bucket, assessments: list[RepoAssessment]) -> str:
    title = bucket.replace("_", " ").title()
    lines = [
        f"# {title}",
        "",
        "This is a dry-run review queue. No GitHub changes were made.",
        "",
    ]
    matches = [assessment for assessment in assessments if assessment.bucket == bucket]
    if not matches:
        lines.append("No repositories matched this bucket.")
        return "\n".join(lines) + "\n"

    for assessment in matches:
        repo = assessment.repo
        age = "unknown" if assessment.stale_days is None else f"{assessment.stale_days} days"
        lines.extend(
            [
                f"## {repo.full_name}",
                "",
                f"- URL: {repo.html_url}",
                f"- Score: {assessment.score}",
                f"- Last push age: {age}",
                f"- Visibility: {repo.visibility or 'unknown'}",
                f"- Size: {repo.size_kb} KB",
                f"- Recommendation: {assessment.recommendation}",
                f"- Reasoning: {'; '.join(assessment.reasons) or 'No deductions'}",
                "",
            ]
        )
    return "\n".join(lines)


def build_decision_ledger(
    assessments: list[RepoAssessment],
    generated_at: str,
    thresholds: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    thresholds = thresholds or {
        "archive_after_days": 730,
        "delete_review_after_days": 1460,
        "portfolio_recent_days": 365,
        "small_repo_kb": 256,
    }
    return [
        ledger_entry(assessment, generated_at, thresholds)
        for assessment in sorted(assessments, key=lambda item: item.repo.full_name.lower())
    ]


def ledger_entry(assessment: RepoAssessment, generated_at: str, thresholds: dict[str, int]) -> dict[str, Any]:
    return {
        "repo_name": assessment.repo.full_name,
        "classification": assessment.bucket,
        "score": assessment.score,
        "recommendation": assessment.recommendation,
        "reasons": assessment.reasons,
        "evidence_fields_used": evidence_fields(assessment.repo),
        "confidence": confidence_for(assessment, thresholds),
        "safety_status": SAFETY_STATUS,
        "generated_at": generated_at,
    }


def evidence_fields(repo: RepoRecord) -> dict[str, Any]:
    return {
        "pushed_at": repo.pushed_at,
        "default_branch": repo.default_branch,
        "archived": repo.archived,
        "fork": repo.fork,
        "open_issues_count": repo.open_issues_count,
        "open_pr_count": repo.open_pr_count,
        "primary_language": repo.primary_language,
        "topics": repo.topics,
        "visibility": repo.visibility,
        "size_kb": repo.size_kb,
        "has_readme": repo.has_readme,
        "has_license": repo.has_license,
        "has_workflows": repo.has_workflows,
    }


def confidence_for(assessment: RepoAssessment, thresholds: dict[str, int]) -> str:
    repo = assessment.repo
    if (
        assessment.stale_days is None
        or repo.has_readme == "unknown"
        or repo.has_license == "unknown"
        or repo.has_workflows == "unknown"
        or repo.open_pr_count is None
        or not repo.default_branch
        or not repo.visibility
    ):
        return "LOW"
    if _strong_signal_count(assessment, thresholds) >= 3:
        return "HIGH"
    return "MEDIUM"


def render_decision_ledger_md(ledger: list[dict[str, Any]]) -> str:
    lines = [
        "# Decision Ledger",
        "",
        "Every entry is advisory and read-only. No GitHub changes were made.",
        "",
        "| Repository | Classification | Score | Confidence | Safety | Recommendation |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for entry in ledger:
        lines.append(
            f"| {entry['repo_name']} | {entry['classification']} | {entry['score']} | "
            f"{entry['confidence']} | {entry['safety_status']} | {entry['recommendation']} |"
        )
    return "\n".join(lines) + "\n"


def _inventory_payload(inventory: Inventory) -> dict[str, Any]:
    payload = asdict(inventory)
    payload["repositories"] = [repo.to_dict() for repo in inventory.repositories]
    return payload


def _strong_signal_count(assessment: RepoAssessment, thresholds: dict[str, int]) -> int:
    repo = assessment.repo
    signals = 0
    if assessment.stale_days is not None:
        if assessment.bucket == "DELETE_REVIEW" and assessment.stale_days >= thresholds["delete_review_after_days"]:
            signals += 1
        elif assessment.bucket == "ARCHIVE_CANDIDATE" and assessment.stale_days >= thresholds["archive_after_days"]:
            signals += 1
        elif assessment.bucket == "PORTFOLIO_CANDIDATE" and assessment.stale_days <= thresholds["portfolio_recent_days"]:
            signals += 1
    if repo.has_readme is True and repo.has_license is True:
        signals += 1
    if repo.has_readme is False and repo.has_license is False:
        signals += 1
    if repo.open_issues_count == 0 and repo.open_pr_count == 0:
        signals += 1
    if repo.visibility == "public" and not repo.fork and not repo.archived:
        signals += 1
    if repo.size_kb <= thresholds["small_repo_kb"]:
        signals += 1
    return signals


def _bucket_order() -> list[Bucket]:
    return ["KEEP", "IMPROVE", "ARCHIVE_CANDIDATE", "DELETE_REVIEW", "PORTFOLIO_CANDIDATE"]
