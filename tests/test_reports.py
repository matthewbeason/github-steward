from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from github_steward.cli import sample_inventory
from github_steward.reports import build_decision_ledger, write_reports
from github_steward.scoring import assess_repo


THRESHOLDS = {
    "archive_after_days": 730,
    "delete_review_after_days": 1460,
    "portfolio_recent_days": 365,
    "small_repo_kb": 256,
}


@dataclass(frozen=True)
class FakeConfig:
    output_dir: str
    classification: dict[str, int]


class ReportTests(unittest.TestCase):
    def test_report_writer_creates_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig(tmp, THRESHOLDS)

            write_reports(sample_inventory(), config)

            names = {path.name for path in Path(tmp).iterdir()}
        self.assertEqual(
            names,
            {
                "repo-inventory.json",
                "repo-health.md",
                "archive-candidates.md",
                "delete-candidates.md",
                "portfolio-candidates.md",
                "decision-ledger.json",
                "decision-ledger.md",
            },
        )

    def test_health_report_includes_timestamp_and_account_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig(tmp, THRESHOLDS)
            inventory = sample_inventory()

            write_reports(inventory, config)
            health = (Path(tmp) / "repo-health.md").read_text(encoding="utf-8")

        self.assertIn(inventory.generated_at, health)
        self.assertIn("sample-user", health)

    def test_inventory_json_contains_safety_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig(tmp, THRESHOLDS)

            write_reports(sample_inventory(), config)
            payload = json.loads((Path(tmp) / "repo-inventory.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["safety_mode"], "READ_ONLY_DRY_RUN")

    def test_ledger_entries_are_generated(self) -> None:
        inventory = sample_inventory()
        assessments = [assess_repo(repo, THRESHOLDS) for repo in inventory.repositories]

        ledger = build_decision_ledger(assessments, inventory.generated_at, THRESHOLDS)

        self.assertEqual(len(ledger), len(inventory.repositories))
        self.assertIn("evidence_fields_used", ledger[0])

    def test_missing_metadata_lowers_confidence(self) -> None:
        inventory = sample_inventory()
        assessment = next(
            assess_repo(repo, THRESHOLDS) for repo in inventory.repositories if repo.full_name.endswith("permission-limited")
        )

        ledger = build_decision_ledger([assessment], inventory.generated_at, THRESHOLDS)

        self.assertEqual(ledger[0]["confidence"], "LOW")

    def test_all_ledger_entries_include_read_only_safety_status(self) -> None:
        inventory = sample_inventory()
        assessments = [assess_repo(repo, THRESHOLDS) for repo in inventory.repositories]

        ledger = build_decision_ledger(assessments, inventory.generated_at, THRESHOLDS)

        self.assertTrue(all(entry["safety_status"] == "READ_ONLY_RECOMMENDATION" for entry in ledger))


if __name__ == "__main__":
    unittest.main()
