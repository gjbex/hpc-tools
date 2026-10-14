from __future__ import annotations

import argparse
from dataclasses import replace

from test_cli_fixtures import *


class CliCoreTests(unittest.TestCase):
    def test_policy_filtered_plugin_group_hides_denied_leaves(self) -> None:
        profile = replace(
            make_profile(),
            capabilities=CapabilityPolicy(
                version=1,
                max_level=CapabilityLevel.PROFILE_CONTEXT,
                scopes=(),
                remote_roots=RemoteRootGrants(),
            ),
        )
        parser = build_parser(profile, policy_filter=True)
        root = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        python_parser = root.choices["python"]
        python_commands = next(
            action for action in python_parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        self.assertEqual(set(python_commands.choices), {"scan", "inspect-deps"})

    def test_cxx_scan_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["cxx", "scan", "."])

        self.assertEqual(args.command, "cxx")
        self.assertEqual(args.cxx_command, "scan")

    def test_cxx_fetchcontent_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "cxx",
                "fetchcontent",
                "CLI11",
                "--project-option-prefix",
                "DEMO",
                "--default-off",
            ]
        )

        self.assertEqual(args.command, "cxx")
        self.assertEqual(args.cxx_command, "fetchcontent")
        self.assertEqual(args.package, "CLI11")
        self.assertEqual(args.project_option_prefix, "DEMO")
        self.assertTrue(args.default_off)

    def test_r_scan_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["r", "scan", "Script/Main.R"])

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "scan")

    def test_r_check_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "check",
                "Script/Main.R",
                "--module",
                "R/4.4.2",
                "--cran-bundle",
                "R-bundle-CRAN/2024.11",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "check")
        self.assertEqual(args.module, "R/4.4.2")
        self.assertEqual(args.cran_bundle, "R-bundle-CRAN/2024.11")

    def test_r_plan_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "plan-install",
                "Script/Main.R",
                "--module",
                "R/4.4.2",
                "--partition",
                "batch_icelake",
                "--output",
                "install.slurm",
                "--archive-package",
                "PrevMap=https://example.org/PrevMap.tar.gz",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "plan-install")
        self.assertEqual(args.partition, "batch_icelake")
        self.assertEqual(str(args.output), "install.slurm")

    def test_r_verify_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "verify-install",
                "--job-output",
                "/tmp/job.out",
                "--package",
                "PrevMap",
                "--package",
                "INLA",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "verify-install")
        self.assertEqual(args.packages, ["PrevMap", "INLA"])

    def test_r_submit_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "submit-install",
                "install.slurm",
                "--directory",
                "$VSC_DATA/Projects/demo",
                "--account",
                "proj123",
                "--cluster",
                "wice",
                "--partition",
                "batch_icelake",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "submit-install")
        self.assertEqual(str(args.jobscript), "install.slurm")
        self.assertEqual(args.account, "proj123")

    def test_submissions_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["submissions", "--database", "/tmp/submissions.sqlite3", "list"])

        self.assertEqual(args.command, "submissions")
        self.assertEqual(args.submissions_command, "list")
        self.assertEqual(str(args.database), "/tmp/submissions.sqlite3")

    def test_references_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["references", "list"])

        self.assertEqual(args.command, "references")
        self.assertEqual(args.references_command, "list")
