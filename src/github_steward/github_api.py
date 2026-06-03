from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Inventory, RepoRecord, TriState

API_ROOT = "https://api.github.com"


class GitHubAPIError(Exception):
    """Friendly wrapper for GitHub API failures."""


class GitHubClient:
    def __init__(self, token: str | None = None, api_root: str = API_ROOT) -> None:
        self.token = token
        self.api_root = api_root.rstrip("/")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        data, _headers = self.get_with_headers(path, params)
        return data

    def get_with_headers(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
        url = self._url(path, params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-steward-read-only",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None, dict(response.headers.items())
        except HTTPError as exc:
            raise GitHubAPIError(friendly_http_error(exc)) from exc
        except URLError as exc:
            raise GitHubAPIError(f"Could not reach GitHub API: {exc.reason}") from exc

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1
        results: list[Any] = []
        while True:
            params["page"] = page
            data, headers = self.get_with_headers(path, params)
            if not isinstance(data, list):
                raise GitHubAPIError(f"Expected a list response from {path}.")
            results.extend(data)
            if 'rel="next"' not in headers.get("Link", ""):
                return results
            page += 1

    def _url(self, path: str, params: dict[str, Any] | None) -> str:
        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.api_root}{clean_path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return url


def collect_inventory(config: Any, token: str | None) -> Inventory:
    client = GitHubClient(token)
    repos: list[RepoRecord] = []
    account_summary: dict[str, Any] = {}
    source_parts: list[str] = []

    for target in config.targets:
        kind = target["kind"]
        if kind == "authenticated_user":
            account_summary = get_account_summary(client)
            source_parts.append(f"authenticated_user:{account_summary.get('login', 'unknown')}")
            repo_items = client.paginate(
                "/user/repos",
                {
                    "visibility": target.get("visibility", "all"),
                    "affiliation": target.get("affiliation", "owner,collaborator,organization_member"),
                    "sort": "full_name",
                },
            )
        elif kind == "user":
            username = target["username"]
            source_parts.append(f"user:{username}")
            repo_items = client.paginate(f"/users/{username}/repos", {"sort": "full_name"})
        else:
            org = target["org"]
            source_parts.append(f"org:{org}")
            repo_items = client.paginate(f"/orgs/{org}/repos", {"type": target.get("type", "all"), "sort": "full_name"})

        for item in repo_items:
            repos.append(normalize_repo(client, item, config.checks))

    return Inventory(
        generated_at=datetime.now(UTC).isoformat(),
        safety_mode="READ_ONLY_DRY_RUN",
        source=", ".join(source_parts),
        account_summary=account_summary,
        repositories=sorted(repos, key=lambda repo: repo.full_name.lower()),
    )


def get_account_summary(client: GitHubClient) -> dict[str, Any]:
    data = client.get("/user")
    return {
        "login": data.get("login"),
        "name": data.get("name"),
        "type": data.get("type"),
        "public_repos": data.get("public_repos"),
        "private_gists": data.get("private_gists"),
        "owned_private_repos": data.get("owned_private_repos"),
        "plan": (data.get("plan") or {}).get("name"),
    }


def normalize_repo(client: GitHubClient, item: dict[str, Any], checks: dict[str, bool]) -> RepoRecord:
    full_name = item["full_name"]
    open_pr_count: int | None = None
    has_readme: TriState = "unknown"
    has_workflows: TriState = "unknown"

    if checks.get("pull_requests", True):
        open_pr_count = _open_pr_count(client, full_name)
    if checks.get("readme", True):
        has_readme = _exists(client, f"/repos/{full_name}/readme")
    if checks.get("workflows", True):
        has_workflows = _has_workflows(client, full_name)

    license_value = item.get("license")
    return RepoRecord(
        full_name=full_name,
        html_url=item.get("html_url", ""),
        description=item.get("description"),
        pushed_at=item.get("pushed_at"),
        default_branch=item.get("default_branch"),
        archived=bool(item.get("archived", False)),
        fork=bool(item.get("fork", False)),
        open_issues_count=int(item.get("open_issues_count") or 0),
        open_pr_count=open_pr_count,
        primary_language=item.get("language"),
        topics=list(item.get("topics") or []),
        visibility=item.get("visibility"),
        size_kb=int(item.get("size") or 0),
        has_readme=has_readme,
        has_license=bool(license_value) if license_value is not None else False,
        has_workflows=has_workflows,
        extra={
            "id": item.get("id"),
            "owner": (item.get("owner") or {}).get("login"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        },
    )


def friendly_http_error(exc: HTTPError) -> str:
    if exc.code in {401, 403}:
        remaining = exc.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "unknown")
            return f"GitHub API rate limit reached. Reset epoch: {reset}."
        return "GitHub authentication or permission check failed. Verify the token has read-only permissions."
    if exc.code == 404:
        return "GitHub resource was not found or the token cannot read it."
    return f"GitHub API request failed with HTTP {exc.code}."


def _exists(client: GitHubClient, path: str) -> TriState:
    try:
        client.get(path)
        return True
    except GitHubAPIError as exc:
        message = str(exc)
        if "not found" in message.lower():
            return False
        return "unknown"


def _has_workflows(client: GitHubClient, full_name: str) -> TriState:
    try:
        data = client.get(f"/repos/{full_name}/actions/workflows")
    except GitHubAPIError as exc:
        message = str(exc)
        if "not found" in message.lower():
            return False
        return "unknown"
    workflows = data.get("workflows") if isinstance(data, dict) else None
    if workflows is None:
        return "unknown"
    return bool(workflows)


def _open_pr_count(client: GitHubClient, full_name: str) -> int | None:
    try:
        data = client.get(f"/repos/{full_name}/pulls", {"state": "open", "per_page": 100})
    except GitHubAPIError:
        return None
    if isinstance(data, list):
        return len(data)
    return None
