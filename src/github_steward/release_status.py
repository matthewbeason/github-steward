from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


READ_ONLY_TIMEOUT_SECONDS = 15
VERSION_RE = re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")
VERSION_SURFACE_FILES = (
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "VERSION",
    "version.txt",
    "src/*/__init__.py",
    "docs/*.md",
    "viz/index.html",
    "viz/*.html",
)


@dataclass(frozen=True)
class VersionSurface:
    file: str
    version: str
    line: int
    text: str


@dataclass(frozen=True)
class ReleaseStatus:
    repo: str
    path: str
    branch: str
    head: str
    latest_local_tag: str | None
    latest_remote_tag: str | None
    commits_since_latest_tag: int | None
    ahead_origin: int | None
    behind_origin: int | None
    worktree_clean: bool
    dirty_tracked_files: int
    untracked_files: int
    origin: str | None
    upstream: str | None
    version_surfaces: list[VersionSurface]
    classifications: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class GitProbe:
    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.path,
            text=True,
            capture_output=True,
            timeout=READ_ONLY_TIMEOUT_SECONDS,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
        return result

    def output(self, args: list[str]) -> str | None:
        result = self.run(args)
        if result.returncode != 0:
            return None
        return result.stdout.strip()


def collect_release_status(paths: list[str | Path]) -> list[ReleaseStatus]:
    return [inspect_repository(Path(path).expanduser()) for path in paths]


def inspect_repository(path: Path) -> ReleaseStatus:
    resolved = path.resolve()
    errors: list[str] = []
    probe = GitProbe(resolved)

    if not resolved.exists():
        return _error_status(resolved, "missing path")
    if probe.run(["rev-parse", "--is-inside-work-tree"]).stdout.strip() != "true":
        return _error_status(resolved, "not a git repository")

    repo_name = resolved.name
    branch = probe.output(["branch", "--show-current"]) or "DETACHED"
    head = probe.output(["rev-parse", "--short", "HEAD"]) or "unknown"
    origin = probe.output(["remote", "get-url", "origin"])
    latest_local_tag = _latest_local_tag(probe)
    latest_remote_tag = _latest_remote_tag(probe) if origin else None
    commits_since_latest_tag = _commits_since_tag(probe, latest_local_tag)
    upstream = _upstream_ref(probe, branch)
    ahead_origin, behind_origin = _ahead_behind(probe, upstream)
    dirty_tracked_files, untracked_files = _status_counts(probe)
    version_surfaces = detect_version_surfaces(resolved)
    classifications = classify_release_status(
        origin=origin,
        latest_local_tag=latest_local_tag,
        commits_since_latest_tag=commits_since_latest_tag,
        ahead_origin=ahead_origin,
        dirty_tracked_files=dirty_tracked_files,
        untracked_files=untracked_files,
        version_surfaces=version_surfaces,
        latest_remote_tag=latest_remote_tag,
    )
    if upstream is None and origin is not None:
        errors.append("origin branch not found in local refs")

    return ReleaseStatus(
        repo=repo_name,
        path=str(resolved),
        branch=branch,
        head=head,
        latest_local_tag=latest_local_tag,
        latest_remote_tag=latest_remote_tag,
        commits_since_latest_tag=commits_since_latest_tag,
        ahead_origin=ahead_origin,
        behind_origin=behind_origin,
        worktree_clean=dirty_tracked_files == 0 and untracked_files == 0,
        dirty_tracked_files=dirty_tracked_files,
        untracked_files=untracked_files,
        origin=origin,
        upstream=upstream,
        version_surfaces=version_surfaces,
        classifications=classifications,
        errors=errors,
    )


def format_release_status_table(statuses: list[ReleaseStatus]) -> str:
    headers = [
        "Repo",
        "Branch",
        "HEAD",
        "Local tag",
        "Remote tag",
        "Since tag",
        "Ahead/behind",
        "WT",
        "Untracked",
        "Status",
    ]
    rows = []
    for status in statuses:
        ahead_behind = "n/a"
        if status.ahead_origin is not None and status.behind_origin is not None:
            ahead_behind = f"{status.ahead_origin}/{status.behind_origin}"
        rows.append(
            [
                status.repo,
                status.branch,
                status.head,
                status.latest_local_tag or "-",
                status.latest_remote_tag or "-",
                "-" if status.commits_since_latest_tag is None else str(status.commits_since_latest_tag),
                ahead_behind,
                "clean" if status.worktree_clean else f"tracked:{status.dirty_tracked_files}",
                str(status.untracked_files),
                ", ".join(status.classifications),
            ]
        )
    return _format_table(headers, rows)


def release_status_json(statuses: list[ReleaseStatus]) -> str:
    return json.dumps([status.to_dict() for status in statuses], indent=2, sort_keys=True)


