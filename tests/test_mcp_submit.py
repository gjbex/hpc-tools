from __future__ import annotations

from test_mcp_fixtures import *


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_quote_job_returns_shape_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed):
                result = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                    time="00:30:00",
                )

        evidence = result["quote_evidence"]
        self.assertTrue(evidence["ok"])
        self.assertFalse(evidence["dry_run"])
        self.assertEqual(evidence["account"], "proj")
        self.assertEqual(evidence["shape_token"], result["resource_shape"]["shape_token"])
        self.assertIn("sam-quote sbatch", result["command"])
        self.assertIn("--account proj", result["command"])

    def test_validate_job_returns_shape_bound_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="sbatch: Job 1 to start later\n", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed):
                result = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )

        evidence = result["validation_evidence"]
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["shape_token"], result["resource_shape"]["shape_token"])
        self.assertIn("sbatch --test-only", result["command"])

    def test_submit_job_rejects_stale_quote_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="batch",
                )

            with self.assertRaisesRegex(ValueError, "stale"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    partition="other",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

    def test_submit_job_refuses_missing_account_quote_validation_or_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with self.assertRaisesRegex(ValueError, "requires an account"):
                mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                )

            with mock.patch("hpc_tools.mcp.common.run_command_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with self.assertRaisesRegex(ValueError, "expected quote evidence"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence={},
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

            with self.assertRaisesRegex(ValueError, "expected validation evidence"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence={},
                    confirm=True,
                    dry_run=False,
                )

            with mock.patch("hpc_tools.mcp.submit.run_command_capture") as remote:
                preview = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    dry_run=False,
                    confirm=False,
                )

        self.assertTrue(preview["confirm_required"])
        self.assertFalse(preview["executed"])
        remote.assert_not_called()

    def test_submit_job_rejects_dry_run_or_tampered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            dry_quote = mcp_server.hpc_quote_job(
                config=str(config_path),
                directory="$VSC_DATA/Projects/demo",
                jobscript="job.slurm",
                account="proj",
                cluster="wice",
                dry_run=True,
            )
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")
            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=validate_completed):
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with self.assertRaisesRegex(ValueError, "dry run"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=dry_quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

            tampered_quote = dict(validation["validation_evidence"]) | {"type": "quote"}
            with self.assertRaisesRegex(ValueError, "token is invalid"):
                mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=tampered_quote,
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

    def test_submit_job_requires_confirm_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

            with mock.patch("hpc_tools.mcp.submit.run_command_capture") as remote:
                preview = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                )

        self.assertTrue(preview["confirm_required"])
        self.assertFalse(preview["executed"])
        self.assertIn("sbatch --account proj --clusters wice job.slurm", preview["command"])
        remote.assert_not_called()

    def test_submit_job_executes_and_logs_with_matching_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            quote_completed = mock.Mock(returncode=0, stdout="2730\n", stderr="")
            validate_completed = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")
            submit_completed = mock.Mock(
                returncode=0,
                stdout="Submitted batch job 60351238 on cluster wice\n",
                stderr="",
            )

            with mock.patch("hpc_tools.mcp.common.run_command_capture", side_effect=[quote_completed, validate_completed]):
                quote = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                )
                validation = mcp_server.hpc_validate_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                )

            with mock.patch("hpc_tools.mcp.submit.run_command_capture", return_value=submit_completed), \
                    mock.patch("hpc_tools.mcp.submit.submissions.append_event") as append_event:
                result = mcp_server.hpc_submit_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                    array="4",
                    quote_evidence=quote["quote_evidence"],
                    validation_evidence=validation["validation_evidence"],
                    confirm=True,
                    dry_run=False,
                )

        self.assertTrue(result["executed"])
        self.assertTrue(result["logged"])
        self.assertEqual(result["submission_event"]["job_id"], "60351238")
        append_event.assert_called_once()

