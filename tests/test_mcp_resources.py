from __future__ import annotations

from test_mcp_fixtures import *


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_profiles_list_uses_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_profiles_list(config=str(config_path))

        self.assertEqual(result["default_profile"], "genius")
        self.assertEqual(result["profiles"][0]["name"], "genius")
        self.assertEqual(result["profiles"][0]["ssh_target"], "genius")

    def test_profile_show_resolves_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_profile_show(config=str(config_path))

        self.assertEqual(result["name"], "genius")
        self.assertEqual(result["ssh_target"], "genius")
        self.assertEqual(result["default_cluster"], "wice")

    def test_resource_config_reads_active_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                text = mcp_server.resource_config()

        self.assertIn('default_profile = "genius"', text)
        self.assertIn("[profiles.genius]", text)

    def test_resource_profile_returns_json_from_active_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                result = json.loads(mcp_server.resource_profile("genius"))

        self.assertEqual(result["name"], "genius")
        self.assertEqual(result["ssh_target"], "genius")

    def test_profile_reference_resources_read_active_config_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                hardware = mcp_server.resource_profile_hardware("genius")
                slurm = mcp_server.resource_profile_slurm("genius")
                storage = mcp_server.resource_profile_storage("genius")

        self.assertEqual(hardware, "# hardware\n")
        self.assertEqual(slurm, "# slurm\n")
        self.assertEqual(storage, "# storage\n")

    def test_reference_set_resource_reads_default_reference_sets_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_config(root)
            self._write_reference_set(root, "baseline")

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=False):
                result = json.loads(mcp_server.resource_reference_set("baseline"))

        self.assertEqual(result["name"], "baseline")
        self.assertTrue(result["hardware_reference"].endswith("hardware.md"))

    def test_local_mcp_tools_work_without_profile_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "submissions.sqlite3"

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                paths = mcp_server.hpc_paths()
                references = mcp_server.hpc_references_list()
                plugins = mcp_server.hpc_plugins_list()
                submissions = mcp_server.hpc_submissions_list(database=str(database_path))
                probe = mcp_server.hpc_write_probe(output="-")
                container = mcp_server.hpc_write_container(output=str(root / "bundle"))

        self.assertTrue(paths["config"].endswith("hpc-tools/config.toml"))
        self.assertTrue(
            paths["submissions_database"].endswith(
                "hpc-tools/submissions.sqlite3"
            )
        )
        self.assertEqual(references["reference_sets"], [])
        self.assertIn("plugins", plugins)
        self.assertEqual(submissions["submissions"], [])
        self.assertIn("#SBATCH --job-name=hardware-probe", probe["contents"])
        self.assertIn("create_apptainer_container.slurm", container["files"])
        self.assertFalse(database_path.exists())
        self.assertFalse((root / "bundle").exists())

    def test_profile_required_tools_reject_missing_or_unknown_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root / "missing")}, clear=True):
                with self.assertRaisesRegex(ValueError, "configuration file not found"):
                    mcp_server.hpc_jobs(dry_run=True)

            with self.assertRaisesRegex(ValueError, "unknown profile"):
                mcp_server.hpc_jobs(profile="missing", config=str(config_path), dry_run=True)