def detect_version_surfaces(path: Path) -> list[VersionSurface]:
    surfaces: list[VersionSurface] = []
    seen: set[Path] = set()
    for pattern in VERSION_SURFACE_FILES:
        for candidate in sorted(path.glob(pattern)):
            if candidate in seen or not candidate.is_file() or candidate.stat().st_size > 500_000:
                continue
            seen.add(candidate)
            try:
                lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if not _line_looks_version_related(line):
                    continue
                for match in VERSION_RE.finditer(line):
                    surfaces.append(
                        VersionSurface(
                            file=str(candidate.relative_to(path)),
                            version=f"v{match.group(1)}",
                            line=line_number,
                            text=line.strip()[:160],
                        )
                    )
    return surfaces


def classify_release_status(
    *,
    origin: str | None,
    latest_local_tag: str | None,
    commits_since_latest_tag: int | None,
    ahead_origin: int | None,
    dirty_tracked_files: int,
    untracked_files: int,
    version_surfaces: list[VersionSurface],
    latest_remote_tag: str | None,
) -> list[str]:
    classifications: list[str] = []
    if origin is None:
        classifications.append("no origin configured")
    if latest_local_tag is None:
        classifications.append("untagged")
    elif commits_since_latest_tag and commits_since_latest_tag > 0:
        classifications.append("unreleased commits")
    if ahead_origin and ahead_origin > 0:
        classifications.append("ahead of remote")
    if dirty_tracked_files > 0 or untracked_files > 0:
        classifications.append("dirty worktree")
    if _has_version_mismatch(version_surfaces, latest_remote_tag or latest_local_tag):
        classifications.append("version mismatch")
    if not classifications:
        classifications.append("released")
    return classifications


def _latest_local_tag(probe: GitProbe) -> str | None:
    described = probe.output(["describe", "--tags", "--abbrev=0"])
    if described:
        return described
    tags = probe.output(["tag", "--sort=-v:refname", "--list"])
    if not tags:
        return None
    return tags.splitlines()[0]


def _latest_remote_tag(probe: GitProbe) -> str | None:
    result = probe.run(["ls-remote", "--tags", "--refs", "origin"])
    if result.returncode != 0:
        return None
    tags = [line.rsplit("/", 1)[-1] for line in result.stdout.splitlines() if line.strip()]
    if not tags:
        return None
    return sorted(tags, key=_tag_sort_key)[-1]


def _commits_since_tag(probe: GitProbe, tag: str | None) -> int | None:
    if tag is None:
        count = probe.output(["rev-list", "--count", "HEAD"])
    else:
        count = probe.output(["rev-list", "--count", f"{tag}..HEAD"])
    if count is None:
        return None
    return int(count)


def _upstream_ref(probe: GitProbe, branch: str) -> str | None:
    upstream = probe.output(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if upstream:
        return upstream
    if branch != "DETACHED":
        candidate = f"origin/{branch}"
        if probe.run(["rev-parse", "--verify", "--quiet", candidate]).returncode == 0:
            return candidate
    return None


def _ahead_behind(probe: GitProbe, upstream: str | None) -> tuple[int | None, int | None]:
    if upstream is None:
        return None, None
    output = probe.output(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"])
    if output is None:
        return None, None
    left, right = output.split()
    return int(left), int(right)


def _status_counts(probe: GitProbe) -> tuple[int, int]:
    output = probe.output(["status", "--short", "--untracked-files=all"]) or ""
    dirty_tracked = 0
    untracked = 0
    for line in output.splitlines():
        if line.startswith("??"):
            untracked += 1
        else:
            dirty_tracked += 1
    return dirty_tracked, untracked


def _has_version_mismatch(surfaces: list[VersionSurface], release_tag: str | None) -> bool:
    if not release_tag:
        return False
    release_version = _normalize_version(release_tag)
    if release_version is None:
        return False
    return any(_normalize_version(surface.version) != release_version for surface in surfaces)


def _normalize_version(value: str) -> str | None:
    match = VERSION_RE.search(value)
    if not match:
        return None
    return match.group(1)


def _line_looks_version_related(line: str) -> bool:
    lowered = line.lower()
    return any(
        word in lowered
        for word in ("current release", "production release", "version", "__version__", "buildtag", "build tag")
    )


def _tag_sort_key(tag: str) -> tuple[tuple[int, ...], str]:
    normalized = _normalize_version(tag)
    if normalized is None:
        return ((), tag)
    numeric = tuple(int(part) for part in normalized.split("-", 1)[0].split("+", 1)[0].split(".") if part.isdigit())
    return (numeric, tag)


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    separator = "  "
    lines = [
        separator.join(header.ljust(widths[index]) for index, header in enumerate(headers)),
        separator.join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(separator.join(cell.ljust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(lines)


def _error_status(path: Path, error: str) -> ReleaseStatus:
    return ReleaseStatus(
        repo=path.name,
        path=str(path),
        branch="unknown",
        head="unknown",
        latest_local_tag=None,
        latest_remote_tag=None,
        commits_since_latest_tag=None,
        ahead_origin=None,
        behind_origin=None,
        worktree_clean=False,
        dirty_tracked_files=0,
        untracked_files=0,
        origin=None,
        upstream=None,
        version_surfaces=[],
        classifications=[error],
        errors=[error],
    )
