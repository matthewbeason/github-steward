from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TriState = bool | Literal["unknown"]
Bucket = Literal[
    "KEEP",
    "IMPROVE",
    "ARCHIVE_CANDIDATE",
    "DELETE_REVIEW",
    "PORTFOLIO_CANDIDATE",
]


@dataclass(frozen=True)
class RepoRecord:
    full_name: str
    html_url: str
    description: str | None
    pushed_at: str | None
    default_branch: str | None
    archived: bool
    fork: bool
    open_issues_count: int
    open_pr_count: int | None
    primary_language: str | None
    topics: list[str]
    visibility: str | None
    size_kb: int
    has_readme: TriState
    has_license: TriState
    has_workflows: TriState
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepoAssessment:
    repo: RepoRecord
    score: int
    bucket: Bucket
    stale_days: int | None
    reasons: list[str]
    recommendation: str


@dataclass(frozen=True)
class Inventory:
    generated_at: str
    safety_mode: str
    source: str
    account_summary: dict[str, Any]
    repositories: list[RepoRecord]
