from __future__ import annotations

from test_mcp_fixtures import *
import tomllib
from hpc_tools.config import load_config, resolve_profile
from hpc_tools.operation_registry import OPERATION_REGISTRY, OperationSurface


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_mcp_tool_and_resource_registries_are_stable(self) -> None:
        self.assertEqual(
            mcp_server.TOOL_NAMES,
            tuple(OPERATION_REGISTRY.bindings(OperationSurface.MCP_TOOL)),
        )
        self.assertEqual(
            mcp_server.RESOURCE_URIS,
            tuple(OPERATION_REGISTRY.bindings(OperationSurface.MCP_RESOURCE)),
        )
        self.assertEqual(mcp_server.RESOURCE_TEMPLATES, ())

    def test_slurm_job_registry_is_a_narrow_fixed_surface(self) -> None:
        self.assertEqual(
            mcp_server.tool_names_for_preset("slurm-job"),
            (
                "hpc_jobs",
                "hpc_job",
                "hpc_job_accounting",
                "hpc_cancel_job",
                "hpc_quote_job",
                "hpc_validate_job",
                "hpc_submit_job",
            ),
        )
        self.assertEqual(
            mcp_server.resource_uris_for_preset("slurm-job"),
            (
                "hpc://runtime",
                "hpc://cluster/hardware",
                "hpc://cluster/slurm",
                "hpc://cluster/storage",
            ),
        )
        self.assertEqual(mcp_server.resource_templates_for_preset("slurm-job"), ())
        restricted = set(mcp_server.tool_names_for_preset("slurm-job"))
        forbidden_tools = set(mcp_server.TOOL_NAMES) - restricted
        self.assertTrue(
            {
                "hpc_profiles_list", "hpc_paths", "hpc_profile_show",
                "hpc_slurm_limits", "hpc_storage_inspect", "hpc_site_env",
                "hpc_submissions_list", "hpc_references_create",
                "hpc_install_probe", "hpc_install_container",
                "hpc_files_list", "hpc_files_read", "hpc_files_mkdir",
                "hpc_files_upload", "hpc_files_download", "hpc_files_copy",
                "hpc_files_remove", "hpc_repo_clone",
            }.issubset(forbidden_tools)
        )
        self.assertTrue(restricted.isdisjoint(forbidden_tools))
        restricted_resources = set(
            mcp_server.resource_uris_for_preset("slurm-job")
        )
        self.assertTrue(restricted_resources.issubset(set(mcp_server.RESOURCE_URIS)))

    def test_unknown_mcp_preset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown MCP preset"):
            mcp_server.resolve_preset("unrestricted")

    def test_named_preset_candidates_follow_capability_levels(self) -> None:
        context = set(mcp_server.tool_names_for_preset("context"))
        discovery = set(mcp_server.tool_names_for_preset("discovery"))
        inspection = set(mcp_server.tool_names_for_preset("job-inspect"))
        lifecycle = set(mcp_server.tool_names_for_preset("job-lifecycle"))

        self.assertLess(context, discovery)
        self.assertLess(discovery, inspection)
        self.assertLess(inspection, lifecycle)
        self.assertNotIn("hpc_status", context)
        self.assertIn("hpc_status", discovery)
        self.assertNotIn("hpc_jobs", discovery)
        self.assertIn("hpc_jobs", inspection)
        self.assertNotIn("hpc_cancel_job", inspection)
        self.assertIn("hpc_cancel_job", lifecycle)
        self.assertIn("hpc_submit_job", lifecycle)

    def test_mcp_tool_schemas_are_stable_for_guarded_submission(self) -> None:
        expected = {
            "hpc_cancel_job": [
                "jobid",
                "profile",
                "config",
                "cluster",
                "reason",
                "database",
                "idempotency_key",
                "dry_run",
                "confirm",
            ],
            "hpc_quote_job": [
                "jobscript",
                "directory",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "container",
                "idempotency_key",
                "profile",
                "config",
                "dry_run",
            ],
            "hpc_validate_job": [
                "jobscript",
                "directory",
                "quote_evidence",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "container",
                "idempotency_key",
                "profile",
                "config",
                "dry_run",
            ],
            "hpc_submit_job": [
                "jobscript",
                "directory",
                "quote_evidence",
                "validation_evidence",
                "account",
                "array",
                "cluster",
                "dependency",
                "error",
                "export",
                "gpu_bind",
                "gpus",
                "gpus_per_node",
                "gpus_per_task",
                "gres",
                "job_name",
                "mem",
                "mem_per_cpu",
                "nodes",
                "ntasks",
                "ntasks_per_node",
                "output",
                "partition",
                "reservation",
                "time",
                "cpus_per_task",
                "container",
                "idempotency_key",
                "database",
                "profile",
                "config",
                "dry_run",
                "confirm",
            ],
        }

        for name, parameter_names in expected.items():
            with self.subTest(name=name):
                signature = inspect.signature(getattr(mcp_server, name))
                self.assertEqual(list(signature.parameters), parameter_names)
                self.assertNotIn("overrides", signature.parameters)

    def test_guarded_tools_include_evidence_gated_slurm_submit_workflow(self) -> None:
        names = set(mcp_server.TOOL_NAMES)

        self.assertIn("hpc_profiles_list", names)
        self.assertIn("hpc_paths", names)
        self.assertIn("hpc_status", names)
        self.assertIn("hpc_jobs", names)
        self.assertIn("hpc_cancel_job", names)
        self.assertIn("hpc_slurm_limits", names)
        self.assertIn("hpc_module_spider", names)
        self.assertIn("hpc_storage_inspect", names)
        self.assertIn("hpc_references_create", names)
        self.assertIn("hpc_submissions_close", names)
        self.assertIn("hpc_write_probe", names)
        self.assertIn("hpc_install_probe", names)
        self.assertIn("hpc_write_container", names)
        self.assertIn("hpc_install_container", names)
        self.assertIn("hpc_quote_job", names)
        self.assertIn("hpc_validate_job", names)
        self.assertIn("hpc_submit_job", names)

    def test_read_only_resources_are_listed_without_write_resources(self) -> None:
        uris = set(mcp_server.RESOURCE_URIS)
        templates = set(mcp_server.RESOURCE_TEMPLATES)

        self.assertIn("hpc://paths", uris)
        self.assertIn("hpc://config", uris)
        self.assertIn("hpc://submissions/active", uris)
        self.assertIn("hpc://cluster/hardware", uris)
        self.assertIn("hpc://reference-set", uris)
        self.assertEqual(templates, set())
        self.assertNotIn("hpc://submit", uris)
        self.assertNotIn("hpc://profiles/{profile}/install-probe", templates)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_fastmcp_server_lists_and_calls_tools_and_resources(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                self._write_reference_set(root, "baseline")

                with mock.patch.dict(
                    "os.environ",
                    {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                    clear=False,
                ):
                    server = mcp_server.create_server()
                    listed = await server.list_tools()
                    names = {tool.name for tool in listed}
                    selected = resolve_profile(load_config(str(config_path)), None)

                    self.assertEqual(
                        set(mcp_server.tool_names_for_preset("full", selected)),
                        names,
                    )
                    self.assertIn("hpc_submit_job", names)
                    self.assertNotIn("hpc_references_show", names)

                    submit = next(tool for tool in listed if tool.name == "hpc_submit_job")
                    self.assertNotIn("profile", submit.inputSchema["properties"])
                    self.assertNotIn("config", submit.inputSchema["properties"])
                    self.assertNotIn("database", submit.inputSchema["properties"])
                    self.assertIn("confirm", submit.inputSchema["properties"])

                    content, structured = await server.call_tool("hpc_paths", {})
                    self.assertEqual(len(content), 1)
                    self.assertIn("hardware_probe_template", content[0].text)
                    self.assertIn("hardware_probe_template", structured["result"])

                    listed_resources = await server.list_resources()
                    resource_uris = {str(resource.uri) for resource in listed_resources}
                    self.assertEqual(
                        set(mcp_server.resource_uris_for_preset("full", selected)),
                        resource_uris,
                    )
                    self.assertNotIn("hpc://reference-set", resource_uris)

                    listed_templates = await server.list_resource_templates()
                    template_uris = {template.uriTemplate for template in listed_templates}
                    self.assertEqual(set(mcp_server.RESOURCE_TEMPLATES), template_uris)

                    read = await server.read_resource("hpc://cluster/hardware")
                    self.assertEqual(read[0].content, "# hardware\n")

                    with self.assertRaises(Exception):
                        await server.read_resource("hpc://profiles/genius/hardware")
                    with self.assertRaises(Exception):
                        await server.read_resource("hpc://reference-sets/baseline")

        asyncio.run(exercise_server())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_profile_policy_filters_discovery_and_is_snapshotted(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                original = config_path.read_text(encoding="utf-8")
                config_path.write_text(
                    original
                    + textwrap.dedent(
                        """

                        [profiles.context_only]
                        hardware_reference = "{hardware}"
                        slurm_reference = "{slurm}"
                        storage_reference = "{storage}"

                        [profiles.context_only.capabilities]
                        version = 1
                        max_level = "profile-context"
                        scopes = []

                        [profiles.context_only.capabilities.remote_roots]
                        list = []
                        read = []
                        write = []
                        delete = []
                        install = []
                        """
                    ).format(
                        hardware=root / "hpc-tools" / "profiles" / "genius" / "hardware.md",
                        slurm=root / "hpc-tools" / "profiles" / "genius" / "slurm.md",
                        storage=root / "hpc-tools" / "profiles" / "genius" / "storage.md",
                    ).strip()
                    + "\n",
                    encoding="utf-8",
                )
                environment = {
                    "HPC_TOOLS_CONFIG": str(config_path),
                    "XDG_CONFIG_HOME": str(root),
                }
                with mock.patch.dict("os.environ", environment, clear=False):
                    lifecycle = mcp_server.create_server(
                        preset="job-lifecycle",
                        profile="genius",
                    )
                    context = mcp_server.create_server(
                        preset="full",
                        profile="context_only",
                    )

                    lifecycle_names = {tool.name for tool in await lifecycle.list_tools()}
                    context_names = {tool.name for tool in await context.list_tools()}
                    self.assertIn("hpc_submit_job", lifecycle_names)
                    self.assertIn("hpc_jobs", lifecycle_names)
                    self.assertNotIn("hpc_submit_job", context_names)
                    self.assertNotIn("hpc_jobs", context_names)
                    self.assertNotIn("hpc_profile_show", context_names)

                    config_resource = await lifecycle.read_resource("hpc://config")
                    selected_config = tomllib.loads(config_resource[0].content)
                    self.assertEqual(["genius"], list(selected_config["profiles"]))
                    self.assertNotIn("context_only", config_resource[0].content)

                    _, profiles = await context.call_tool("hpc_profiles_list", {})
                    self.assertEqual(
                        ["context_only"],
                        [item["name"] for item in profiles["result"]["profiles"]],
                    )
                    with self.assertRaises(Exception):
                        await context.call_tool("hpc_jobs", {"dry_run": True})
                    with self.assertRaises(Exception):
                        await context.read_resource("hpc://config")
                    self.assertEqual([], await context.list_resource_templates())
                    denied_output = root / "denied-probe.slurm"
                    with self.assertRaises(Exception):
                        await context.call_tool(
                            "hpc_write_probe",
                            {"output": str(denied_output), "confirm": True},
                        )
                    self.assertFalse(denied_output.exists())

                    config_path.write_text(
                        config_path.read_text(encoding="utf-8").replace(
                            'max_level = "profile-context"',
                            'max_level = "job-lifecycle"',
                        ),
                        encoding="utf-8",
                    )
                    self.assertNotIn(
                        "hpc_jobs",
                        {tool.name for tool in await context.list_tools()},
                    )
                    restarted = mcp_server.create_server(
                        preset="full",
                        profile="context_only",
                    )
                    restarted_names = {
                        tool.name for tool in await restarted.list_tools()
                    }
                    self.assertIn("hpc_jobs", restarted_names)
                    self.assertIn("hpc_cancel_job", restarted_names)
                    self.assertNotIn("hpc_quote_job", restarted_names)
                    self.assertNotIn("hpc_validate_job", restarted_names)
                    self.assertNotIn("hpc_submit_job", restarted_names)

                    _, old_profiles = await context.call_tool(
                        "hpc_profiles_list", {}
                    )
                    self.assertEqual(
                        "profile-context",
                        old_profiles["result"]["profiles"][0]["capabilities"]["max_level"],
                    )
                    runtime = await context.read_resource("hpc://runtime")
                    self.assertEqual(
                        "profile-context",
                        json.loads(runtime[0].content)["capabilities"]["max_level"],
                    )

        asyncio.run(exercise_server())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_bound_reference_visibility_is_limited_to_attached_set(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                self._write_reference_set(root, "baseline")
                self._write_reference_set(root, "other")
                config_path.write_text(
                    config_path.read_text(encoding="utf-8").replace(
                        'ssh_options = ["-x"]',
                        'ssh_options = ["-x"]\nreference_set = "baseline"',
                    ),
                    encoding="utf-8",
                )
                with mock.patch.dict(
                    "os.environ",
                    {
                        "HPC_TOOLS_CONFIG": str(config_path),
                        "XDG_CONFIG_HOME": str(root),
                    },
                    clear=False,
                ):
                    server = mcp_server.create_server(preset="context")
                    names = {tool.name for tool in await server.list_tools()}
                    self.assertIn("hpc_references_show", names)
                    _, listed = await server.call_tool("hpc_references_list", {})
                    self.assertEqual(
                        ["baseline"],
                        [item["name"] for item in listed["result"]["reference_sets"]],
                    )
                    with self.assertRaises(Exception):
                        await server.call_tool("hpc_references_show", {"name": "other"})
                    selected = await server.read_resource("hpc://reference-set")
                    self.assertIn('"name": "baseline"', selected[0].content)
                    with self.assertRaises(Exception):
                        await server.read_resource("hpc://reference-sets/other")

        asyncio.run(exercise_server())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_slurm_job_server_registers_only_bound_surface(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                manifest_path = self._write_delegation_manifest(root)

                with mock.patch.dict(
                    "os.environ",
                    {
                        "HPC_TOOLS_CONFIG": str(config_path),
                        "XDG_CONFIG_HOME": str(root),
                        "HPC_TOOLS_PARENT_JOB_ID": "9001",
                    },
                    clear=False,
                ):
                    server = mcp_server.create_server(
                        preset="slurm-job",
                        profile="genius",
                        delegation_manifest=str(manifest_path),
                        ledger=str(root / "ledger.sqlite3"),
                    )
                    tools = await server.list_tools()
                    names = {tool.name for tool in tools}
                    self.assertEqual(set(mcp_server.SLURM_JOB_TOOL_NAMES), names)

                    jobs = next(tool for tool in tools if tool.name == "hpc_jobs")
                    self.assertNotIn("profile", jobs.inputSchema["properties"])
                    self.assertNotIn("config", jobs.inputSchema["properties"])
                    submit_tool = next(
                        tool for tool in tools if tool.name == "hpc_submit_job"
                    )
                    quote_tool = next(
                        tool for tool in tools if tool.name == "hpc_quote_job"
                    )
                    validate_tool = next(
                        tool for tool in tools if tool.name == "hpc_validate_job"
                    )
                    cancel_tool = next(
                        tool for tool in tools if tool.name == "hpc_cancel_job"
                    )
                    for tool in (submit_tool, cancel_tool):
                        self.assertNotIn("database", tool.inputSchema["properties"])
                        self.assertNotIn("confirm", tool.inputSchema["properties"])
                    for tool in (quote_tool, validate_tool, submit_tool):
                        self.assertNotIn("output", tool.inputSchema["properties"])
                        self.assertNotIn("error", tool.inputSchema["properties"])
                        self.assertNotIn("export", tool.inputSchema["properties"])
                        self.assertIn("container", tool.inputSchema["properties"])
                        self.assertIn("idempotency_key", tool.inputSchema["properties"])

                    _, job_result = await server.call_tool(
                        "hpc_jobs",
                        {"dry_run": True},
                    )
                    self.assertEqual("genius", job_result["result"]["profile"])
                    self.assertTrue(job_result["result"]["dry_run"])

                    resources = await server.list_resources()
                    self.assertEqual(
                        set(mcp_server.SLURM_JOB_RESOURCE_URIS),
                        {str(resource.uri) for resource in resources},
                    )
                    self.assertEqual([], await server.list_resource_templates())

                    runtime = await server.read_resource("hpc://runtime")
                    runtime_data = json.loads(runtime[0].content)
                    self.assertEqual("slurm-job", runtime_data["preset"])
                    self.assertEqual("genius", runtime_data["profile"])
                    self.assertTrue(runtime_data["delegation"]["configured"])
                    self.assertEqual(
                        "cancel",
                        runtime_data["delegation"]["lifecycle"]["on_cancel"],
                    )
                    self.assertEqual(
                        "running",
                        runtime_data["delegation"]["controller"]["state"],
                    )

                    hardware = await server.read_resource("hpc://cluster/hardware")
                    self.assertEqual("# hardware\n", hardware[0].content)

        asyncio.run(exercise_server())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_slurm_job_controller_start_requires_c3(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            manifest_path = self._write_delegation_manifest(root)
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'max_level = "job-lifecycle"',
                    'max_level = "job-inspection"',
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_PARENT_JOB_ID": "9001"},
                clear=False,
            ), self.assertRaisesRegex(
                mcp_server.ConfigError,
                "agent.controller.start.*job-lifecycle",
            ):
                mcp_server.create_server(
                    preset="slurm-job",
                    profile="genius",
                    delegation_manifest=str(manifest_path),
                    ledger=str(root / "ledger.sqlite3"),
                    config=str(config_path),
                )

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_slurm_job_credit_start_requires_structured_quote_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            manifest_path = self._write_delegation_manifest(root)
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8")
                + textwrap.dedent(
                    """
                    [credit_budget]
                    unit = "credits"
                    scale = 0
                    maximum_total = 20000
                    quote_ttl_seconds = 300
                    """
                ),
                encoding="utf-8",
            )
            ledger_path = root / "ledger.sqlite3"
            arguments = {
                "preset": "slurm-job",
                "profile": "genius",
                "delegation_manifest": str(manifest_path),
                "ledger": str(ledger_path),
                "config": str(config_path),
            }
            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_PARENT_JOB_ID": "9001"},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    mcp_server.ConfigError, "sam_quote_format"
                ):
                    mcp_server.create_server(**arguments)
                self.assertFalse(ledger_path.exists())

                config_path.write_text(
                    config_path.read_text(encoding="utf-8").replace(
                        'sam_quote_command = "sam-quote"',
                        'sam_quote_command = "sam-quote"\n'
                        'sam_quote_format = "hpc-tools-credit-quote-v1"',
                    ),
                    encoding="utf-8",
                )
                server = mcp_server.create_server(**arguments)

            self.assertIsNotNone(server)
            self.assertTrue(ledger_path.exists())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_restarted_slurm_job_server_intersects_current_and_captured_policy(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = self._write_config(root)
                manifest_path = self._write_delegation_manifest(root)
                ledger_path = root / "ledger.sqlite3"
                with mock.patch.dict(
                    "os.environ",
                    {"HPC_TOOLS_PARENT_JOB_ID": "9001"},
                    clear=False,
                ):
                    initial = mcp_server.create_server(
                        preset="slurm-job",
                        profile="genius",
                        delegation_manifest=str(manifest_path),
                        ledger=str(ledger_path),
                        config=str(config_path),
                    )
                    self.assertIn(
                        "hpc_submit_job",
                        {tool.name for tool in await initial.list_tools()},
                    )
                    config_path.write_text(
                        config_path.read_text(encoding="utf-8").replace(
                            'max_level = "job-lifecycle"',
                            'max_level = "job-inspection"',
                        ),
                        encoding="utf-8",
                    )
                    restarted = mcp_server.create_server(
                        preset="slurm-job",
                        profile="genius",
                        delegation_manifest=str(manifest_path),
                        ledger=str(ledger_path),
                        config=str(config_path),
                    )

                    names = {tool.name for tool in await restarted.list_tools()}
                    self.assertIn("hpc_jobs", names)
                    self.assertIn("hpc_validate_job", names)
                    self.assertNotIn("hpc_cancel_job", names)
                    self.assertNotIn("hpc_submit_job", names)
                    self.assertTrue(names.issubset(set(mcp_server.SLURM_JOB_TOOL_NAMES)))
                    runtime = json.loads(
                        (await restarted.read_resource("hpc://runtime"))[0].content
                    )
                    self.assertEqual(
                        "job-inspection",
                        runtime["capabilities"]["max_level"],
                    )
                    self.assertEqual(
                        "job-lifecycle",
                        runtime["delegation"]["controller_authority"]["policy"][
                            "max_level"
                        ],
                    )
                    self.assertEqual(
                        {
                            "mode": "model-only",
                            "web_search": "disabled",
                            "command_network_access": False,
                        },
                        runtime["delegation"]["network"],
                    )

        asyncio.run(exercise_server())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
    def test_slurm_job_server_loads_host_side_delegation_context(self) -> None:
        async def exercise_server() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
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
                        clusters = ["wice"]
                        partitions = ["batch"]
                        qos = []
                        reservations = []
                        containers = []
                        script_sha256 = []
                        roots = ["/work/delegate-1"]
                        [budget]
                        max_submissions = 2

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
                config_path.write_text(
                    config_path.read_text(encoding="utf-8").replace(
                        'sam_quote_command = "sam-quote"',
                        'sam_quote_command = "sam-quote"\n'
                        'sam_quote_format = "hpc-tools-credit-quote-v1"',
                    ),
                    encoding="utf-8",
                )
                environment = {
                    "HPC_TOOLS_CONFIG": str(config_path),
                    "XDG_CONFIG_HOME": str(root),
                    "HPC_TOOLS_PARENT_JOB_ID": "9001",
                }
                with mock.patch.dict("os.environ", environment, clear=False):
                    server = mcp_server.create_server(
                        preset="slurm-job",
                        profile="genius",
                        delegation_manifest=str(manifest_path),
                        ledger=str(root / "ledger.sqlite3"),
                    )
                    runtime = await server.read_resource("hpc://runtime")
                    data = json.loads(runtime[0].content)
                    self.assertTrue(data["delegation"]["configured"])
                    self.assertEqual("delegate-1", data["delegation"]["identifier"])
                    self.assertEqual(1, data["delegation"]["controller"]["generation"])
                    self.assertEqual(
                        2,
                        data["delegation"]["usage"]["remaining"]["max_submissions"],
                    )
                    self.assertEqual(
                        {"value": 0, "scale": 0, "unit": "credits"},
                        data["delegation"]["usage"]["quoted_credit"][
                            "consumed_quoted_maximum"
                        ],
                    )
                    self.assertEqual(
                        {"value": 10000, "scale": 0, "unit": "credits"},
                        data["delegation"]["usage"]["quoted_credit"][
                            "remaining_quoted_maximum"
                        ],
                    )

                with mock.patch.dict(
                    "os.environ",
                    {
                        "HPC_TOOLS_CONFIG": str(config_path),
                        "XDG_CONFIG_HOME": str(root),
                    },
                    clear=True,
                ), self.assertRaisesRegex(
                    mcp_server.ConfigError,
                    "HPC_TOOLS_PARENT_JOB_ID",
                ):
                    mcp_server.create_server(
                        preset="slurm-job",
                        profile="genius",
                        delegation_manifest=str(manifest_path),
                        ledger=str(root / "other.sqlite3"),
                    )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            with mock.patch.dict(
                "os.environ",
                {
                    "HPC_TOOLS_CONFIG": str(config_path),
                    "XDG_CONFIG_HOME": str(root),
                },
                clear=True,
            ), self.assertRaisesRegex(
                mcp_server.ConfigError,
                "requires --delegation",
            ):
                mcp_server.create_server(
                    preset="slurm-job",
                    profile="genius",
                )

        asyncio.run(exercise_server())
