# GitHub Steward Handoff

## Project purpose

GitHub Steward is a local-first, read-only CLI for inventorying GitHub repositories, scoring maintenance health, and writing advisory reports. Phase 1 is intentionally non-mutating: it reports on repositories and local release drift without archiving, deleting, renaming, transferring, opening issues or PRs, changing settings, or pushing commits.

## Current status

- Health-checked on 2026-06-30 from `/Users/mbeason/github-steward`
- Local tests pass from project root with a real local `.env` present
- `pyproject.toml` entry point works after editable install
- `sample`, `validate`, and `run` all behave as documented
- Local and remote git state were clean and synchronized at handoff time

Current git remote: `origin https://github.com/matthewbeason/github-steward.git`
Current git branch: `main`

## Safety model

- GitHub API access is read-only by design
- The client uses `GET` requests only
- Normal CLI commands are for inventory, validation, reporting, and local release-status checks
- Reports are advisory only and always dry-run output
- Secrets belong in `.env`, not config files or reports

## CLI commands

Run from source:

```bash
PYTHONPATH=src python3 -m github_steward.cli --help
PYTHONPATH=src python3 -m github_steward.cli validate --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli sample --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli run --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli release-status --config steward.config.json
PYTHONPATH=src python3 -m github_steward.cli release-status --config steward.config.json --json
```

Installed entry point:

```bash
python3 -m pip install -e .
github-steward --help
```

## Required token permissions

Use a fine-grained GitHub personal access token in `.env` as `GITHUB_TOKEN`.

Recommended permissions:

- Metadata: read
- Contents: read
- Pull requests: read, if pull request checks stay enabled
- Actions: read, if workflow checks stay enabled

Do not grant write or admin permissions for normal use.

## Report outputs

Current core outputs written by `sample` and `run`:

- `reports/repo-inventory.json`
- `reports/repo-health.md`
- `reports/archive-candidates.md`
- `reports/delete-candidates.md`
- `reports/portfolio-candidates.md`
- `reports/decision-ledger.json`
- `reports/decision-ledger.md`

The `reports/` directory is gitignored. Older ignored report files may exist locally from previous runs; treat them as disposable local artifacts unless a human explicitly wants to keep them.

## Test command

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Known limitations

- `run` depends on live GitHub API availability and token access
- Optional repo metadata can downgrade to unknown when permissions or endpoints are limited
- `release-status` version detection is heuristic by design and should stay focused on obvious current version surfaces
- The tool is intentionally advisory; any future mutation workflow should be added as a separate, explicitly reviewed phase

## How opencode should continue safely

- Keep Phase 1 read-only unless a human explicitly opens a new mutation phase
- Prefer `sample`, `validate`, `run`, and `release-status` for normal checks
- Keep tests hermetic and do not let local `.env` state leak into unit tests
- Keep secrets out of `steward.config.json`, tracked files, and reports
- If you add new report files, update README and this handoff note together
- Re-run tests and the relevant CLI commands after any code or doc change

## Explicit warning

Do not commit `.env`.
Do not commit anything under `reports/`.
