from __future__ import annotations

import json
import sqlite3
import stat
import tempfile
import textwrap
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hpc_tools import agent_audit, delegation, submissions
from hpc_tools.config import ConfigError
from hpc_tools.credit_quotes import CreditAmount


class AgentAuditTests(unittest.TestCase):
    def _manifest(
        self,
        root: Path,
        *,
        credit: bool = False,
    ) -> delegation.DelegationManifest:
        path = root / "delegation.toml"
        path.write_text(
            textwrap.dedent(
                """
                format_version = 4
                id = "delegate-1"
                issuer = "operator"
                profile = "cluster"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [network]
                mode = "model-only"

                [allowed]
                accounts = ["project"]
                clusters = ["alpha"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = ["/images/worker.sif"]
                script_sha256 = []
                roots = ["/work"]

                [per_job_limits]
                nodes = 1

                [budget]
                max_submissions = 2
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        if credit:
            path.write_text(
                path.read_text(encoding="utf-8")
                + textwrap.dedent(
                    """

                    [credit_budget]
                    unit = "credits"
                    scale = 0
                    maximum_total = 10000
                    maximum_per_job = 5000
                    quote_ttl_seconds = 300
                    """
                ),
                encoding="utf-8",
            )
        return delegation.load_manifest(path, expected_profile="cluster")

    def test_report_joins_ledger_artifacts_outputs_and_submission_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._manifest(root)
            ledger_path = root / "delegations.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            artifacts = root / "state" / "agent-attempts" / "generation-1"
            artifacts.mkdir(parents=True)
            provenance = artifacts / "provenance.json"
            event_log = artifacts / "codex-events.jsonl"
            diagnostic_log = artifacts / "codex-stderr.log"
            for path, contents in (
                (provenance, "{}\n"),
                (event_log, '{"type":"thread.started"}\n'),
                (diagnostic_log, "diagnostic\n"),
            ):
                path.write_text(contents, encoding="utf-8")
                path.chmod(0o600)
            ledger.record_controller_artifacts(
                manifest,
                generation=1,
                artifact_directory=str(artifacts),
                provenance_path=str(provenance),
                event_log=str(event_log),
                diagnostic_log=str(diagnostic_log),
                manifest_materialization={
                    "mode": "template",
                    "template": {
                        "source_path": str(root / "delegation-template.toml"),
                        "format_version": 1,
                        "sha256": "a" * 64,
                    },
                    "manifest": {
                        "source_path": str(manifest.source_path),
                        "sha256": manifest.digest,
                    },
                },
            )
            shape = {
                "profile": "cluster",
                "jobscript": "job.slurm",
                "directory": "/work",
                "overrides": {
                    "account": "project",
                    "cluster": "alpha",
                    "partition": "batch",
                    "nodes": "1",
                },
                "shape_token": "token",
            }
            ledger.reserve_submission(
                manifest, idempotency_key="request-1", shape=shape
            )
            output = root / "output" / "request-1"
            output.mkdir(parents=True)
            (output / ".hpc-tools-status.json").write_text(
                '{"exit_code":0,"complete":true}\n', encoding="utf-8"
            )
            ledger.record_submission(
                manifest,
                idempotency_key="request-1",
                job_id="12345",
                cluster="alpha",
                output_directory=str(output),
            )
            submissions_path = root / "submissions.sqlite3"
            submissions.append_event(
                submissions.submitted_event(
                    profile="cluster",
                    job_id="12345",
                    cluster="alpha",
                    remote_directory="/state/jobs/request-1",
                    jobscript="job.slurm",
                    submit_command="sbatch job.slurm",
                    overrides={"account": "project"},
                ),
                path=submissions_path,
            )

            report = agent_audit.build_report(
                ledger_path, submissions_database=submissions_path
            )

            self.assertEqual(1, len(report["delegations"]))
            item = report["delegations"][0]
            self.assertEqual(4, report["format_version"])
            self.assertEqual("model-only", item["network_mode"])
            self.assertEqual(
                {
                    "mode": "model-only",
                    "web_search": "disabled",
                    "command_network_access": False,
                },
                item["manifest"]["network"],
            )
            self.assertEqual(
                str(artifacts),
                item["controller_attempts"][0]["artifacts"]["artifact_directory"],
            )
            materialization = item["controller_attempts"][0]["artifacts"][
                "manifest_materialization"
            ]
            self.assertEqual("a" * 64, materialization["template"]["sha256"])
            self.assertEqual(manifest.digest, materialization["manifest"]["sha256"])
            operation = item["submission_operations"][0]
            self.assertEqual(str(output), operation["output_directory"])
            self.assertEqual(
                {"exit_code": 0, "complete": True}, operation["output"]["status"]
            )
            self.assertEqual("submitted", operation["submission_events"][0]["event"])
            self.assertIn("audit_events:", agent_audit.format_report(report))
            self.assertIn(
                "network_mode: model-only", agent_audit.format_report(report)
            )
            self.assertIn(
                f"manifest_template_sha256={'a' * 64}",
                agent_audit.format_report(report),
            )
            self.assertEqual(
                "model-only",
                item["audit_events"][0]["detail"]["network"]["mode"],
            )

    def test_report_exposes_quote_maxima_without_mutating_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._manifest(root, credit=True)
            ledger_path = root / "delegations.sqlite3"
            ledger = delegation.DelegationLedger(ledger_path)
            ledger.register(manifest)
            shape = {
                "profile": "cluster",
                "jobscript": "job.slurm",
                "directory": "/work",
                "overrides": {
                    "account": "project",
                    "cluster": "alpha",
                    "partition": "batch",
                    "nodes": "1",
                },
                "shape_token": "token",
            }

            def quote(value: int, token: str) -> delegation.QuotedCreditReservation:
                return delegation.QuotedCreditReservation(
                    cost=CreditAmount(value=value, scale=0, unit="credits"),
                    evidence_token=token * 64,
                    expires_at=datetime(2098, 1, 1, tzinfo=UTC),
                )

            ledger.reserve_submission(
                manifest,
                idempotency_key="consumed",
                shape=shape,
                quoted_credit=quote(3000, "a"),
            )
            ledger.reserve_submission(
                manifest,
                idempotency_key="released",
                shape=shape,
                quoted_credit=quote(2000, "b"),
            )
            ledger.release_reservation(
                manifest,
                idempotency_key="released",
                reason="definite failure",
            )
            before = ledger_path.read_bytes()

            report = agent_audit.build_report(
                ledger_path,
                submissions_database=root / "missing-submissions.sqlite3",
            )

            self.assertEqual(4, report["format_version"])
            item = report["delegations"][0]
            self.assertEqual(
                {"value": 3000, "scale": 0, "unit": "credits"},
                item["quoted_credit"]["consumed_quoted_maximum"],
            )
            self.assertEqual(
                {"value": 2000, "scale": 0, "unit": "credits"},
                item["quoted_credit"]["released_quoted_maximum"],
            )
            self.assertEqual(
                {"value": 7000, "scale": 0, "unit": "credits"},
                item["quoted_credit"]["remaining_quoted_maximum"],
            )
            self.assertEqual(
                "a" * 64,
                item["submission_operations"][0]["quote"]["evidence_token"],
            )
            rendered = agent_audit.format_report(report)
            self.assertIn("quoted_maximum=3000e-0 credits", rendered)
            self.assertIn("remaining_quoted_maximum: 7000e-0 credits", rendered)
            self.assertEqual(before, ledger_path.read_bytes())

    def test_export_is_private_and_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            report = {"delegations": [], "format_version": 1}
            written = agent_audit.write_report(report, output)
            self.assertEqual(output, written)
            self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))
            self.assertEqual(report, json.loads(output.read_text(encoding="utf-8")))
            with self.assertRaisesRegex(ConfigError, "already exists"):
                agent_audit.write_report(report, output)
            agent_audit.write_report(report | {"updated": True}, output, force=True)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["updated"])

    def test_export_refuses_symlink_even_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("unchanged\n", encoding="utf-8")
            output = root / "audit.json"
            output.symlink_to(target)

            with self.assertRaisesRegex(ConfigError, "regular file"):
                agent_audit.write_report(
                    {"delegations": [], "format_version": 1}, output, force=True
                )

            self.assertEqual("unchanged\n", target.read_text(encoding="utf-8"))

    def test_output_summary_does_not_follow_status_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            secret = root / "secret.json"
            secret.write_text('{"secret":"must-not-be-exported"}\n', encoding="utf-8")
            (output / ".hpc-tools-status.json").symlink_to(secret)

            summary = agent_audit._output_summary(str(output))

            self.assertIsNone(summary["status"])

    def test_report_rejects_an_unknown_ledger_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.sqlite3"
            with closing(sqlite3.connect(ledger)) as database:
                database.execute("PRAGMA user_version=999")
                database.commit()
            ledger.chmod(0o600)
            with self.assertRaisesRegex(ConfigError, "schema version"):
                agent_audit.build_report(
                    ledger, submissions_database=Path(directory) / "missing.sqlite3"
                )


if __name__ == "__main__":
    unittest.main()
