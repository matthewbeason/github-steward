# GitHub Steward

GitHub Steward is a local-first, read-only repository stewardship CLI for GitHub accounts and organizations.

It inventories repositories through GitHub's REST API, scores maintenance health, classifies repositories into review buckets, and writes dry-run reports with auditable reasoning. Phase 1 never mutates GitHub state: it does not archive, delete, rename, transfer, open issues, create pull requests, push commits, or make any other write-side GitHub changes.

## Commands

Run from source:

```bash
PYTHONPATH=src python3 -m github_steward.cli validate --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli sample --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli run --config steward.config.json
```

Install locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
github-steward validate --config steward.config.json
github-steward sample --config steward.config.json
github-steward run --config steward.config.json
```

`validate` checks config shape, loads `.env`, confirms token presence when an `authenticated_user` target requires it, and probes `GET /user` when a token is available. It does not fetch repository inventory.

`sample` writes reports from built-in sample data and requires no token or network access.

`run` fetches repository inventory and writes local dry-run reports.

## Token Setup

Copy the example environment file:

```bash
cp .env.example .env
```

Use a fine-grained GitHub personal access token with read-only permissions. Recommended permissions are:

- Metadata: read
- Contents: read
- Pull requests: read, if pull request checks are enabled
- Actions: read, if workflow checks are enabled

Avoid broad classic `repo` scope for Phase 1, and do not grant write or admin permissions.

## Configuration

The default `steward.config.json` targets the authenticated user:

```json
{
  "version": 1,
  "token_env": "GITHUB_TOKEN",
  "output_dir": "reports",
  "targets": [
    {
      "kind": "authenticated_user",
      "visibility": "all",
      "affiliation": "owner,collaborator,organization_member"
    }
  ],
  "checks": {
    "readme": true,
    "pull_requests": true,
    "workflows": true
  },
  "classification": {
    "archive_after_days": 730,
    "delete_review_after_days": 1460,
    "portfolio_recent_days": 365,
    "small_repo_kb": 256
  }
}
```

Supported target kinds:

```json
{ "kind": "authenticated_user" }
{ "kind": "user", "username": "some-user" }
{ "kind": "org", "org": "some-org" }
```

Secrets belong in `.env`, not in `steward.config.json`. The config loader rejects likely token and secret fields.

## Reports

Generated files:

- `reports/repo-inventory.json`
- `reports/repo-health.md`
- `reports/archive-candidates.md`
- `reports/delete-candidates.md`
- `reports/portfolio-candidates.md`
- `reports/decision-ledger.json`
- `reports/decision-ledger.md`

Candidate reports are review queues only. `DELETE_REVIEW` means manual review, not deletion.

## Classification Buckets

- `KEEP`: no cleanup action recommended
- `IMPROVE`: documentation, metadata, or maintenance signals need attention
- `ARCHIVE_CANDIDATE`: stale and inactive enough for archive review
- `DELETE_REVIEW`: very old, small, undocumented, inactive manual review queue
- `PORTFOLIO_CANDIDATE`: recent, public, healthy repository that may be worth featuring

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Safety Rules

- Keep Phase 1 read-only.
- Do not add GitHub write methods to `GitHubClient`.
- Do not store secrets in config or reports.
- Keep `.env` ignored.
- Keep recommendations advisory.
- Add tests for scoring, classification, report schema, or CLI behavior changes.
