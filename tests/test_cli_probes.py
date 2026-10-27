from __future__ import annotations

from test_cli_fixtures import *

from hpc_tools.commands.probes import _container_bundle


class CliCoreTests(unittest.TestCase):
    def test_write_hardware_probe_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["write-hardware-probe", "probe.slurm"])

        self.assertIs(args.handler, cmd_write_hardware_probe)
        self.assertEqual(args.output, "probe.slurm")
        self.assertFalse(args.force)

    def test_write_probe_parser_accepts_kind(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["write-probe", "--kind", "cuda-device-properties", "out"])

        self.assertIs(args.handler, cmd_write_probe)
        self.assertEqual(args.kind, "cuda-device-properties")
        self.assertEqual(args.output, "out")

    def test_install_probe_parser_accepts_kind(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "install-probe",
                "--kind",
                "cuda-device-properties",
                "--directory",
                "$VSC_DATA/probes",
            ]
        )

        self.assertIs(args.handler, cmd_install_probe)
        self.assertEqual(args.kind, "cuda-device-properties")
        self.assertEqual(args.directory, "$VSC_DATA/probes")

    def test_install_hardware_probe_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "install-hardware-probe",
                "--directory",
                "$VSC_DATA/probes",
                "--account",
                "proj",
                "--cluster",
                "cluster-a",
                "--partition",
                "batch",
                "--time",
                "00:30:00",
                "--mail-notifications",
            ]
        )

        self.assertIs(args.handler, cmd_install_hardware_probe)
        self.assertEqual(args.directory, "$VSC_DATA/probes")
        self.assertEqual(args.account, "proj")
        self.assertEqual(args.cluster, "cluster-a")
        self.assertEqual(args.partition, "batch")
        self.assertEqual(args.time, "00:30:00")
        self.assertTrue(args.mail_notifications)

    def test_write_container_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["write-container", "--kind", "generic", "bundle"])

        self.assertIs(args.handler, cmd_write_container)
        self.assertEqual(args.kind, "generic")
        self.assertEqual(args.output, "bundle")

    def test_install_container_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "install-container",
                "--kind",
                "generic",
                "--directory",
                "$VSC_DATA/containers",
            ]
        )

        self.assertIs(args.handler, cmd_install_container)
        self.assertEqual(args.kind, "generic")
        self.assertEqual(args.directory, "$VSC_DATA/containers")

    def test_write_hardware_probe_to_stdout(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "write-hardware-probe",
                "--account",
                "proj",
                "--cluster",
                "cluster-a",
                "--partition",
                "batch",
                "--qos",
                "normal",
                "--time",
                "00:30:00",
                "--cpus-per-task",
                "72",
                "--mail-user",
                "user@example.org",
            ]
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = args.handler(args, make_profile())

        self.assertEqual(result, 0)
        self.assertIn("#SBATCH --job-name=hardware-probe", stdout.getvalue())
        self.assertIn("#SBATCH --account=proj", stdout.getvalue())
        self.assertIn("#SBATCH --clusters=cluster-a", stdout.getvalue())
        self.assertIn("#SBATCH --partition=batch", stdout.getvalue())
        self.assertIn("#SBATCH --qos=normal", stdout.getvalue())
        self.assertIn("#SBATCH --time=00:30:00", stdout.getvalue())
        self.assertIn("#SBATCH --cpus-per-task=72", stdout.getvalue())
        self.assertIn("#SBATCH --mail-user=user@example.org", stdout.getvalue())
        self.assertIn("#SBATCH --mail-type=END,FAIL", stdout.getvalue())
        self.assertIn("lscpu --cache", stdout.getvalue())

    def test_write_hardware_probe_uses_profile_email_for_notifications(self) -> None:
        parser = build_parser(make_profile(email="profile@example.org"))
        args = parser.parse_args(["write-hardware-probe", "--mail-notifications"])

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = args.handler(args, make_profile(email="profile@example.org"))

        self.assertEqual(result, 0)
        self.assertIn("#SBATCH --mail-user=profile@example.org", stdout.getvalue())
        self.assertIn("#SBATCH --mail-type=END,FAIL", stdout.getvalue())

    def test_write_hardware_probe_rejects_profile_notifications_without_email(self) -> None:
        parser = build_parser(make_profile(email=None))
        args = parser.parse_args(["write-hardware-probe", "--mail-notifications"])

        with self.assertRaises(ConfigError):
            args.handler(args, make_profile(email=None))

    def test_write_hardware_probe_to_file(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"
            args = parser.parse_args(["write-hardware-probe", str(output)])

            result = args.handler(args, make_profile())

            self.assertEqual(result, 0)
            self.assertIn("Hardware probe output written", output.read_text(encoding="utf-8"))

    def test_write_container_bundle_to_directory(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            args = parser.parse_args(["write-container", "--kind", "generic", str(output)])

            result = args.handler(args, make_profile())

            self.assertEqual(result, 0)
            self.assertTrue((output / "create_apptainer_container.slurm").exists())
            self.assertIn(
                "apptainer build",
                (output / "create_apptainer_container.slurm").read_text(encoding="utf-8"),
            )

    def test_write_restricted_agent_container_bundle(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "agent"
            args = parser.parse_args(
                ["write-container", "--kind", "agent", str(output)]
            )

            self.assertEqual(0, args.handler(args, make_profile()))
            definition = (output / "Apptainer.def").read_text(encoding="utf-8")
            wrapper = (output / "codex-agent").read_text(encoding="utf-8")
            configs = {
                mode: (output / f"codex-config-{mode}.toml").read_text(
                    encoding="utf-8"
                )
                for mode in (
                    "model-only",
                    "model-indexed-search",
                    "model-live-search",
                )
            }
            task = (output / "task.md").read_text(encoding="utf-8")
            slurm = (output / "restricted-agent.slurm").read_text(encoding="utf-8")
            skill = (
                output / "skills" / "hpc-delegated-slurm" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("@openai/codex@0.150.1", definition)
            self.assertIn("hpc-mcp-relay", definition)
            self.assertIn(
                "codex-config-model-only.toml "
                "/opt/hpc-tools/config/model-only.toml",
                definition,
            )
            self.assertIn("def relay_main", (output / "hpc-mcp-relay").read_text())
            self.assertIn("--ephemeral", wrapper)
            self.assertIn("--sandbox workspace-write", wrapper)
            self.assertIn('cp -R /opt/hpc-tools/skills "$codex_home/skills"', wrapper)
            self.assertIn('web_search = "disabled"', configs["model-only"])
            self.assertIn(
                'web_search = "indexed"', configs["model-indexed-search"]
            )
            self.assertIn('web_search = "live"', configs["model-live-search"])
            for config in configs.values():
                self.assertIn("[mcp_servers.hpc-tools]", config)
                self.assertIn("required = true", config)
                self.assertIn("network_access = false", config)
            self.assertIn("Use $hpc-delegated-slurm", task)
            self.assertIn("name: hpc-delegated-slurm", skill)
            self.assertEqual(
                ["hpc-delegated-slurm"],
                sorted(path.name for path in (output / "skills").iterdir()),
            )
            self.assertTrue(
                (
                    output
                    / "skills"
                    / "hpc-delegated-slurm"
                    / "references"
                    / "result-validation.md"
                ).is_file()
            )
            self.assertIn("--agent-env-file", slurm)
            self.assertIn("--network-env-file", slurm)
            self.assertIn("-- codex-agent -", slurm)
            self.assertFalse((output / "mcp.json").exists())

    def test_write_agent_boundary_container_bundle(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "agent-boundary"
            args = parser.parse_args(
                ["write-container", "--kind", "agent-boundary", str(output)]
            )

            self.assertEqual(0, args.handler(args, make_profile()))
            definition = (output / "Apptainer.def").read_text(encoding="utf-8")
            self.assertIn("restricted agent boundary fixture", definition)
            self.assertIn("From: python:3.12.11-slim-bookworm", definition)
            self.assertIn("hpc-mcp-relay", definition)
            self.assertNotIn("@openai/codex", definition)
            self.assertNotIn("codex-agent", definition)
            self.assertEqual(
                {"Apptainer.def", "hpc-mcp-relay"},
                {path.name for path in output.iterdir()},
            )

    def test_write_hardware_probe_rejects_existing_file_without_force(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"
            output.write_text("existing", encoding="utf-8")
            args = parser.parse_args(["write-hardware-probe", str(output)])

            with self.assertRaises(ConfigError):
                args.handler(args, make_profile())

    def test_write_hardware_probe_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["write-hardware-probe"])

        self.assertEqual(result, 0)
        self.assertIn("#SBATCH --job-name=hardware-probe", stdout.getvalue())

    def test_write_probe_hardware_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["write-probe", "--kind", "hardware"])

        self.assertEqual(result, 0)
        self.assertIn("#SBATCH --job-name=hardware-probe", stdout.getvalue())

    def test_write_probe_cuda_device_properties_bundle(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cuda-probe"
            args = parser.parse_args(["write-probe", "--kind", "cuda-device-properties", str(output)])

            result = args.handler(args, make_profile())

            self.assertEqual(result, 0)
            self.assertIn(
                "cuda-device-properties",
                (output / "cuda-device-properties.slurm").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "cudaGetDeviceProperties",
                (output / "cuda" / "device_properties.cu").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "device_properties.cu",
                (output / "cuda" / "CMakeLists.txt").read_text(encoding="utf-8"),
            )

    def test_write_probe_cuda_device_properties_rejects_stdout(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["write-probe", "--kind", "cuda-device-properties"])

        with self.assertRaises(ConfigError):
            args.handler(args, None)

    def test_install_container_bundle_writes_remote_bundle(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["install-container", "--kind", "generic", "--directory", "$VSC_DATA/containers"])

        with mock.patch(
            "hpc_tools.commands.probes.install_remote_assets",
            return_value=(),
        ) as install:
            result = cmd_install_container(args, profile)

        self.assertEqual(result, 0)
        self.assertEqual(install.call_args.args[1], "$VSC_DATA/containers")
        self.assertIn("create_apptainer_container.slurm", install.call_args.args[2])

    def test_apptainer_container_file_is_packaged(self) -> None:
        data = resources.files("hpc_tools.data")

        slurm_template = data.joinpath("containers", "apptainer", "create_apptainer_container.slurm")

        self.assertTrue(slurm_template.is_file())
        self.assertIn("apptainer build", slurm_template.read_text(encoding="utf-8"))

    def test_cuda_device_properties_files_are_packaged(self) -> None:
        data = resources.files("hpc_tools.data")

        slurm_template = data.joinpath("cuda-device-properties.slurm")
        cuda_source = data.joinpath("cuda", "device_properties.cu")
        cmake_project = data.joinpath("cuda", "CMakeLists.txt")

        self.assertTrue(slurm_template.is_file())
        self.assertTrue(cuda_source.is_file())
        self.assertTrue(cmake_project.is_file())
        self.assertIn("cuda-device-properties", slurm_template.read_text(encoding="utf-8"))
        self.assertIn("cudaGetDeviceProperties", cuda_source.read_text(encoding="utf-8"))
        self.assertIn("device_properties.cu", cmake_project.read_text(encoding="utf-8"))
