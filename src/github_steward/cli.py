from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config, load_dotenv, target_requires_token
from .github_api import GitHubAPIError, GitHubClient, collect_inventory
from .models import Inventory, RepoRecord
from .reports import write_reports
from .release_status import collect_release_status, format_release_status_table, release_status_json


def main(argv: list[str] | None = None, *, dotenv_path: str | Path | None = ".env") -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "sample":
        return sample_command(args)
    if args.command == "run":
        return run_command(args, dotenv_path=dotenv_path)
    if args.command == "release-status":
        return release_status_command(args)
    if args.command == "validate":
        return validate_command(args, dotenv_path=dotenv_path)
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-steward",
        description="Read-only GitHub repository stewardship reports.",
    )
    subparsers = parser.add_subparsers(dest="command")

    sample = subparsers.add_parser("sample", help="Generate reports from built-in sample data.")
    sample.add_argument("--config", default="steward.config.json", help="Path to steward.config.json.")

    run = subparsers.add_parser("run", help="Fetch GitHub inventory and generate dry-run reports.")
    run.add_argument("--config", default="steward.config.json", help="Path to steward.config.json.")

    release_status = subparsers.add_parser("release-status", help="Report read-only local release drift.")
    release_status.add_argument("--config", default="steward.config.json", help="Path to steward.config.json.")
    release_status.add_argument(
        "--repo",
        action="append",
        dest="repos",
        help="Local repository path to inspect. May be repeated; overrides config local_repositories.",
    )
    release_status.add_argument("--json", action="store_true", help="Write machine-readable JSON.")

    validate = subparsers.add_parser("validate", help="Validate config and optional GitHub token readiness.")
    validate.add_argument("--config", default="steward.config.json", help="Path to steward.config.json.")
    return parser


def sample_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1
    inventory = sample_inventory()
    assessments = write_reports(inventory, config)
    print(f"Wrote read-only sample reports for {len(assessments)} repositories to {config.output_dir}/")
    print("Safety mode: READ_ONLY_DRY_RUN")
    return 0


def run_command(args: argparse.Namespace, *, dotenv_path: str | Path | None = ".env") -> int:
    try:
        config = load_config(args.config)
        load_dotenv_if_enabled(dotenv_path)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    token = os.environ.get(config.token_env)
    if target_requires_token(config.targets) and not token:
        print(f"Missing GitHub token. Set {config.token_env} in .env or the environment.", file=sys.stderr)
        return 1

    try:
        inventory = collect_inventory(config, token)
        assessments = write_reports(inventory, config)
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote read-only reports for {len(assessments)} repositories to {config.output_dir}/")
    print("Safety mode: READ_ONLY_DRY_RUN")
    return 0


def release_status_command(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    repo_paths = args.repos if args.repos else config.local_repositories
    if not repo_paths:
        print("No local repositories configured. Add local_repositories to config or pass --repo.", file=sys.stderr)
        return 1

    statuses = collect_release_status(repo_paths)
    if args.json:
        print(release_status_json(statuses))
    else:
        print(format_release_status_table(statuses))
        print("Safety mode: READ_ONLY_RELEASE_STATUS")
    return 0


def validate_command(args: argparse.Namespace, *, dotenv_path: str | Path | None = ".env") -> int:
    try:
        config = load_config(args.config)
        load_dotenv_if_enabled(dotenv_path)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    print(f"Config OK: {args.config}")
    print(f"Output directory: {config.output_dir}")
    print(f"Targets: {len(config.targets)}")

    token = os.environ.get(config.token_env)
    needs_token = target_requires_token(config.targets)
    if needs_token and not token:
        print(f"Token missing: {config.token_env} is required for authenticated_user targets.", file=sys.stderr)
        return 1
    if not token:
        print(f"Token not set: {config.token_env}; GitHub account probe skipped.")
        print("Safety mode: READ_ONLY_VALIDATION")
        return 0

    try:
        account, headers = GitHubClient(token).get_with_headers("/user")
    except GitHubAPIError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1

    print(f"GitHub account: {account.get('login', 'unknown')}")
    print(f"Rate limit remaining: {headers.get('X-RateLimit-Remaining', 'unknown')}")
    print("Safety mode: READ_ONLY_VALIDATION")
    return 0


def load_dotenv_if_enabled(dotenv_path: str | Path | None) -> None:
    if dotenv_path is not None:
        load_dotenv(dotenv_path)


def sample_inventory() -> Inventory:
    now = datetime.now(UTC)

    def days_ago(days: int) -> str:
        return (now - timedelta(days=days)).isoformat().replace("+00:00", "Z")

    repos = [
        RepoRecord(
            full_name="example/portfolio-app",
            html_url="https://github.com/example/portfolio-app",
            description="Recent public project with healthy metadata.",
            pushed_at=days_ago(42),
            default_branch="main",
            archived=False,
            fork=False,
            open_issues_count=2,
            open_pr_count=0,
            primary_language="Python",
            topics=["portfolio", "cli"],
            visibility="public",
            size_kb=512,
            has_readme=True,
            has_license=True,
            has_workflows=True,
        ),
        RepoRecord(
            full_name="example/old-tool",
            html_url="https://github.com/example/old-tool",
            description="Inactive repository that may be ready for archive review.",
            pushed_at=days_ago(900),
            default_branch="master",
            archived=False,
            fork=False,
            open_issues_count=0,
            open_pr_count=0,
            primary_language="Shell",
            topics=[],
            visibility="private",
            size_kb=900,
            has_readme=True,
            has_license=False,
            has_workflows=False,
        ),
        RepoRecord(
            full_name="example/tiny-scratch",
            html_url="https://github.com/example/tiny-scratch",
            description=None,
            pushed_at=days_ago(1800),
            default_branch="main",
            archived=False,
            fork=False,
            open_issues_count=0,
            open_pr_count=0,
            primary_language=None,
            topics=[],
            visibility="private",
            size_kb=12,
            has_readme=False,
            has_license=False,
            has_workflows=False,
        ),
        RepoRecord(
            full_name="example/permission-limited",
            html_url="https://github.com/example/permission-limited",
            description="Repo with some optional metadata hidden by permissions.",
            pushed_at=days_ago(150),
            default_branch="main",
            archived=False,
            fork=False,
            open_issues_count=4,
            open_pr_count=None,
            primary_language="TypeScript",
            topics=["internal"],
            visibility="private",
            size_kb=2048,
            has_readme="unknown",
            has_license="unknown",
            has_workflows="unknown",
        ),
    ]
    return Inventory(
        generated_at=now.isoformat(),
        safety_mode="READ_ONLY_DRY_RUN",
        source="built-in sample data",
        account_summary={"login": "sample-user", "type": "User", "public_repos": 2},
        repositories=repos,
    )


if __name__ == "__main__":
    raise SystemExit(main())
