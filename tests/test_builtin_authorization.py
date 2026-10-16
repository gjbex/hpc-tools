from __future__ import annotations

from dataclasses import replace
import unittest
from unittest import mock

from test_cli_fixtures import make_profile

from hpc_tools.authorization import CapabilityAuthorizationError
from hpc_tools.capabilities import (
    CapabilityLevel,
    CapabilityPolicy,
    RemoteRootGrants,
)
from hpc_tools.cli import build_parser
from hpc_tools.commands.core import cmd_doctor
from hpc_tools.commands.probes import cmd_write_probe
from hpc_tools.commands.references import cmd_references_create
from hpc_tools.commands.slurm import cmd_cancel, cmd_jobs, cmd_status, cmd_submit
from hpc_tools.commands.submissions import cmd_submissions_mark_collected
from hpc_tools.mcp.submit import hpc_quote_job


def _profile(
    level: CapabilityLevel,
    *,
    scopes: tuple[str, ...] = (),
) -> object:
    return replace(
        make_profile(),
        capabilities=CapabilityPolicy(
            version=1,
            max_level=level,
            scopes=scopes,
            remote_roots=RemoteRootGrants(),
        ),
    )


class BuiltinAuthorizationTests(unittest.TestCase):
    def test_denied_discovery_handler_never_reaches_executor(self) -> None:
        profile = _profile(CapabilityLevel.PROFILE_CONTEXT)
        args = build_parser(profile).parse_args(["doctor"])

        with mock.patch("hpc_tools.commands.core.run_command") as execute:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_doctor(args, profile)

        execute.assert_not_called()

    def test_c1_profile_cannot_query_jobs(self) -> None:
        profile = _profile(CapabilityLevel.CLUSTER_DISCOVERY)
        args = build_parser(profile).parse_args(["jobs"])

        with mock.patch("hpc_tools.commands.slurm.run_command") as execute:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_jobs(args, profile)

        execute.assert_not_called()

    def test_c2_profile_cannot_submit_or_log(self) -> None:
        profile = _profile(CapabilityLevel.JOB_INSPECTION)
        args = build_parser(profile).parse_args(["submit", "job.slurm"])

        with mock.patch("hpc_tools.commands.slurm.run_command_capture") as execute, \
             mock.patch("hpc_tools.commands.slurm._log_submission") as log:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_submit(args, profile)

        execute.assert_not_called()
        log.assert_not_called()

    def test_c2_profile_cannot_cancel_or_log(self) -> None:
        profile = _profile(CapabilityLevel.JOB_INSPECTION)
        args = build_parser(profile).parse_args(["cancel", "12345"])

        with mock.patch("hpc_tools.commands.slurm.run_command_capture") as execute, \
             mock.patch("hpc_tools.commands.slurm._log_cancellation_request") as log:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_cancel(args, profile)

        execute.assert_not_called()
        log.assert_not_called()

    def test_c2_job_validation_scope_allows_test_only_preview(self) -> None:
        profile = _profile(
            CapabilityLevel.JOB_INSPECTION,
            scopes=("job.validate",),
        )
        args = build_parser(profile).parse_args(
            ["--dry-run", "submit", "job.slurm", "--test-only"]
        )

        with mock.patch("hpc_tools.commands.slurm.run_command", return_value=0) as execute:
            self.assertEqual(cmd_submit(args, profile), 0)

        execute.assert_called_once()

    def test_denied_local_reference_write_has_no_mutation(self) -> None:
        profile = _profile(CapabilityLevel.PROFILE_CONTEXT)
        args = build_parser(profile).parse_args(["references", "create", "site"])

        with mock.patch("hpc_tools.commands.references.references.create_reference_set") as create:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_references_create(args, profile)

        create.assert_not_called()

    def test_local_write_dry_runs_have_no_mutation(self) -> None:
        reference_profile = _profile(
            CapabilityLevel.PROFILE_CONTEXT,
            scopes=("local-state.write",),
        )
        reference_args = build_parser(reference_profile).parse_args(
            ["--dry-run", "references", "create", "site"]
        )
        probe_args = build_parser(reference_profile).parse_args(
            ["--dry-run", "write-probe", "probe.slurm"]
        )
        submission_profile = _profile(
            CapabilityLevel.JOB_INSPECTION,
            scopes=("submission-record.write",),
        )
        submission_args = build_parser(submission_profile).parse_args(
            [
                "--dry-run",
                "submissions",
                "mark-collected",
                "run-1",
                "--path",
                "result.dat",
            ]
        )

        with mock.patch(
            "hpc_tools.commands.references.references.create_reference_set"
        ) as create, mock.patch(
            "hpc_tools.commands.probes.Path.write_text"
        ) as write, mock.patch(
            "hpc_tools.commands.submissions.submissions.read_events"
        ) as read, mock.patch(
            "hpc_tools.commands.submissions.submissions.append_event"
        ) as append:
            self.assertEqual(cmd_references_create(reference_args, reference_profile), 0)
            self.assertEqual(cmd_write_probe(probe_args, reference_profile), 0)
            self.assertEqual(
                cmd_submissions_mark_collected(submission_args, submission_profile),
                0,
            )

        create.assert_not_called()
        write.assert_not_called()
        read.assert_not_called()
        append.assert_not_called()

    def test_denied_status_does_not_fetch_http(self) -> None:
        profile = _profile(CapabilityLevel.PROFILE_CONTEXT)
        args = build_parser(profile).parse_args(["status"])

        with mock.patch("hpc_tools.commands.slurm._fetch_status_page") as fetch:
            with self.assertRaises(CapabilityAuthorizationError):
                cmd_status(args, profile)

        fetch.assert_not_called()

    def test_mcp_quote_is_denied_before_temporary_staging(self) -> None:
        profile = _profile(CapabilityLevel.CLUSTER_DISCOVERY)
        with mock.patch("hpc_tools.mcp.submit._resolve_profile", return_value=profile), \
             mock.patch("hpc_tools.mcp.submit._prepare_request") as prepare:
            with self.assertRaises(CapabilityAuthorizationError):
                hpc_quote_job("job.slurm", account="proj")

        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
