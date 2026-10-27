from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime

from test_mcp_fixtures import *

from hpc_tools import delegation
from hpc_tools.config import load_config, resolve_profile


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
        self.assertNotIn("structured_quote", result)

    def test_quote_job_parses_configured_structured_stdout_only_after_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'sam_quote_command = "sam-quote"',
                    'sam_quote_command = "sam-quote"\n'
                    'sam_quote_format = "hpc-tools-credit-quote-v1"',
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                returncode=0,
                stdout=(
                    '{"format_version":1,"maximum_cost":'
                    '{"value":2730,"scale":0,"unit":"credits"}}\n'
                ),
                stderr="site diagnostic\n",
            )

            with mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=completed
            ):
                result = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    directory="$VSC_DATA/Projects/demo",
                    jobscript="job.slurm",
                    account="proj",
                    cluster="wice",
                )

        self.assertEqual(
            {
                "format_version": 1,
                "maximum_cost": {"value": 2730, "scale": 0, "unit": "credits"},
            },
            result["structured_quote"],
        )
        self.assertEqual("site diagnostic\n", result["stderr"])
        self.assertNotIn("quoted_cost", result["quote_evidence"])

    def test_failed_or_dry_run_structured_quote_is_not_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'sam_quote_command = "sam-quote"',
                    'sam_quote_command = "sam-quote"\n'
                    'sam_quote_format = "hpc-tools-credit-quote-v1"',
                ),
                encoding="utf-8",
            )
            failed = mock.Mock(returncode=1, stdout="not JSON", stderr="denied")

            with mock.patch(
                "hpc_tools.mcp.common.run_command_capture", return_value=failed
            ):
                result = mcp_server.hpc_quote_job(
                    config=str(config_path),
                    jobscript="job.slurm",
                    account="proj",
                    dry_run=False,
                )
            preview = mcp_server.hpc_quote_job(
                config=str(config_path),
                jobscript="job.slurm",
                account="proj",
                dry_run=True,
            )

        self.assertNotIn("structured_quote", result)
        self.assertNotIn("structured_quote", preview)

    def test_successful_malformed_structured_quote_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'sam_quote_command = "sam-quote"',
                    'sam_quote_command = "sam-quote"\n'
                    'sam_quote_format = "hpc-tools-credit-quote-v1"',
                ),
                encoding="utf-8",
            )
            malformed = mock.Mock(returncode=0, stdout="2730\n", stderr="")

            with (
                mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=malformed,
                ),
                self.assertRaisesRegex(ValueError, "must be a JSON object"),
            ):
                mcp_server.hpc_quote_job(
                    config=str(config_path),
                    jobscript="job.slurm",
                    account="proj",
                )

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

    def test_restricted_submission_records_ownership_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'sam_quote_command = "sam-quote"',
                    'sam_quote_command = "sam-quote"\n'
                    'sam_quote_format = "hpc-tools-credit-quote-v1"',
                ),
                encoding="utf-8",
            )
            state_root = root / "state"
            work_root = root / "work"
            output_root = root / "output"
            input_root = root / "input"
            for path in (state_root, work_root, output_root, input_root):
                path.mkdir(mode=0o700)
            run_directory = work_root / "run"
            run_directory.mkdir()
            (run_directory / "job.slurm").write_text(
                "#!/bin/sh\necho delegated\n", encoding="utf-8"
            )
            container_path = root / "worker.sif"
            container_path.write_bytes(b"test image")
            apptainer_path = root / "apptainer"
            apptainer_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            apptainer_path.chmod(0o700)
            manifest_path = root / "delegation.toml"
            manifest_path.write_text(
                textwrap.dedent(
                    f"""
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
                    clusters = ["wice"]
                    partitions = ["batch"]
                    qos = []
                    reservations = []
                    containers = ["{container_path}"]
                    script_sha256 = []
                    roots = ["{work_root}"]
                    [filesystem]
                    state_root = "{state_root}"
                    work_root = "{work_root}"
                    output_root = "{output_root}"
                    input_roots = ["{input_root}"]
                    apptainer_path = "{apptainer_path}"
                    [per_job_limits]
                    nodes = 1
                    [budget]
                    max_submissions = 2
                    max_active_jobs = 2
                    [credit_budget]
                    unit = "credits"
                    scale = 0
                    maximum_total = 10000
                    maximum_per_job = 5000
                    quote_ttl_seconds = 300
                    """
                ).strip() + "\n",
                encoding="utf-8",
            )
            ledger_path = root / "delegations.sqlite3"
            runtime = delegation.load_runtime(
                manifest_path,
                profile="genius",
                ledger_path=ledger_path,
                parent_job_id="9001",
                profile_policy=resolve_profile(
                    load_config(str(config_path)), "genius"
                ).capabilities,
                config_path=config_path,
                config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                sam_quote_command="sam-quote",
                sam_quote_format="hpc-tools-credit-quote-v1",
            )
            quote_result = mock.Mock(
                returncode=0,
                stdout=(
                    '{"format_version":1,"maximum_cost":'
                    '{"value":2730,"scale":0,"unit":"credits"}}\n'
                ),
                stderr="",
            )
            validation_result = mock.Mock(returncode=0, stdout="sbatch: ok\n", stderr="")
            submission_result = mock.Mock(
                returncode=0,
                stdout="Submitted batch job 60351238 on cluster wice\n",
                stderr="",
            )
            arguments = {
                "config": str(config_path),
                "directory": str(run_directory),
                "jobscript": "job.slurm",
                "container": str(container_path),
                "idempotency_key": "request-1",
                "account": "proj",
                "cluster": "wice",
                "partition": "batch",
                "nodes": "1",
            }
            with delegation.delegation_scope(runtime):
                malformed_quote_result = mock.Mock(
                    returncode=0,
                    stdout="not structured JSON\n",
                    stderr="private helper diagnostic\n",
                )
                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=malformed_quote_result,
                ):
                    malformed = mcp_server.hpc_quote_job(**arguments)
                self.assertFalse(malformed["allowed"])
                self.assertEqual("quote", malformed["stage"])
                self.assertEqual("quote.format", malformed["denial"]["code"])
                self.assertNotIn("private helper diagnostic", str(malformed))
                self.assertNotIn(str(runtime.ledger_path), str(malformed))

                failed_quote_result = mock.Mock(
                    returncode=7,
                    stdout="private quote output\n",
                    stderr="private quote diagnostic\n",
                )
                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=failed_quote_result,
                ):
                    failed_quote = mcp_server.hpc_quote_job(**arguments)
                self.assertFalse(failed_quote["allowed"])
                self.assertEqual("quote", failed_quote["stage"])
                self.assertEqual("quote.failed", failed_quote["denial"]["code"])
                self.assertNotIn("command", failed_quote)
                self.assertNotIn("private quote", str(failed_quote))

                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=quote_result,
                ):
                    quote = mcp_server.hpc_quote_job(**arguments)
                failed_validation_result = mock.Mock(
                    returncode=8,
                    stdout="private validation output\n",
                    stderr="private validation diagnostic\n",
                )
                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=failed_validation_result,
                ):
                    failed_validation = mcp_server.hpc_validate_job(
                        **(arguments | {"quote_evidence": quote["quote_evidence"]})
                    )
                self.assertFalse(failed_validation["allowed"])
                self.assertEqual("validation", failed_validation["stage"])
                self.assertEqual(
                    "validation.failed", failed_validation["denial"]["code"]
                )
                self.assertNotIn("command", failed_validation)
                self.assertNotIn("private validation", str(failed_validation))

                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    return_value=validation_result,
                ):
                    validation = mcp_server.hpc_validate_job(
                        **(arguments | {"quote_evidence": quote["quote_evidence"]})
                    )
                expired_at = datetime.fromisoformat(
                    quote["quote_evidence"]["expires_at"]
                )
                with (
                    mock.patch(
                        "hpc_tools.mcp.submit._utc_now",
                        return_value=expired_at,
                    ),
                    mock.patch(
                        "hpc_tools.delegation._utc_now",
                        return_value=expired_at,
                    ),
                    mock.patch(
                        "hpc_tools.mcp.submit.run_command_capture"
                    ) as expired_submit,
                ):
                    expired = mcp_server.hpc_submit_job(
                        **(
                            arguments
                            | {
                                "quote_evidence": quote["quote_evidence"],
                                "validation_evidence": validation[
                                    "validation_evidence"
                                ],
                                "dry_run": False,
                            }
                        )
                    )
                self.assertFalse(expired["allowed"])
                self.assertEqual("submission", expired["stage"])
                self.assertEqual("quote.expired", expired["denial"]["code"])
                self.assertNotIn(str(runtime.ledger_path), str(expired))
                self.assertNotIn("sbatch", str(expired))
                expired_submit.assert_not_called()
                for code in (
                    delegation.SubmissionDenialCode.PER_JOB_CREDIT,
                    delegation.SubmissionDenialCode.TOTAL_CREDITS,
                    delegation.SubmissionDenialCode.SUBMISSION_COUNT,
                    delegation.SubmissionDenialCode.ACTIVE_JOBS,
                    delegation.SubmissionDenialCode.RESOURCES,
                ):
                    with self.subTest(denial_code=code.value), mock.patch(
                        "hpc_tools.mcp.submit.delegation.DelegationLedger"
                    ) as denied_ledger, mock.patch(
                        "hpc_tools.mcp.submit.run_command_capture"
                    ) as denied_submit:
                        denied_ledger.return_value.reserve_submission.side_effect = (
                            delegation.SubmissionDenied(
                                code,
                                "submission denied by the delegated budget",
                                resource=(
                                    "nodes"
                                    if code
                                    is delegation.SubmissionDenialCode.RESOURCES
                                    else None
                                ),
                            )
                        )
                        denied = mcp_server.hpc_submit_job(
                            **(
                                arguments
                                | {
                                    "quote_evidence": quote["quote_evidence"],
                                    "validation_evidence": validation[
                                        "validation_evidence"
                                    ],
                                    "dry_run": False,
                                }
                            )
                        )
                    self.assertFalse(denied["allowed"])
                    self.assertEqual(code.value, denied["denial"]["code"])
                    self.assertNotIn(str(runtime.ledger_path), str(denied))
                    self.assertNotIn("sbatch", str(denied))
                    denied_submit.assert_not_called()
                with mock.patch(
                    "hpc_tools.mcp.submit.run_command_capture",
                    return_value=submission_result,
                ) as submit, mock.patch(
                    "hpc_tools.mcp.submit.submissions.append_event",
                    side_effect=OSError("history unavailable"),
                ):
                    submit_arguments = arguments | {
                        "quote_evidence": quote["quote_evidence"],
                        "validation_evidence": validation["validation_evidence"],
                        "dry_run": False,
                    }
                    result = mcp_server.hpc_submit_job(**submit_arguments)
                    with mock.patch(
                        "hpc_tools.mcp.submit._utc_now",
                        return_value=datetime.fromisoformat(
                            quote["quote_evidence"]["expires_at"]
                        ),
                    ):
                        replay = mcp_server.hpc_submit_job(**submit_arguments)

                uncertain_arguments = arguments | {"idempotency_key": "request-2"}
                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    side_effect=[quote_result, validation_result],
                ):
                    uncertain_quote = mcp_server.hpc_quote_job(**uncertain_arguments)
                    uncertain_validation = mcp_server.hpc_validate_job(
                        **(
                            uncertain_arguments
                            | {"quote_evidence": uncertain_quote["quote_evidence"]}
                        )
                    )
                uncertain_scheduler_result = mock.Mock(
                    returncode=0,
                    stdout="Submitted batch job 60351239 on cluster wice\n",
                    stderr="",
                )
                with mock.patch(
                    "hpc_tools.mcp.submit.run_command_capture",
                    return_value=uncertain_scheduler_result,
                ) as uncertain_submit, mock.patch.object(
                    delegation.DelegationLedger,
                    "record_submission",
                    side_effect=delegation.DelegationError("audit unavailable"),
                ):
                    uncertain = mcp_server.hpc_submit_job(
                        **(
                            uncertain_arguments
                            | {
                                "quote_evidence": uncertain_quote["quote_evidence"],
                                "validation_evidence": uncertain_validation[
                                    "validation_evidence"
                                ],
                                "dry_run": False,
                            }
                        )
                    )

                exhausted_arguments = arguments | {"idempotency_key": "request-3"}
                with mock.patch(
                    "hpc_tools.mcp.common.run_command_capture",
                    side_effect=[quote_result, validation_result],
                ):
                    exhausted_quote = mcp_server.hpc_quote_job(
                        **exhausted_arguments
                    )
                    exhausted_validation = mcp_server.hpc_validate_job(
                        **(
                            exhausted_arguments
                            | {
                                "quote_evidence": exhausted_quote[
                                    "quote_evidence"
                                ]
                            }
                        )
                    )
                with mock.patch(
                    "hpc_tools.mcp.submit.run_command_capture"
                ) as exhausted_submit:
                    exhausted = mcp_server.hpc_submit_job(
                        **(
                            exhausted_arguments
                            | {
                                "quote_evidence": exhausted_quote["quote_evidence"],
                                "validation_evidence": exhausted_validation[
                                    "validation_evidence"
                                ],
                                "dry_run": False,
                            }
                        )
                    )
                self.assertFalse(exhausted["allowed"])
                self.assertEqual(
                    "budget.submission_count", exhausted["denial"]["code"]
                )
                exhausted_submit.assert_not_called()

            self.assertTrue(result["ledger_recorded"])
            self.assertEqual(
                {"value": 2730, "scale": 0, "unit": "credits"},
                quote["quote_evidence"]["quoted_cost"],
            )
            self.assertIn("expires_at", quote["quote_evidence"])
            self.assertEqual(
                quote["quote_evidence"]["evidence_token"],
                validation["validation_evidence"]["quote_evidence_token"],
            )
            self.assertFalse(result["logged"])
            self.assertEqual("history unavailable", result["database_error"])
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["executed"])
            submit.assert_called_once()
            uncertain_submit.assert_called_once()
            ledger = delegation.DelegationLedger(ledger_path)
            self.assertTrue(ledger.owns_job("delegate-1", "60351238", "wice"))
            with closing(sqlite3.connect(ledger_path)) as connection:
                recorded_credit = connection.execute(
                    """SELECT quoted_cost_value,quoted_cost_scale,
                              quoted_cost_unit,quote_evidence_token
                       FROM submission_operations
                       WHERE delegation_id='delegate-1'
                         AND idempotency_key='request-1'"""
                ).fetchone()
            self.assertEqual(
                (
                    2730,
                    0,
                    "credits",
                    quote["quote_evidence"]["evidence_token"],
                ),
                recorded_credit,
            )
            self.assertTrue(uncertain["ledger_recorded"])
            self.assertEqual("uncertain", uncertain["ledger_status"])
            self.assertEqual("audit unavailable", uncertain["ledger_error"])
            self.assertIsNone(uncertain["ledger_recovery_error"])
            self.assertEqual("60351239", uncertain["job_id"])
            self.assertTrue(ledger.owns_job("delegate-1", "60351239", "wice"))
