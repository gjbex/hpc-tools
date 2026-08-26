from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import textwrap
import unittest

from hpc_tools import delegation


class DelegationTests(unittest.TestCase):
    def _manifest(self, root: Path, **changes: str) -> Path:
        values = {
            "id": "delegate-1",
            "profile": "genius",
            "parent_job_id": "9001",
            "expires_at": "2099-01-01T00:00:00Z",
        } | changes
        path = root / "delegation.toml"
        path.write_text(
            textwrap.dedent(
                f"""
                format_version = 1
                id = "{values['id']}"
                issuer = "operator@example.org"
                profile = "{values['profile']}"
                parent_job_id = "{values['parent_job_id']}"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "{values['expires_at']}"

                [allowed]
                accounts = ["proj"]
                clusters = ["wice"]
                partitions = ["batch"]
                qos = ["normal"]
                reservations = []
                containers = ["/images/worker.sif"]
                script_sha256 = []
                roots = ["/work/delegate-1"]

                [per_job_limits]
                nodes = 2
                tasks = 8
                wall_seconds = 3600
                array_tasks = 10

                [budget]
                max_submissions = 2
                max_active_jobs = 1
                max_total_nodes = 3
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        return path

    def _shape(self, **overrides: str) -> dict[str, object]:
        values = {
            "account": "proj",
            "cluster": "wice",
            "partition": "batch",
            "qos": "normal",
            "nodes": "1",
            "ntasks": "4",
            "time": "00:30:00",
        } | overrides
        return {
            "profile": "genius",
            "jobscript": "job.slurm",
            "directory": "/work/delegate-1/run",
            "overrides": values,
            "shape_token": "test-token",
        }

    def test_manifest_binds_profile_parent_expiry_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            manifest = delegation.load_manifest(
                path,
                expected_profile="genius",
                expected_parent_job_id="9001",
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
            )
            self.assertEqual("delegate-1", manifest.identifier)
            with self.assertRaisesRegex(delegation.DelegationError, "profile"):
                delegation.load_manifest(path, expected_profile="other")
            with self.assertRaisesRegex(delegation.DelegationError, "parent"):
                delegation.load_manifest(
                    path, expected_profile="genius", expected_parent_job_id="9002"
                )
            path.chmod(0o666)
            with self.assertRaisesRegex(delegation.DelegationError, "writable"):
                delegation.load_manifest(path, expected_profile="genius")

    def test_policy_only_narrows_scheduler_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = delegation.load_manifest(
                self._manifest(Path(directory)), expected_profile="genius"
            )
            delegation.authorize_shape(manifest, self._shape())
            with self.assertRaisesRegex(delegation.DelegationError, "account"):
                delegation.authorize_shape(manifest, self._shape(account="other"))
            with self.assertRaisesRegex(delegation.DelegationError, "nodes"):
                delegation.authorize_shape(manifest, self._shape(nodes="3"))
            outside = self._shape()
            outside["directory"] = "/work/other"
            with self.assertRaisesRegex(delegation.DelegationError, "roots"):
                delegation.authorize_shape(manifest, outside)

    def test_ledger_enforces_idempotency_budget_ownership_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            first = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertFalse(first["idempotent_replay"])
            with self.assertRaisesRegex(delegation.DelegationError, "active-job"):
                ledger.reserve_submission(
                    manifest, idempotency_key="request-2", shape=self._shape()
                )
            replay = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertTrue(replay["idempotent_replay"])
            changed = self._shape(nodes="2")
            with self.assertRaisesRegex(delegation.DelegationError, "different request"):
                ledger.reserve_submission(
                    manifest, idempotency_key="request-1", shape=changed
                )
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            self.assertTrue(ledger.owns_job("delegate-1", "12345", "wice"))
            self.assertFalse(ledger.owns_job("delegate-1", "99999", "wice"))
            ledger.reconcile_job(
                manifest, job_id="12345", cluster="wice", state="COMPLETED"
            )
            second = ledger.reserve_submission(
                manifest,
                idempotency_key="request-2",
                shape=self._shape(nodes="2"),
            )
            self.assertEqual("reserved", second["status"])
            summary = ledger.summary(manifest)
            self.assertEqual(2, summary["used_submissions"])
            self.assertEqual(1, summary["active_jobs"])
            self.assertEqual(0, summary["remaining"]["max_total_nodes"])

    def test_failed_reservation_releases_budget_and_rejection_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            ledger.release_reservation(
                manifest, idempotency_key="request-1", reason="sbatch failed"
            )
            ledger.reserve_submission(
                manifest, idempotency_key="request-2", shape=self._shape()
            )
            with self.assertRaises(delegation.DelegationError):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="request-3",
                    shape=self._shape(account="other"),
                )
            with closing(sqlite3.connect(ledger_path)) as connection:
                decisions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT decision FROM delegation_audit ORDER BY sequence"
                    )
                ]
            self.assertIn("rejected", decisions)

    def test_concurrent_first_use_and_reservations_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger_path = root / "ledger.sqlite3"

            with ThreadPoolExecutor(max_workers=2) as pool:
                registrations = [
                    pool.submit(
                        delegation.DelegationLedger(ledger_path).register,
                        manifest,
                    )
                    for _ in range(2)
                ]
                for future in registrations:
                    future.result()

            ledger = delegation.DelegationLedger(ledger_path)
            def reserve(key: str) -> str:
                try:
                    ledger.reserve_submission(
                        manifest, idempotency_key=key, shape=self._shape()
                    )
                except delegation.DelegationError:
                    return "rejected"
                return "accepted"

            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions = list(pool.map(reserve, ("request-1", "request-2")))
            self.assertEqual(["accepted", "rejected"], sorted(decisions))

    def test_revocation_blocks_further_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.revoke(manifest.identifier, reason="operator request")
            with self.assertRaisesRegex(delegation.DelegationError, "revoked"):
                ledger.summary(manifest)


if __name__ == "__main__":
    unittest.main()
