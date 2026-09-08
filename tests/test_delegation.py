from __future__ import annotations

import sqlite3
import tempfile
import textwrap
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

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
                format_version = 2
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

    def test_lifecycle_policy_has_strict_defaults_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            manifest = delegation.load_manifest(path, expected_profile="genius")
            self.assertEqual(
                {
                    "on_cancel": "cancel",
                    "on_timeout": "requeue-or-cancel",
                    "on_failure": "cancel",
                    "on_normal_exit_with_active_jobs": "cancel",
                    "max_requeues": 3,
                    "warning_seconds": 600,
                },
                manifest.lifecycle.public_summary(),
            )

            path.write_text(
                path.read_text(encoding="utf-8")
                + '\n[lifecycle]\non_cancel = "leave-running"\nmax_requeues = 0\n',
                encoding="utf-8",
            )
            explicit = delegation.load_manifest(path, expected_profile="genius")
            self.assertEqual("leave-running", explicit.lifecycle.on_cancel)
            self.assertEqual(0, explicit.lifecycle.max_requeues)

            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'on_cancel = "leave-running"', 'on_cancel = "ignore"'
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "on_cancel"):
                delegation.load_manifest(path, expected_profile="genius")

    def test_controller_requeue_blocks_submission_until_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            self.assertEqual(1, ledger.controller_summary(manifest)["generation"])

            ledger.begin_draining(manifest, reason="SIGUSR1")
            self.assertEqual(0, ledger.inflight_submission_count(manifest))
            with self.assertRaisesRegex(delegation.DelegationError, "draining"):
                ledger.reserve_submission(
                    manifest, idempotency_key="blocked-1", shape=self._shape()
                )
            ledger.request_requeue(manifest)
            ledger.record_requeue_result(manifest, accepted=True, detail="accepted")
            restarted = ledger.begin_controller(manifest, restart_count=1)
            self.assertEqual("reconciling", restarted["state"])
            self.assertEqual(2, restarted["generation"])
            with self.assertRaisesRegex(delegation.DelegationError, "reconciling"):
                ledger.reserve_submission(
                    manifest, idempotency_key="blocked-2", shape=self._shape()
                )
            ledger.complete_reconciliation(manifest)
            accepted = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertEqual("reserved", accepted["status"])

    def test_drain_exposes_submission_reserved_before_it_started(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            ledger.begin_draining(manifest, reason="SIGUSR1")
            self.assertEqual(1, ledger.inflight_submission_count(manifest))
            ledger.release_reservation(
                manifest, idempotency_key="request-1", reason="submission stopped"
            )
            self.assertEqual(0, ledger.inflight_submission_count(manifest))

    def test_concurrent_drain_and_submission_have_one_serialized_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            barrier = threading.Barrier(2)

            def reserve() -> str:
                barrier.wait()
                try:
                    ledger.reserve_submission(
                        manifest, idempotency_key="request-1", shape=self._shape()
                    )
                except delegation.DelegationError:
                    return "rejected"
                return "reserved"

            def drain() -> str:
                barrier.wait()
                ledger.begin_draining(manifest, reason="SIGUSR1")
                return "draining"

            with ThreadPoolExecutor(max_workers=2) as pool:
                reserve_future = pool.submit(reserve)
                drain_future = pool.submit(drain)
                reserve_result = reserve_future.result()
                self.assertEqual("draining", drain_future.result())

            self.assertIn(reserve_result, {"reserved", "rejected"})
            self.assertEqual(
                1 if reserve_result == "reserved" else 0,
                ledger.inflight_submission_count(manifest),
            )
            self.assertEqual("draining", ledger.controller_summary(manifest)["state"])

    def test_controller_requeue_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n[lifecycle]\nmax_requeues = 0\n",
                encoding="utf-8",
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.begin_draining(manifest, reason="SIGUSR1")
            with self.assertRaisesRegex(delegation.DelegationError, "limit"):
                ledger.request_requeue(manifest)

    def test_restart_recovers_when_requeue_acceptance_was_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            ledger.begin_draining(manifest, reason="SIGUSR1")
            ledger.request_requeue(manifest)

            restarted = ledger.begin_controller(manifest, restart_count=1)

            self.assertEqual("reconciling", restarted["state"])
            self.assertTrue(restarted["reconciliation_required"])

    def test_old_ledger_schema_is_rejected_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute("PRAGMA user_version=2")
            ledger_path.chmod(0o600)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            with self.assertRaisesRegex(delegation.DelegationError, "schema version 2"):
                delegation.DelegationLedger(ledger_path).register(manifest)

    def test_expired_malformed_and_misspelled_manifests_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expired = self._manifest(root, expires_at="2026-01-02T00:00:00Z")
            with self.assertRaisesRegex(delegation.DelegationError, "expired"):
                delegation.load_manifest(
                    expired,
                    expected_profile="genius",
                    now=datetime(2026, 8, 1, tzinfo=timezone.utc),
                )

            malformed = root / "delegation.toml"
            malformed.write_text("this is not = valid = TOML\n", encoding="utf-8")
            with self.assertRaisesRegex(delegation.DelegationError, "invalid"):
                delegation.load_manifest(malformed, expected_profile="genius")

            misspelled = self._manifest(root)
            misspelled.write_text(
                misspelled.read_text(encoding="utf-8").replace(
                    "max_submissions = 2", "max_submissons = 2"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(delegation.DelegationError, "max_submissons"):
                delegation.load_manifest(misspelled, expected_profile="genius")

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

    def test_all_scheduler_and_payload_policy_dimensions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._manifest(root)
            approved_digest = "a" * 64
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "script_sha256 = []",
                    f'script_sha256 = ["{approved_digest}"]',
                ),
                encoding="utf-8",
            )
            manifest = delegation.load_manifest(path, expected_profile="genius")
            shape = self._shape()
            shape["boundary"] = {
                "container": "/images/worker.sif",
                "script_sha256": approved_digest,
            }
            delegation.authorize_shape(manifest, shape)

            cases = {
                "account": ("overrides", "account", "other"),
                "cluster": ("overrides", "cluster", "other"),
                "partition": ("overrides", "partition", "other"),
                "qos": ("overrides", "qos", "other"),
                "container": ("boundary", "container", "/images/other.sif"),
                "script_sha256": ("boundary", "script_sha256", "b" * 64),
                "nodes": ("overrides", "nodes", "3"),
            }
            for label, (section, field, value) in cases.items():
                with self.subTest(label=label):
                    denied = {
                        **shape,
                        "overrides": dict(shape["overrides"]),
                        "boundary": dict(shape["boundary"]),
                    }
                    denied[section][field] = value
                    with self.assertRaises(delegation.DelegationError):
                        delegation.authorize_shape(manifest, denied)

            outside = {
                **shape,
                "directory": "/work/other",
                "overrides": dict(shape["overrides"]),
                "boundary": dict(shape["boundary"]),
            }
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

    def test_array_elements_consume_cumulative_node_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)
            with self.assertRaisesRegex(delegation.DelegationError, "aggregate nodes"):
                ledger.reserve_submission(
                    manifest,
                    idempotency_key="array-1",
                    shape=self._shape(array="0-3"),
                )

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

    def test_concurrent_duplicate_key_submits_once_and_budget_stays_capped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = delegation.load_manifest(
                self._manifest(root), expected_profile="genius"
            )
            ledger = delegation.DelegationLedger(root / "ledger.sqlite3")
            ledger.register(manifest)

            def reserve() -> dict[str, object]:
                return ledger.reserve_submission(
                    manifest, idempotency_key="same-request", shape=self._shape()
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: reserve(), range(2)))
            self.assertEqual(
                [False, True],
                sorted(result["idempotent_replay"] for result in results),
            )
            summary = ledger.summary(manifest)
            self.assertEqual(1, summary["used_submissions"])
            self.assertEqual(1, summary["active_jobs"])
            with self.assertRaisesRegex(delegation.DelegationError, "active-job"):
                ledger.reserve_submission(
                    manifest, idempotency_key="another-request", shape=self._shape()
                )

    def test_accepted_submission_recovery_retains_ownership_and_budget(self) -> None:
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
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_submission_audit
                       BEFORE INSERT ON delegation_audit
                       WHEN NEW.operation = 'record_submission'
                       BEGIN SELECT RAISE(FAIL, 'audit unavailable'); END"""
                )
                connection.commit()

            with self.assertRaisesRegex(delegation.DelegationError, "audit unavailable"):
                ledger.record_submission(
                    manifest,
                    idempotency_key="request-1",
                    job_id="12345",
                    cluster="wice",
                )
            ledger.record_accepted_submission_uncertain(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
                reason="audit unavailable",
            )

            self.assertTrue(ledger.owns_job("delegate-1", "12345", "wice"))
            replay = ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=self._shape()
            )
            self.assertEqual("uncertain", replay["status"])
            self.assertEqual(1, ledger.summary(manifest)["active_jobs"])
            ledger.reconcile_job(
                manifest, job_id="12345", cluster="wice", state="COMPLETED"
            )
            self.assertEqual(0, ledger.summary(manifest)["active_jobs"])

    def test_accepted_cancellation_recovery_is_not_replayed(self) -> None:
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
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="wice",
            )
            ledger.reserve_lifecycle_operation(
                manifest,
                idempotency_key="cancel-1",
                operation="cancel",
                job_id="12345",
                cluster="wice",
            )
            with closing(sqlite3.connect(ledger_path)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_lifecycle_audit
                       BEFORE INSERT ON delegation_audit
                       WHEN NEW.operation = 'lifecycle_result'
                       BEGIN SELECT RAISE(FAIL, 'audit unavailable'); END"""
                )
                connection.commit()

            result = {"returncode": 0, "jobid": "12345"}
            with self.assertRaisesRegex(delegation.DelegationError, "audit unavailable"):
                ledger.record_lifecycle_result(
                    manifest,
                    idempotency_key="cancel-1",
                    succeeded=True,
                    result=result,
                )
            ledger.record_accepted_lifecycle_uncertain(
                manifest,
                idempotency_key="cancel-1",
                result=result,
                reason="audit unavailable",
            )
            replay = ledger.reserve_lifecycle_operation(
                manifest,
                idempotency_key="cancel-1",
                operation="cancel",
                job_id="12345",
                cluster="wice",
            )
            self.assertEqual("uncertain", replay["status"])
            self.assertEqual(0, replay["result"]["returncode"])

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
