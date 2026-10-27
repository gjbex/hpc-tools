from __future__ import annotations

import hashlib
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from test_mcp_fixtures import McpFixtures

from hpc_tools import delegation, mcp_server
from hpc_tools.config import load_config, resolve_profile


class DelegatedLifecycleTests(McpFixtures, unittest.TestCase):
    def _runtime(self, root: Path) -> delegation.DelegationRuntime:
        config_path = self._write_config(root)
        manifest_path = root / "delegation.toml"
        manifest_path.write_text(
            textwrap.dedent(
                """
                format_version = 4
                id = "delegate-1"
                issuer = "operator"
                profile = "genius"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"
                [network]
                mode = "model-only"
                [allowed]
                accounts = ["proj"]
                clusters = ["wice", "other"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = []
                script_sha256 = []
                roots = ["/work/delegate-1"]
                [budget]
                max_submissions = 10
                max_active_jobs = 10
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        return delegation.load_runtime(
            manifest_path,
            profile="genius",
            ledger_path=root / "delegations.sqlite3",
            parent_job_id="9001",
            profile_policy=resolve_profile(
                load_config(str(config_path)), "genius"
            ).capabilities,
            config_path=config_path,
            config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        )

    def _own(
        self,
        runtime: delegation.DelegationRuntime,
        *,
        job_id: str,
        cluster: str = "wice",
    ) -> None:
        ledger = delegation.DelegationLedger(runtime.ledger_path)
        shape = {
            "profile": "genius",
            "account": "proj",
            "jobscript": "job.slurm",
            "directory": "/work/delegate-1/run",
            "overrides": {"account": "proj", "cluster": cluster},
        }
        key = f"submit-{job_id}-{cluster}"
        ledger.reserve_submission(
            runtime.manifest,
            idempotency_key=key,
            shape=shape,
        )
        ledger.record_submission(
            runtime.manifest,
            idempotency_key=key,
            job_id=job_id,
            cluster=cluster,
        )

    def test_listing_queries_only_owned_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            self._own(runtime, job_id="456")
            completed = mock.Mock(returncode=0, stdout="JOBID\n123\n456\n", stderr="")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ) as remote:
                result = mcp_server.hpc_jobs(
                    config=str(config), cluster="wice"
                )

        self.assertEqual(
            [{"job_id": "123", "cluster": "wice"}, {"job_id": "456", "cluster": "wice"}],
            result["owned_job_ids"],
        )
        self.assertIn("squeue -M wice -j 123,456", result["queries"][0]["command"])
        self.assertNotIn("-u", result["queries"][0]["command"])
        remote.assert_called_once()

    def test_restarted_controller_reconciles_before_new_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            ledger.begin_draining(runtime.manifest, reason="SIGUSR1")
            ledger.request_requeue(runtime.manifest)
            ledger.record_requeue_result(runtime.manifest, accepted=True)
            ledger.begin_controller(runtime.manifest, restart_count=1)
            with self.assertRaisesRegex(delegation.DelegationError, "reconciling"):
                ledger.reserve_submission(
                    runtime.manifest,
                    idempotency_key="blocked",
                    shape={
                        "profile": "genius",
                        "jobscript": "job.slurm",
                        "directory": "/work/delegate-1/run",
                        "overrides": {"account": "proj", "cluster": "wice"},
                    },
                )

            queue = mock.Mock(returncode=0, stdout="JOBID PARTITION NAME STATE\n", stderr="")
            accounting = mock.Mock(
                returncode=0,
                stdout="123|job|batch|proj|COMPLETED|0:0|00:01:00\n",
                stderr="",
            )
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture",
                side_effect=[queue, accounting],
            ):
                result = mcp_server.hpc_jobs(config=str(config), cluster="wice")

            self.assertTrue(result["reconciliation_complete"])
            self.assertEqual(1, len(result["reconciliation_queries"]))
            controller = ledger.controller_summary(runtime.manifest)
            self.assertEqual("running", controller["state"])
            self.assertFalse(controller["reconciliation_required"])
            self.assertEqual(0, ledger.summary(runtime.manifest)["active_jobs"])

    def test_partial_cluster_listing_cannot_clear_restart_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123", cluster="wice")
            self._own(runtime, job_id="456", cluster="other")
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            ledger.begin_draining(runtime.manifest, reason="SIGUSR1")
            ledger.request_requeue(runtime.manifest)
            ledger.record_requeue_result(runtime.manifest, accepted=True)
            ledger.begin_controller(runtime.manifest, restart_count=1)
            queue = mock.Mock(returncode=0, stdout="JOBID\n", stderr="")
            accounting = mock.Mock(
                returncode=0,
                stdout="123|job|batch|proj|COMPLETED|0:0|00:01:00\n",
                stderr="",
            )

            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture",
                side_effect=[queue, accounting],
            ):
                result = mcp_server.hpc_jobs(config=str(config), cluster="wice")

            self.assertFalse(result["reconciliation_complete"])
            self.assertTrue(
                ledger.controller_summary(runtime.manifest)["reconciliation_required"]
            )

    def test_inspection_requires_ownership_and_accepts_job_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            completed = mock.Mock(returncode=0, stdout="123_7 RUNNING\n", stderr="")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ) as remote:
                result = mcp_server.hpc_job(
                    "123_7", config=str(config), cluster="wice"
                )
                with self.assertRaisesRegex(delegation.DelegationError, "outside"):
                    mcp_server.hpc_job(
                        "999", config=str(config), cluster="wice"
                    )

        self.assertTrue(result["owned"])
        self.assertIn("-j 123_7", result["command"])
        remote.assert_called_once()

    def test_accounting_reconciles_terminal_owned_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            completed = mock.Mock(
                returncode=0,
                stdout="123|job|batch|proj|COMPLETED|0:0|00:01:00\n",
                stderr="",
            )
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ):
                result = mcp_server.hpc_job_accounting(
                    "123", config=str(config), cluster="wice"
                )

            summary = delegation.DelegationLedger(runtime.ledger_path).summary(
                runtime.manifest
            )

        self.assertEqual("COMPLETED", result["state"])
        self.assertTrue(result["ledger_reconciled"])
        self.assertEqual(0, summary["active_jobs"])
        self.assertIn("sacct -n -P -M wice -j 123", result["command"])

    def test_accounting_rejects_unowned_job_before_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture"
            ) as remote, self.assertRaisesRegex(
                delegation.DelegationError, "outside"
            ):
                mcp_server.hpc_job_accounting(
                    "999", config=str(config), cluster="wice"
                )
        remote.assert_not_called()

    def test_delegated_cancel_uses_authority_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ) as remote, mock.patch(
                "hpc_tools.mcp.tools.submissions.append_cancel_requested_events",
                side_effect=OSError("history unavailable"),
            ):
                arguments = {
                    "jobid": "123+1_7",
                    "config": str(config),
                    "cluster": "wice",
                    "idempotency_key": "cancel-1",
                    "dry_run": False,
                }
                result = mcp_server.hpc_cancel_job(**arguments)
                replay = mcp_server.hpc_cancel_job(**arguments)

        self.assertTrue(result["executed"])
        self.assertFalse(result["confirm_required"])
        self.assertTrue(result["ledger_recorded"])
        self.assertEqual("history unavailable", result["database_error"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["executed"])
        remote.assert_called_once()

    def test_delegated_cancel_rejects_unowned_job_before_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture"
            ) as remote, self.assertRaisesRegex(
                delegation.DelegationError, "outside"
            ):
                mcp_server.hpc_cancel_job(
                    "999",
                    config=str(config),
                    cluster="wice",
                    idempotency_key="cancel-1",
                    dry_run=False,
                )
        remote.assert_not_called()

    def test_delegated_cancel_recovers_uncertain_when_result_audit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self._write_config(root)
            runtime = self._runtime(root)
            self._own(runtime, job_id="123")
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with delegation.delegation_scope(runtime), mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ) as remote, mock.patch.object(
                delegation.DelegationLedger,
                "record_lifecycle_result",
                side_effect=delegation.DelegationError("audit unavailable"),
            ):
                result = mcp_server.hpc_cancel_job(
                    "123",
                    config=str(config),
                    cluster="wice",
                    idempotency_key="cancel-uncertain",
                    dry_run=False,
                )

            ledger = delegation.DelegationLedger(runtime.ledger_path)
            replay = ledger.reserve_lifecycle_operation(
                runtime.manifest,
                idempotency_key="cancel-uncertain",
                operation="cancel",
                job_id="123",
                cluster="wice",
            )

        self.assertTrue(result["ledger_recorded"])
        self.assertEqual("uncertain", result["ledger_status"])
        self.assertEqual("audit unavailable", result["ledger_error"])
        self.assertIsNone(result["ledger_recovery_error"])
        self.assertEqual("uncertain", replay["status"])
        remote.assert_called_once()


if __name__ == "__main__":
    unittest.main()
