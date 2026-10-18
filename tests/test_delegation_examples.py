from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from hpc_tools import delegation

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "delegations"


class DelegationExampleTests(unittest.TestCase):
    def test_credit_examples_are_accepted_by_the_runtime_parser(self) -> None:
        examples = {
            "restricted-agent-credit-minimal.toml": 4,
            "restricted-agent-credit-full.toml": 20,
        }
        for name, expected_submissions in examples.items():
            with self.subTest(name=name):
                manifest = delegation.load_manifest(
                    EXAMPLES / name,
                    expected_profile="example",
                    expected_parent_job_id="123456",
                    now=datetime(2026, 10, 17, 12, 0, tzinfo=UTC),
                )
                self.assertEqual(3, delegation.MANIFEST_VERSION)
                self.assertEqual(
                    expected_submissions,
                    manifest.budget["max_submissions"],
                )
                self.assertIsNotNone(manifest.credit_budget)
                self.assertIsNotNone(manifest.filesystem)

    def test_schema_tracks_the_frozen_credit_contract(self) -> None:
        schema = json.loads(
            (EXAMPLES / "delegation-manifest-v3.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(3, schema["properties"]["format_version"]["const"])
        credit = schema["$defs"]["creditBudget"]
        self.assertEqual(
            {"unit", "scale", "maximum_total", "quote_ttl_seconds"},
            set(credit["required"]),
        )
        self.assertEqual(86400, credit["properties"]["quote_ttl_seconds"]["maximum"])
        self.assertNotIn("budget", schema["required"])
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
