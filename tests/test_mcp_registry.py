from __future__ import annotations

from test_mcp_fixtures import *


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_mcp_tool_and_resource_registries_are_stable(self) -> None:
        self.assertEqual(
            mcp_server.TOOL_NAMES,
            (
                "hpc_profiles_list",
                "hpc_paths",
                "hpc_profile_show",
                "hpc_hardware_context",
                "hpc_hardware_sources",
                "hpc_references_list",
                "hpc_references_show",
                "hpc_plugins_list",
                "hpc_submissions_list",
                "hpc_status",
                "hpc_jobs",
                "hpc_job",
                "hpc_cancel_job",
                "hpc_slurm_limits",
                "hpc_module_spider",
                "hpc_storage_inspect",
                "hpc_site_env",
                "hpc_references_create",
                "hpc_references_import",
                "hpc_references_attach",
                "hpc_submissions_mark_collected",
                "hpc_submissions_mark_analysed",
                "hpc_submissions_close",
                "hpc_write_probe",
                "hpc_install_probe",
                "hpc_write_container",
                "hpc_install_container",
                "hpc_quote_job",
                "hpc_validate_job",
                "hpc_submit_job",
            ),
        )
        self.assertEqual(
            mcp_server.RESOURCE_URIS,
            (
                "hpc://paths",
                "hpc://config",
                "hpc://submissions/active",
                "hpc://submissions/all",
            ),
        )
        self.assertEqual(
            mcp_server.RESOURCE_TEMPLATES,
            (
                "hpc://profiles/{profile}",
                "hpc://profiles/{profile}/hardware",
                "hpc://profiles/{profile}/slurm",
                "hpc://profiles/{profile}/storage",
                "hpc://reference-sets/{name}",
            ),
        )

    def test_mcp_tool_schemas_are_stable_for_guarded_submission(self) -> None:
        expected = {
            "hpc_cancel_job": [
                "jobid",
                "profile",
                "config",
                "cluster",
                "reason",
                "log",
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
                "profile",
                "config",
                "dry_run",
            ],
            "hpc_validate_job": [
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
        self.assertIn("hpc://profiles/{profile}/hardware", templates)
        self.assertIn("hpc://reference-sets/{name}", templates)
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

                    self.assertEqual(set(mcp_server.TOOL_NAMES), names)
                    self.assertIn("hpc_submit_job", names)

                    content, structured = await server.call_tool("hpc_paths", {})
                    self.assertEqual(len(content), 1)
                    self.assertIn("hardware_probe_template", content[0].text)
                    self.assertIn("hardware_probe_template", structured)

                    listed_resources = await server.list_resources()
                    resource_uris = {str(resource.uri) for resource in listed_resources}
                    self.assertEqual(set(mcp_server.RESOURCE_URIS), resource_uris)

                    listed_templates = await server.list_resource_templates()
                    template_uris = {template.uriTemplate for template in listed_templates}
                    self.assertEqual(set(mcp_server.RESOURCE_TEMPLATES), template_uris)

                    read = await server.read_resource("hpc://profiles/genius/hardware")
                    self.assertEqual(read[0].content, "# hardware\n")

                    read = await server.read_resource("hpc://reference-sets/baseline")
                    self.assertIn('"name": "baseline"', read[0].content)

        asyncio.run(exercise_server())
