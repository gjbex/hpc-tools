from __future__ import annotations

import argparse
from dataclasses import replace
import textwrap

from test_cli_fixtures import *


class CliCoreTests(unittest.TestCase):
    def test_ssh_command_quotes_remote_command(self) -> None:
        profile = make_profile()

        argv = build_ssh_argv(profile, 'cd "$VSC_DATA/Projects/foo" && git status')

        self.assertEqual(argv[0:3], ["ssh", "-x", "gjb@genius"])
        self.assertEqual(
            argv[3],
            'bash -l -c \'cd "$VSC_DATA/Projects/foo" && git status\'',
        )

    def test_top_level_help_groups_commands_by_workflow(self) -> None:
        parser = build_parser(make_profile())

        help_text = parser.format_help()

        self.assertIn("commands:", help_text)
        self.assertNotIn("positional arguments:\n  <command>", help_text)
        expected_order = [
            "  Local setup and metadata:",
            "    paths",
            "    plugins",
            "    references",
            "    agent",
            "  Cluster inspection:",
            "    doctor",
            "    status",
            "    site-env",
            "    hardware",
            "    storage",
            "    quota",
            "    module-spider",
            "    slurm-limits",
            "  Remote workspace:",
            "    projects",
            "    repo",
            "    clone",
            "    run",
            "  Packaged assets:",
            "    write-probe",
            "    write-hardware-probe",
            "    install-probe",
            "    install-hardware-probe",
            "    write-container",
            "    install-container",
            "  Slurm accounting and safety:",
            "    quote",
            "    balance",
            "    statement",
            "  Slurm job lifecycle:",
            "    submit",
            "    jobs",
            "    job",
            "    queue",
            "    sacct",
            "    submissions",
            "  Workflow plugins:",
            "    benchmark",
            "    cxx",
            "    python",
            "    r",
        ]
        help_lines = help_text.splitlines()
        previous_index = -1
        for text in expected_order:
            index = _find_help_line(help_lines, text, previous_index + 1)
            self.assertGreater(index, previous_index)
            previous_index = index

    def test_doctor_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["doctor"])

        self.assertIs(args.handler, cmd_doctor)
        command = _doctor_command()
        self.assertIn("## identity", command)
        self.assertIn("hostname; whoami; pwd", command)
        self.assertIn("## slurm-tools", command)
        self.assertIn("command -v \"$tool\"", command)
        self.assertIn("sacctmgr", command)

    def test_main_uses_local_executor_with_targetless_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                textwrap.dedent(
                    """
                    default_profile = "local"

                    [profiles.local]
                    login_shell = ["bash", "-l", "-c"]

                    [profiles.local.capabilities]
                    version = 1
                    max_level = "cluster-discovery"
                    """
                ),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0)

            with mock.patch(
                "hpc_tools.execution.subprocess.run",
                return_value=completed,
            ) as run:
                result = main(
                    [
                        "--config",
                        str(config_path),
                        "--executor",
                        "local",
                        "doctor",
                    ]
                )

        self.assertEqual(result, 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ("bash", "-l", "-c"))
        self.assertNotIn("ssh", argv)

    def test_site_env_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["site-env"])

        self.assertIs(args.handler, cmd_site_env)
        command = _site_env_command()
        self.assertIn("## environment", command)
        self.assertIn("HOME|DATA|SCRATCH|WORK|PROJECT|TMP|SLURM", command)
        self.assertIn("## helper-tools", command)
        self.assertIn("beegfs-ctl", command)
        self.assertIn("module --version", command)

    def test_paths_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["paths"])

        self.assertIs(args.handler, cmd_paths)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = args.handler(args, None)

        self.assertEqual(result, 0)
        self.assertIn("container_generic_template:", stdout.getvalue())

    def test_plugins_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["plugins", "list"])

        self.assertEqual(args.command, "plugins")
        self.assertEqual(args.plugins_command, "list")

    def test_agent_audit_and_export_parsers(self) -> None:
        parser = build_parser()
        audit = parser.parse_args(
            ["agent", "audit", "--ledger", "/protected/delegations.sqlite3"]
        )
        export = parser.parse_args(
            [
                "agent",
                "export",
                "--ledger",
                "/protected/delegations.sqlite3",
                "--output",
                "audit.json",
            ]
        )

        self.assertIs(audit.handler, cmd_agent_audit)
        self.assertIs(export.handler, cmd_agent_export)

    def test_mcp_console_script_entry_point_is_available(self) -> None:
        self.assertTrue(callable(mcp_server.main))

    def test_benchmark_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["benchmark", "summarize", "results/"])

        self.assertEqual(args.command, "benchmark")
        self.assertEqual(args.benchmark_command, "summarize")
        self.assertIs(args.handler, benchmark_support.cmd_benchmark_summarize)

    def test_benchmark_main_json_is_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.csv"
            path.write_text("seconds\n10\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["--json", "benchmark", "summarize", str(path)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("summaries", payload)
        self.assertNotIn("stdout", payload)

    def test_paths_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["paths"])

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("config: /tmp/xdg/hpc-tools/config.toml", output)
        self.assertIn("profile_references: /tmp/xdg/hpc-tools/profiles/<profile>", output)
        self.assertIn(
            "submissions_database: /tmp/xdg/hpc-tools/submissions.sqlite3",
            output,
        )
        self.assertIn("reference_sets: /tmp/xdg/hpc-tools/reference-sets", output)
        self.assertIn("codex_skills: ~/.codex/skills/", output)
        self.assertIn("cuda_device_properties_template:", output)
        self.assertIn("cuda_device_properties_source:", output)
        self.assertIn("package_uninstall: pipx uninstall hpc-tools", output)
        self.assertIn("hpc-cluster-onboarding", output)
        self.assertIn("hpc-slurm-job-arrays", output)
        self.assertIn("hpc-slurm-benchmark", output)

    def test_executor_option_does_not_make_paths_require_config(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(
            "os.environ",
            {"XDG_CONFIG_HOME": "/tmp/xdg"},
            clear=True,
        ), contextlib.redirect_stdout(stdout):
            result = main(["--executor", "local", "paths"])

        self.assertEqual(result, 0)
        self.assertIn("config: /tmp/xdg/hpc-tools/config.toml", stdout.getvalue())

    def test_paths_main_json_wraps_text_output(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["paths", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["returncode"], 0)
        self.assertEqual(payload["stderr"], "")
        self.assertIn("config:", payload["stdout"])
        self.assertIn("paths", payload["argv"])

    def test_python_scan_main_json_stays_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "analysis.py").write_text("import mmh3\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["python", "scan", str(root), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("mmh3", payload["packages"])
        self.assertIn(str(root / "analysis.py"), payload["scanned_files"][0])
        self.assertNotIn("stdout", payload)

    def test_references_list_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["references", "list"])

        self.assertEqual(result, 0)
        self.assertIn("No reference sets.", stdout.getvalue())

    def test_optional_commands_visible_when_configured(self) -> None:
        parser = build_parser(make_profile())
        help_text = parser.format_help()

        self.assertIn("quota", help_text)
        self.assertIn("queue", help_text)
        self.assertIn("balance", help_text)
        self.assertIn("statement", help_text)
        self.assertIn("quote", help_text)
        self.assertIn("hardware", help_text)

    def test_optional_commands_hidden_when_unconfigured(self) -> None:
        parser = build_parser(
            make_profile(
                quota_command=None,
                queue_command=None,
                sam_balance_command=None,
                sam_statement_command=None,
                sam_quote_command=None,
                hardware_reference=None,
                hardware_url=None,
                slurm_reference=None,
                slurm_url=None,
                storage_reference=None,
                storage_url=None,
                status_url=None,
            ),
            policy_filter=True,
        )
        help_text = parser.format_help()

        self.assertNotIn("quota", help_text)
        self.assertNotIn("queue", help_text)
        self.assertNotIn("balance", help_text)
        self.assertNotIn("statement", help_text)
        self.assertNotIn("quote", help_text)
        self.assertNotIn("hardware           Show profile hardware", help_text)

    def test_hidden_optional_command_is_rejected_if_invoked(self) -> None:
        parser = build_parser(
            make_profile(quota_command=None),
            policy_filter=True,
        )

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args(["quota"])

    def test_hardware_context_renders_sources(self) -> None:
        profile = make_profile(
            hardware_url="https://example.org/hardware",
            slurm_url="https://example.org/slurm",
            storage_url="https://example.org/storage",
            status_url="https://status.example.org/",
        )

        self.assertEqual(
            render_hardware_context(profile, source_only=True),
            "hardware_url: https://example.org/hardware\n"
            "slurm_url: https://example.org/slurm\n"
            "storage_url: https://example.org/storage\n"
            "status_url: https://status.example.org/",
        )

    def test_policy_filtered_help_hides_denied_commands(self) -> None:
        profile = replace(
            make_profile(),
            capabilities=CapabilityPolicy(
                version=1,
                max_level=CapabilityLevel.PROFILE_CONTEXT,
                scopes=(),
                remote_roots=RemoteRootGrants(),
            ),
        )

        help_text = build_parser(profile, policy_filter=True).format_help()
        expanded = build_parser(
            profile,
            policy_filter=True,
            show_disallowed=True,
        ).format_help()

        self.assertIn("    capabilities", help_text)
        self.assertNotIn("    doctor", help_text)
        self.assertNotIn("    jobs", help_text)
        self.assertIn("    doctor", expanded)
        self.assertIn("disallowed: requires cluster-", expanded)

    def test_c2_help_exposes_only_test_only_submission_form(self) -> None:
        profile = replace(
            make_profile(),
            capabilities=CapabilityPolicy(
                version=1,
                max_level=CapabilityLevel.JOB_INSPECTION,
                scopes=("job.validate",),
                remote_roots=RemoteRootGrants(),
            ),
        )
        parser = build_parser(profile, policy_filter=True)
        action = next(
            item for item in parser._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        submit_help = next(
            item.help for item in action._choices_actions if item.dest == "submit"
        )

        self.assertIn("allowed form: submit JOBSCRIPT --test-only", submit_help)
        self.assertIn("actual submission is unavailable", submit_help)

    def test_profile_free_help_is_small_and_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ",
            {"XDG_CONFIG_HOME": directory},
            clear=True,
        ), contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        output = stdout.getvalue()
        self.assertIn("    paths", output)
        self.assertIn("    references", output)
        self.assertNotIn("    doctor", output)
        self.assertNotIn("    jobs", output)

    def test_explicit_and_default_profile_help_use_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = _write_policy_config(
                Path(directory) / "config.toml",
                level="profile-context",
            )
            for argv, environment in (
                (["--config", str(config_path), "--help"], {}),
                (["--help"], {"HPC_TOOLS_CONFIG": str(config_path)}),
            ):
                with self.subTest(argv=argv), mock.patch.dict(
                    "os.environ", environment, clear=True
                ), contextlib.redirect_stdout(io.StringIO()) as stdout, self.assertRaises(
                    SystemExit
                ) as raised:
                    main(argv)
                self.assertEqual(raised.exception.code, 0)
                self.assertNotIn("    doctor", stdout.getvalue())

    def test_capabilities_json_distinguishes_execution_and_display_grants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = _write_policy_config(
                Path(directory) / "config.toml",
                level="cluster-discovery",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main([
                    "--config", str(config_path),
                    "--capability", "profile-context",
                    "--json", "capabilities",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["profile"], "fixture")
        self.assertEqual(payload["execution_grants"]["max_level"], "cluster-discovery")
        self.assertEqual(payload["display_grants"]["max_level"], "profile-context")
        self.assertTrue(payload["display_filter_only"])

    def test_display_ceiling_does_not_reduce_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = _write_policy_config(
                Path(directory) / "config.toml",
                level="cluster-discovery",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main([
                    "--config", str(config_path),
                    "--capability", "profile-context",
                    "--executor", "local",
                    "--dry-run", "doctor",
                ])

        self.assertEqual(result, 0)
        self.assertIn("bash -l -c", stdout.getvalue())

    def test_hidden_direct_invocation_returns_structured_json_denial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = _write_policy_config(
                Path(directory) / "config.toml",
                level="profile-context",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main([
                    "--config", str(config_path),
                    "--show-disallowed",
                    "--json", "doctor",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 2)
        self.assertEqual(payload["code"], "capability.denied")
        self.assertEqual(payload["operation"], "cluster.doctor")
        self.assertEqual(payload["profile"], "fixture")

    def test_parser_errors_do_not_list_unfiltered_commands(self) -> None:
        parser = build_parser(make_profile(), policy_filter=False)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args(["not-a-command"])

        message = stderr.getvalue()
        self.assertIn("unknown or unavailable choice", message)
        self.assertNotIn("choose from", message)
        self.assertNotIn("'doctor'", message)


def _write_policy_config(path: Path, *, level: str) -> Path:
    path.write_text(
        textwrap.dedent(
            f"""
            default_profile = "fixture"

            [profiles.fixture]
            login_shell = ["bash", "-l", "-c"]

            [profiles.fixture.capabilities]
            version = 1
            max_level = "{level}"
            """
        ),
        encoding="utf-8",
    )
    return path
