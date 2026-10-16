from __future__ import annotations

import json
import sqlite3
import tempfile
import textwrap
import unittest
from dataclasses import fields
from pathlib import Path

from hpc_tools import delegation, slurm_contracts
from hpc_tools.config import Profile

BASELINE_PATH = (
    Path(__file__).parent / "fixtures" / "delegated_credit_budget_baseline.json"
)


class DelegatedCreditBudgetBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["current"]

    @staticmethod
    def _write_manifest(root: Path) -> Path:
        path = root / "delegation.toml"
        path.write_text(
            textwrap.dedent(
                """
                format_version = 3
                id = "credit-baseline"
                issuer = "operator"
                profile = "genius"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [allowed]
                accounts = ["proj"]
                clusters = ["wice"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = []
                script_sha256 = []
                roots = ["/work/credit-baseline"]

                [budget]
                max_submissions = 2
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _shape(*, array: str | None = None) -> dict[str, object]:
        overrides = {
            "account": "proj",
            "cluster": "wice",
            "partition": "batch",
            "nodes": "1",
        }
        if array is not None:
            overrides["array"] = array
        shape: dict[str, object] = {
            "profile": "genius",
            "jobscript": "job.slurm",
            "directory": "/work/credit-baseline/run",
            "overrides": overrides,
        }
        shape["shape_token"] = slurm_contracts.shape_token(shape)
        return shape

    def test_current_versions_profile_fields_and_ledger_columns_match_snapshot(
        self,
    ) -> None:
        self.assertEqual(self.baseline["manifest_version"], delegation.MANIFEST_VERSION)
        self.assertEqual(
            self.baseline["ledger_schema_version"], delegation.LEDGER_SCHEMA_VERSION
        )
        self.assertEqual(
            self.baseline["profile_quote_fields"],
            [field.name for field in fields(Profile) if "quote" in field.name],
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._write_manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"
            delegation.DelegationLedger(ledger_path).register(manifest)
            with sqlite3.connect(ledger_path) as connection:
                columns = [
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(submission_operations)"
                    )
                ]

        self.assertEqual(self.baseline["submission_operation_columns"], columns)

    def test_quote_evidence_remains_unexpired_and_has_no_typed_cost(self) -> None:
        shape = self._shape()
        evidence = slurm_contracts.submission_evidence(
            "quote",
            shape,
            {
                "command": "sam-quote sbatch --account proj job.slurm",
                "executor": "local",
                "execution_command": "sam-quote sbatch --account proj job.slurm",
                "ssh_command": None,
                "returncode": 0,
                "stdout": "Maximum charge: 2730 credits\n",
                "stderr": "",
                "dry_run": False,
            },
        )

        self.assertEqual(self.baseline["quote_evidence_fields"], sorted(evidence))
        self.assertEqual("Maximum charge: 2730 credits\n", evidence["stdout"])
        self.assertTrue(self.baseline["structured_quote_supported"])
        self.assertFalse(self.baseline["quote_expiry_supported"])
        self.assertNotIn("quoted_cost", evidence)
        self.assertNotIn("expires_at", evidence)

    def test_manifest_v3_accepts_the_frozen_credit_budget_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_manifest(root)
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n[credit_budget]\n"
                + 'unit = "credits"\n'
                + "scale = 0\n"
                + "maximum_total = 20000\n"
                + "quote_ttl_seconds = 300\n",
                encoding="utf-8",
            )

            manifest = delegation.load_manifest(path, expected_profile="genius")

        self.assertTrue(self.baseline["credit_budget_manifest_supported"])
        self.assertEqual(20000, manifest.credit_budget.maximum_total)
        self.assertEqual(300, manifest.credit_budget.quote_ttl_seconds)

    def test_submission_count_is_per_logical_job_and_released_failure_is_refunded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._write_manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)

            ledger.reserve_submission(
                manifest,
                idempotency_key="array-request",
                shape=self._shape(array="0-3"),
            )
            first_summary = ledger.summary(manifest)
            self.assertEqual(1, first_summary["used_submissions"])
            self.assertEqual(4, first_summary["requested_resources"]["nodes"])

            ledger.reserve_submission(
                manifest,
                idempotency_key="single-request",
                shape=self._shape(),
            )
            with self.assertRaisesRegex(
                delegation.DelegationError, "submission budget"
            ):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="over-budget",
                    shape=self._shape(),
                )

            ledger.release_reservation(
                manifest,
                idempotency_key="single-request",
                reason="definite pre-acceptance failure",
            )
            replacement = ledger.reserve_submission(
                manifest,
                idempotency_key="replacement-request",
                shape=self._shape(),
            )

        self.assertEqual(
            "logical-submission", self.baseline["array_submission_count_unit"]
        )
        self.assertEqual("reserved", replacement["status"])

    def test_controller_generation_is_a_characterized_evidence_binding_gap(
        self,
    ) -> None:
        first = self._shape()
        first.pop("shape_token")
        first["boundary"] = {
            "container": "/images/worker.sif",
            "script_sha256": "a" * 64,
            "idempotency_key": "request-1",
        }
        first["controller_generation"] = 1
        first["shape_token"] = slurm_contracts.shape_token(first)
        evidence = slurm_contracts.submission_evidence(
            "quote",
            first,
            {
                "command": "site-quote sbatch job.slurm",
                "executor": "local",
                "execution_command": "site-quote sbatch job.slurm",
                "ssh_command": None,
                "returncode": 0,
                "stdout": "2730\n",
                "stderr": "",
                "dry_run": False,
            },
        )
        restarted = dict(first)
        restarted["controller_generation"] = 2
        restarted["shape_token"] = slurm_contracts.shape_token(restarted)

        self.assertNotEqual(first["shape_token"], restarted["shape_token"])
        self.assertNotEqual(first["shape_token"], evidence["shape_token"])
        slurm_contracts.validate_evidence(
            "quote", evidence, restarted, executor="local"
        )
        self.assertFalse(self.baseline["controller_generation_bound_to_evidence"])


if __name__ == "__main__":
    unittest.main()
