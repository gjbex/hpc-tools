from __future__ import annotations

from test_mcp_fixtures import *
import tomllib

from hpc_tools import submissions


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_profiles_list_uses_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_profiles_list(config=str(config_path))

        self.assertEqual(result["default_profile"], "genius")
        self.assertEqual(result["profiles"][0]["name"], "genius")
        self.assertNotIn("ssh_target", result["profiles"][0])
        self.assertEqual(
            result["profiles"][0]["capabilities"]["max_level"],
            "job-lifecycle",
        )

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
            config_path.write_text(
                config_path.read_text(encoding="utf-8")
                + textwrap.dedent(
                    """

                    [profiles.other]
                    ssh_target = "secret-other-host"
                    quota_command = "secret-other-quota"

                    [profiles.other.capabilities]
                    version = 1
                    max_level = "profile-context"
                    scopes = ["config.read.raw"]

                    [profiles.other.capabilities.remote_roots]
                    list = []
                    read = []
                    write = []
                    delete = []
                    install = []
                    """
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                text = mcp_server.resource_config()

        payload = tomllib.loads(text)
        self.assertEqual(payload["default_profile"], "genius")
        self.assertEqual(payload["profiles"]["genius"]["ssh_target"], "genius")
        self.assertNotIn("other", payload)
        self.assertNotIn("secret-other-host", text)
        self.assertNotIn("secret-other-quota", text)

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

    def test_submission_resource_filters_selected_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            database_path = root / "hpc-tools" / "submissions.sqlite3"
            submissions.append_events(
                [
                    {
                        "event": "submitted",
                        "run_id": "genius-run",
                        "profile": "genius",
                        "job_id": "1",
                    },
                    {
                        "event": "submitted",
                        "run_id": "other-run",
                        "profile": "other",
                        "job_id": "2",
                    },
                ],
                path=database_path,
            )

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                result = json.loads(mcp_server.resource_submissions_all())

        self.assertEqual(result["profile"], "genius")
        self.assertEqual(
            [record["run_id"] for record in result["submissions"]],
            ["genius-run"],
        )

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

    def test_profile_free_bootstrap_tools_work_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root)}, clear=True):
                paths = mcp_server.hpc_paths()
                references = mcp_server.hpc_references_list()
                plugins = mcp_server.hpc_plugins_list()

        self.assertTrue(paths["config"].endswith("hpc-tools/config.toml"))
        self.assertTrue(
            paths["submissions_database"].endswith(
                "hpc-tools/submissions.sqlite3"
            )
        )
        self.assertEqual(references["reference_sets"], [])
        self.assertIn("plugins", plugins)

    def test_profile_required_tools_reject_missing_or_unknown_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(root / "missing")}, clear=True):
                with self.assertRaisesRegex(ValueError, "configuration file not found"):
                    mcp_server.hpc_jobs(dry_run=True)

            with self.assertRaisesRegex(ValueError, "unknown profile"):
                mcp_server.hpc_jobs(profile="missing", config=str(config_path), dry_run=True)

