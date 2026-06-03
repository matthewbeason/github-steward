from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when steward configuration is invalid."""


@dataclass(frozen=True)
class StewardConfig:
    version: int
    token_env: str
    output_dir: str
    targets: list[dict[str, Any]]
    checks: dict[str, bool]
    classification: dict[str, int]


DEFAULT_CHECKS = {
    "readme": True,
    "pull_requests": True,
    "workflows": True,
}

DEFAULT_CLASSIFICATION = {
    "archive_after_days": 730,
    "delete_review_after_days": 1460,
    "portfolio_recent_days": 365,
    "small_repo_kb": 256,
}

SECRET_KEYWORDS = ("secret", "password", "private_key", "access_token", "github_token")
SECRET_VALUE_PREFIXES = ("github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_")


def load_config(path: str | Path) -> StewardConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Config root must be a JSON object.")

    _reject_likely_secrets(data)

    version = data.get("version", 1)
    if version != 1:
        raise ConfigError("Only config version 1 is supported.")

    token_env = data.get("token_env", "GITHUB_TOKEN")
    if not isinstance(token_env, str) or not token_env:
        raise ConfigError("token_env must be a non-empty string.")

    output_dir = data.get("output_dir", "reports")
    if not isinstance(output_dir, str) or not output_dir:
        raise ConfigError("output_dir must be a non-empty string.")

    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ConfigError("targets must be a non-empty array.")
    for target in targets:
        _validate_target(target)

    provided_checks = data.get("checks", {})
    if not isinstance(provided_checks, dict):
        raise ConfigError("checks must be an object.")
    checks = DEFAULT_CHECKS | provided_checks
    for key, value in checks.items():
        if key not in DEFAULT_CHECKS:
            raise ConfigError(f"Unsupported check: {key}")
        if not isinstance(value, bool):
            raise ConfigError(f"checks.{key} must be a boolean.")

    provided_classification = data.get("classification", {})
    if not isinstance(provided_classification, dict):
        raise ConfigError("classification must be an object.")
    classification = DEFAULT_CLASSIFICATION | provided_classification
    for key, value in classification.items():
        if key not in DEFAULT_CLASSIFICATION:
            raise ConfigError(f"Unsupported classification threshold: {key}")
        if not isinstance(value, int) or value < 0:
            raise ConfigError(f"classification.{key} must be a non-negative integer.")
    if classification["delete_review_after_days"] < classification["archive_after_days"]:
        raise ConfigError("delete_review_after_days must be >= archive_after_days.")
    if classification["portfolio_recent_days"] > classification["archive_after_days"]:
        raise ConfigError("portfolio_recent_days must be <= archive_after_days.")

    return StewardConfig(
        version=version,
        token_env=token_env,
        output_dir=output_dir,
        targets=targets,
        checks=checks,
        classification=classification,
    )


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def target_requires_token(targets: list[dict[str, Any]]) -> bool:
    return any(target.get("kind") == "authenticated_user" for target in targets)


def _validate_target(target: Any) -> None:
    if not isinstance(target, dict):
        raise ConfigError("Each target must be an object.")
    kind = target.get("kind")
    if kind not in {"authenticated_user", "user", "org"}:
        raise ConfigError("target.kind must be authenticated_user, user, or org.")
    if kind == "user" and not target.get("username"):
        raise ConfigError("user targets require username.")
    if kind == "org" and not target.get("org"):
        raise ConfigError("org targets require org.")


def _reject_likely_secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if lowered != "token_env" and any(word in lowered for word in SECRET_KEYWORDS):
                raise ConfigError(f"Config must not contain secrets: {key_path}")
            _reject_likely_secrets(child, key_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_likely_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and value.startswith(SECRET_VALUE_PREFIXES):
        raise ConfigError(f"Config appears to contain a GitHub token at {path}. Use .env instead.")
