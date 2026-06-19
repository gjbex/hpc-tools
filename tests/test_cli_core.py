from __future__ import annotations

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
        self.assertIn("reference_sets: /tmp/xdg/hpc-tools/reference-sets", output)
        self.assertIn("codex_skills: ~/.codex/skills/", output)
        self.assertIn("cuda_device_properties_template:", output)
        self.assertIn("cuda_device_properties_source:", output)
        self.assertIn("package_uninstall: pipx uninstall hpc-tools", output)
        self.assertIn("hpc-cluster-onboarding", output)
        self.assertIn("hpc-slurm-job-arrays", output)
        self.assertIn("hpc-slurm-benchmark", output)

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
            )
        )
        help_text = parser.format_help()

        self.assertNotIn("quota", help_text)
        self.assertNotIn("queue", help_text)
        self.assertNotIn("balance", help_text)
        self.assertNotIn("statement", help_text)
        self.assertNotIn("quote", help_text)
        self.assertNotIn("hardware           Show profile hardware", help_text)

    def test_hidden_optional_command_is_rejected_if_invoked(self) -> None:
        parser = build_parser(make_profile(quota_command=None))

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
