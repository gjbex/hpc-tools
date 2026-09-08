from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from hpc_tools import agent_cleanup, delegation
from hpc_tools.config import ConfigError


class AgentCleanupTests(unittest.TestCase):
    def _manifest(
        self,
        root: Path,
        *,
        identifier: str = "delegate-1",
        parent_job_id: str = "9001",
        lifecycle: str = "",
    ) -> delegation.DelegationManifest:
        path = root / f"{identifier}.toml"
        path.write_text(
            textwrap.dedent(
                f"""
                format_version = 2
                id = "{identifier}"
                issuer = "operator"
                profile = "cluster"
                parent_job_id = "{parent_job_id}"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [allowed]
                accounts = ["project"]
                clusters = ["alpha"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = []
                script_sha256 = []
                roots = ["/work/{identifier}"]

                [budget]
                max_submissions = 4
                max_active_jobs = 4
                {lifecycle}
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return delegation.load_manifest(path, expected_profile="cluster")

    def _own(
        self,
        ledger: delegation.DelegationLedger,
        manifest: delegation.DelegationManifest,
        job_id: str,
    ) -> None:
        shape = {
            "profile": "cluster",
            "jobscript": "job.slurm",
            "directory": f"/work/{manifest.identifier}/run",
            "overrides": {"account": "project", "cluster": "alpha"},
        }
        key = f"submit-{job_id}"
        ledger.reserve_submission(manifest, idempotency_key=key, shape=shape)
        ledger.record_submission(
            manifest,
            idempotency_key=key,
            job_id=job_id,
            cluster="alpha",
        )

    @staticmethod
    def _completed(
        *, returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_cancel_policy_mutates_only_exact_ledger_owned_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            manifest = self._manifest(root)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            self._own(ledger, manifest, "123")

            unrelated = self._manifest(
                root, identifier="delegate-2", parent_job_id="9002"
            )
            ledger.register(unrelated)
            self._own(ledger, unrelated, "999")
            commands: list[list[str]] = []

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                if command[0] == "squeue":
                    return self._completed()
                if command[0] == "sacct" and command[command.index("-j") + 1] == "9001":
                    return self._completed(stdout="9001|CANCELLED by 1000\n")
                if command[0] == "sacct":
                    return self._completed(stdout="123|RUNNING\n")
                if command == ["scancel", "-M", "alpha", "123"]:
                    return self._completed()
                return self._completed(returncode=9, stderr="unexpected command")

            result = agent_cleanup.run_cleanup(
                manifest_path=manifest.source_path,
                ledger_path=ledger_path,
                profile="cluster",
                parent_job_id="9001",
                cleanup_job_id="7001",
                retries=1,
                retry_delay=0,
                runner=runner,
            )

            self.assertEqual("cancel", result["action"])
            self.assertEqual([{"job_id": "123", "cluster": "alpha"}], result["cancelled"])
            self.assertIn(["scancel", "-M", "alpha", "123"], commands)
            self.assertFalse(any("999" in command for command in commands))
            self.assertEqual([], ledger.owned_jobs_for_cleanup(manifest))
            self.assertEqual(1, len(ledger.owned_jobs_for_cleanup(unrelated)))

    def test_leave_running_requires_manifest_policy_and_preserves_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            manifest = self._manifest(
                root,
                lifecycle='[lifecycle]\non_cancel = "leave-running"',
            )
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            self._own(ledger, manifest, "123")

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if command[0] == "squeue":
                    return self._completed()
                return self._completed(stdout="9001|CANCELLED\n")

            result = agent_cleanup.run_cleanup(
                manifest_path=manifest.source_path,
                ledger_path=ledger_path,
                profile="cluster",
                parent_job_id="9001",
                cleanup_job_id="7001",
                retries=1,
                retry_delay=0,
                runner=runner,
            )

            self.assertEqual("leave-running", result["action"])
            self.assertEqual("123", result["preserved"][0]["job_id"])
            self.assertEqual(1, len(ledger.owned_jobs_for_cleanup(manifest)))

    def test_naturally_terminal_job_is_reconciled_without_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            manifest = self._manifest(root)
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            self._own(ledger, manifest, "123")
            commands: list[list[str]] = []

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                if command[0] == "squeue":
                    return self._completed()
                job_id = command[command.index("-j") + 1]
                state = "CANCELLED" if job_id == "9001" else "COMPLETED"
                return self._completed(stdout=f"{job_id}|{state}\n")

            result = agent_cleanup.run_cleanup(
                manifest_path=manifest.source_path,
                ledger_path=ledger_path,
                profile="cluster",
                parent_job_id="9001",
                cleanup_job_id="7001",
                retries=1,
                retry_delay=0,
                runner=runner,
            )

            self.assertEqual("COMPLETED", result["reconciled"][0]["state"])
            self.assertFalse(any(command[0] == "scancel" for command in commands))

    def test_cleanup_rejects_wrong_job_identity_and_active_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            manifest = self._manifest(root)
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            with self.assertRaisesRegex(delegation.DelegationError, "registered"):
                agent_cleanup.run_cleanup(
                    manifest_path=manifest.source_path,
                    ledger_path=ledger_path,
                    profile="cluster",
                    parent_job_id="9001",
                    cleanup_job_id="7002",
                )

            def running_parent(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual("squeue", command[0])
                return self._completed(stdout="RUNNING\n")

            with self.assertRaisesRegex(ConfigError, "must be retried"):
                agent_cleanup.run_cleanup(
                    manifest_path=manifest.source_path,
                    ledger_path=ledger_path,
                    profile="cluster",
                    parent_job_id="9001",
                    cleanup_job_id="7001",
                    retries=1,
                    retry_delay=0,
                    runner=running_parent,
                )

    def test_timeout_policy_distinguishes_requeue_from_final_fallback(self) -> None:
        policy = delegation.LifecyclePolicy()
        for state in agent_cleanup.CONTINUING_STATES:
            with self.subTest(state=state):
                self.assertEqual("defer", agent_cleanup.cleanup_action(policy, state))
        for state in agent_cleanup.TERMINAL_STATES:
            with self.subTest(state=state):
                self.assertEqual("cancel", agent_cleanup.cleanup_action(policy, state))

        preserving = delegation.LifecyclePolicy(
            on_cancel="leave-running",
            on_timeout="leave-running",
            on_failure="leave-running",
            on_normal_exit_with_active_jobs="leave-running",
        )
        for state in agent_cleanup.TERMINAL_STATES:
            with self.subTest(preserving_state=state):
                self.assertEqual(
                    "leave-running", agent_cleanup.cleanup_action(preserving, state)
                )

    def test_failed_cleanup_retries_are_bounded_and_use_new_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            manifest = self._manifest(root)
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            self._own(ledger, manifest, "123")
            scancel_calls = 0

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                nonlocal scancel_calls
                if command[0] == "squeue":
                    return self._completed()
                if command[0] == "sacct":
                    job_id = command[command.index("-j") + 1]
                    state = "CANCELLED" if job_id == "9001" else "RUNNING"
                    return self._completed(stdout=f"{job_id}|{state}\n")
                scancel_calls += 1
                return self._completed(returncode=1, stderr="scheduler unavailable")

            arguments = {
                "manifest_path": manifest.source_path,
                "ledger_path": ledger_path,
                "profile": "cluster",
                "parent_job_id": "9001",
                "cleanup_job_id": "7001",
                "retries": 1,
                "retry_delay": 0,
                "runner": runner,
            }
            results = [agent_cleanup.run_cleanup(**arguments) for _ in range(4)]

            self.assertEqual(delegation.CLEANUP_CANCEL_ATTEMPTS, scancel_calls)
            self.assertEqual(
                "scheduler unavailable", results[0]["failures"][0]["error"]
            )
            self.assertIn(
                "operator reconciliation", results[-1]["failures"][0]["error"]
            )

    def test_failed_timeout_requeue_cancels_even_if_generic_failures_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "ledger.sqlite3"
            manifest = self._manifest(
                root,
                lifecycle='[lifecycle]\non_failure = "leave-running"',
            )
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            ledger.record_cleanup_job(manifest, job_id="7001")
            self._own(ledger, manifest, "123")
            ledger.begin_draining(manifest, reason="SIGUSR1")
            ledger.request_requeue(manifest)
            ledger.record_requeue_result(
                manifest,
                accepted=False,
                detail="timeout-requeue-failed: denied",
            )

            def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                if command[0] == "squeue":
                    return self._completed()
                if command[0] == "sacct":
                    job_id = command[command.index("-j") + 1]
                    state = "FAILED" if job_id == "9001" else "RUNNING"
                    return self._completed(stdout=f"{job_id}|{state}\n")
                return self._completed()

            result = agent_cleanup.run_cleanup(
                manifest_path=manifest.source_path,
                ledger_path=ledger_path,
                profile="cluster",
                parent_job_id="9001",
                cleanup_job_id="7001",
                retries=1,
                retry_delay=0,
                runner=runner,
            )

            self.assertEqual("cancel", result["action"])
            self.assertEqual("123", result["cancelled"][0]["job_id"])


if __name__ == "__main__":
    unittest.main()
