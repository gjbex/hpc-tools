from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from importlib import resources
from pathlib import Path
from unittest import mock

from hpc_tools import delegation, mcp_bridge, restricted_jobs, restricted_launch
from hpc_tools.config import Profile


class RestrictedBoundaryTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[delegation.DelegationRuntime, dict[str, Path]]:
        paths = {
            name: root / name
            for name in ("state", "work", "output", "input")
        }
        for path in paths.values():
            path.mkdir(mode=0o700)
        apptainer = root / "apptainer"
        apptainer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        apptainer.chmod(0o700)
        container = root / "worker.sif"
        container.write_bytes(b"container")
        paths |= {"apptainer": apptainer, "container": container}
        run = paths["work"] / "run"
        run.mkdir()
        payload = run / "job.sh"
        payload.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
        paths |= {"run": run, "payload": payload}
        manifest_path = root / "delegation.toml"
        manifest_path.write_text(
            textwrap.dedent(
                f"""
                format_version = 1
                id = "delegate-1"
                issuer = "operator"
                profile = "cluster"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [allowed]
                accounts = ["project"]
                clusters = ["alpha"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = ["{container}"]
                script_sha256 = []
                roots = ["{paths['work']}"]

                [filesystem]
                state_root = "{paths['state']}"
                work_root = "{paths['work']}"
                output_root = "{paths['output']}"
                input_roots = ["{paths['input']}"]
                apptainer_path = "{apptainer}"
                max_file_blocks = 1024
                max_open_files = 128

                [budget]
                max_submissions = 2
                """
            ).strip() + "\n",
            encoding="utf-8",
        )
        paths["manifest"] = manifest_path
        runtime = delegation.load_runtime(
            manifest_path,
            profile="cluster",
            ledger_path=root / "ledger.sqlite3",
            parent_job_id="9001",
        )
        return runtime, paths

    def _profile(self) -> Profile:
        return Profile(
            name="cluster", target=None, host=None, user=None, ssh_options=(),
            login_shell=("bash", "-l", "-c"), projects_dir=None,
            quota_command=None, queue_command=None, sam_balance_command=None,
            sam_statement_command=None, sam_quote_command="quote",
            hardware_reference=None, hardware_url=None, slurm_reference=None,
            slurm_url=None, storage_reference=None, storage_url=None,
            status_url=None, reference_set=None, default_cluster="alpha", email=None,
        )

    def test_packaged_codex_agent_is_pinned_ephemeral_and_relay_only(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        definition = assets.joinpath("Apptainer.def").read_text(encoding="utf-8")
        wrapper = assets.joinpath("codex-agent").read_text(encoding="utf-8")
        config = assets.joinpath("codex-config.toml").read_text(encoding="utf-8")

        self.assertIn("From: node:22.16.0-bookworm-slim", definition)
        self.assertIn("npm install --global @openai/codex@0.150.1", definition)
        self.assertNotIn("@openai/codex@latest", definition)
        self.assertIn('test "$(codex --version)" = "codex-cli 0.150.1"', definition)
        for command in restricted_launch.FORBIDDEN_COMMANDS:
            self.assertIn(command, definition)
        self.assertIn("mktemp -d /tmp/codex-home.XXXXXX", wrapper)
        self.assertIn("--strict-config", wrapper)
        self.assertIn("--ephemeral", wrapper)
        self.assertIn("--sandbox workspace-write", wrapper)
        self.assertIn("--skip-git-repo-check", wrapper)
        self.assertNotIn("set -x", wrapper)
        self.assertIn("[mcp_servers.hpc-tools]", config)
        self.assertIn('command = "hpc-mcp-relay"', config)
        self.assertIn("required = true", config)

    def test_prepared_job_uses_snapshot_fixed_logs_and_restricted_binds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            prepared = restricted_jobs.prepare_job(
                runtime,
                profile=self._profile(),
                jobscript="job.sh",
                directory=str(paths["run"]),
                container=str(paths["container"]),
                idempotency_key="request-1",
                overrides={
                    "account": "project", "cluster": "alpha",
                    "partition": "batch", "output": None,
                    "error": None, "export": None,
                },
                stage=True,
            )
            state_directory = Path(prepared.directory)
            wrapper = (state_directory / prepared.jobscript).read_text(encoding="utf-8")
            snapshot = (state_directory / "payload.sh").read_text(encoding="utf-8")
            self.assertEqual("#!/bin/sh\necho hello\n", snapshot)
            self.assertIn("--containall", wrapper)
            self.assertIn("--cleanenv", wrapper)
            self.assertIn(f"{paths['work']}:{paths['work']}:ro", wrapper)
            self.assertIn(f"{paths['input']}:{paths['input']}:ro", wrapper)
            self.assertIn(f"{prepared.output_directory}:{prepared.output_directory}:rw", wrapper)
            self.assertNotIn("HPC_TOOLS_MCP_SOCKET", wrapper)
            self.assertEqual("NONE", prepared.overrides["export"])
            self.assertTrue(str(prepared.overrides["output"]).startswith(prepared.output_directory))
            self.assertTrue(str(prepared.overrides["error"]).startswith(prepared.output_directory))
            self.assertEqual(0o500, stat.S_IMODE((state_directory / "payload.sh").stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(Path(prepared.output_directory).stat().st_mode))
            self.assertIsNone(prepared.discard())
            self.assertFalse(state_directory.exists())
            self.assertFalse(Path(prepared.output_directory).exists())

    def test_restricted_job_rejects_agent_log_paths_and_symlink_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            arguments = {
                "runtime": runtime,
                "profile": self._profile(),
                "jobscript": "job.sh",
                "directory": str(paths["run"]),
                "container": str(paths["container"]),
                "idempotency_key": "request-1",
                "stage": False,
            }
            with self.assertRaisesRegex(delegation.DelegationError, "output"):
                restricted_jobs.prepare_job(
                    **arguments,
                    overrides={"account": "project", "cluster": "alpha", "output": "/tmp/x"},
                )
            with self.assertRaisesRegex(delegation.DelegationError, "one Slurm node"):
                restricted_jobs.prepare_job(
                    **arguments,
                    overrides={
                        "account": "project", "cluster": "alpha", "ntasks": "2"
                    },
                )
            paths["payload"].unlink()
            paths["payload"].symlink_to(paths["input"] / "payload.sh")
            (paths["input"] / "payload.sh").write_text("echo escaped\n", encoding="utf-8")
            with self.assertRaisesRegex(delegation.DelegationError, "symbolic link"):
                restricted_jobs.prepare_job(
                    **arguments,
                    overrides={"account": "project", "cluster": "alpha"},
                )

    def test_quote_validation_staging_is_temporary_and_does_not_consume_output_space(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            prepared = restricted_jobs.prepare_job(
                runtime,
                profile=self._profile(),
                jobscript="job.sh",
                directory=str(paths["run"]),
                container=str(paths["container"]),
                idempotency_key="request-1",
                overrides={"account": "project", "cluster": "alpha"},
                stage=True,
                temporary=True,
            )
            temporary_state = Path(prepared.directory)
            self.assertTrue(temporary_state.is_dir())
            self.assertFalse(Path(prepared.output_directory).exists())
            prepared.cleanup()
            self.assertFalse(temporary_state.exists())
            self.assertEqual([], list(paths["output"].iterdir()))

    def test_parent_command_has_only_explicit_bind_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            socket_directory = Path(directory) / "socket"
            socket_directory.mkdir(mode=0o700)
            command = restricted_launch.build_apptainer_command(
                manifest=runtime.manifest,
                agent_image=paths["container"],
                socket_directory=socket_directory,
                agent_command=["agent", "--batch"],
            )
            rendered = " ".join(command)
            self.assertIn("--containall", command)
            self.assertIn("home,cwd,hostfs,bind-paths", command)
            self.assertIn(f"{paths['work']}:{paths['work']}:rw", command)
            self.assertIn(f"{paths['output']}:{paths['output']}:ro", command)
            self.assertIn(f"{paths['input']}:{paths['input']}:ro", command)
            self.assertNotIn(str(paths["state"]), rendered)
            self.assertNotIn(str(runtime.ledger_path), rendered)

    def test_apptainer_like_clean_environment_exposes_no_scheduler_commands(self) -> None:
        """Exercise the generated argv through a clean-environment runtime shim.

        This checks the launcher/runtime contract without claiming kernel-level
        mount isolation, which requires a real target-site Apptainer pilot.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            empty_bin = root / "empty-bin"
            empty_bin.mkdir()
            shim = paths["apptainer"]
            shim.write_text(
                f"""#!{sys.executable}
import os
import subprocess
import sys

arguments = sys.argv[1:]
if not arguments or arguments.pop(0) != "exec":
    raise SystemExit(90)
container_environment = {{"PATH": {str(empty_bin)!r}}}
value_options = {{"--no-mount", "--bind", "--env", "--pwd", "--env-file"}}
flag_options = {{"--containall", "--cleanenv", "--no-home"}}
index = 0
while index < len(arguments):
    option = arguments[index]
    if option in flag_options:
        index += 1
        continue
    if option in value_options:
        value = arguments[index + 1]
        if option == "--env":
            name, content = value.split("=", 1)
            container_environment[name] = content
        index += 2
        continue
    break
if index >= len(arguments):
    raise SystemExit(91)
command = arguments[index + 1:]
raise SystemExit(subprocess.run(command, env=container_environment).returncode)
""",
                encoding="utf-8",
            )
            shim.chmod(0o700)
            socket_directory = root / "socket"
            socket_directory.mkdir(mode=0o700)
            probe = (
                "import json,os,shutil; "
                f"commands={restricted_launch.FORBIDDEN_COMMANDS!r}; "
                "print(json.dumps({'available': [name for name in commands "
                "if shutil.which(name)], 'environment': sorted(os.environ), "
                "'socket': os.environ.get('HPC_TOOLS_MCP_SOCKET')}))"
            )
            command = restricted_launch.build_apptainer_command(
                manifest=runtime.manifest,
                agent_image=paths["container"],
                socket_directory=socket_directory,
                agent_command=[sys.executable, "-c", probe],
            )
            with mock.patch.dict(
                os.environ,
                {
                    "PATH": os.environ.get("PATH", ""),
                    "SSH_AUTH_SOCK": "/tmp/ssh-agent",
                    "OPENAI_API_KEY": "must-not-cross",
                    "HPC_TOOLS_MCP_LEDGER": str(runtime.ledger_path),
                },
                clear=True,
            ):
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=restricted_launch._sanitized_apptainer_environment(),
                )

            self.assertEqual(0, completed.returncode, completed.stderr)
            observation = json.loads(completed.stdout)
            self.assertEqual([], observation["available"])
            self.assertTrue(
                set(observation["environment"]).issubset(
                    {"HOME", "HPC_TOOLS_MCP_SOCKET", "PATH", "LC_CTYPE"}
                )
            )
            self.assertNotIn("OPENAI_API_KEY", observation["environment"])
            self.assertNotIn("HPC_TOOLS_MCP_LEDGER", observation["environment"])
            self.assertEqual(
                "/run/hpc-tools-mcp/server.sock", observation["socket"]
            )

    def test_launcher_dry_run_requires_parent_job_and_keeps_private_state_unbound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            paths["manifest"].chmod(0o600)
            runtime_base = root / "runtime"
            runtime_base.mkdir(mode=0o700)
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"SLURM_JOB_ID": "9001"}, clear=True),
                contextlib.redirect_stdout(stdout),
            ):
                result = restricted_launch.launch(
                    manifest_path=paths["manifest"],
                    ledger_path=runtime.ledger_path,
                    profile="cluster",
                    agent_image=paths["container"],
                    agent_command=["agent", "--batch"],
                    runtime_base=runtime_base,
                    dry_run=True,
                )
            rendered = stdout.getvalue()
            self.assertEqual(0, result)
            self.assertIn("--containall", rendered)
            self.assertNotIn(str(paths["state"]), rendered)
            self.assertNotIn(str(runtime.ledger_path), rendered)

    def test_environment_filter_removes_credentials_and_apptainer_injection(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "SSH_AUTH_SOCK": "/tmp/agent",
                "OPENAI_API_KEY": "secret",
                "APPTAINERENV_ESCAPE": "value",
                "SAFE_VALUE": "yes",
            },
            clear=True,
        ):
            filtered = restricted_launch._sanitized_apptainer_environment()
        self.assertEqual("/bin", filtered["PATH"])
        self.assertNotIn("SAFE_VALUE", filtered)
        self.assertNotIn("SSH_AUTH_SOCK", filtered)
        self.assertNotIn("OPENAI_API_KEY", filtered)
        self.assertNotIn("APPTAINERENV_ESCAPE", filtered)

    def test_host_server_environment_drops_unneeded_credentials(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "SLURM_JOB_ID": "9001",
                "SSH_AUTH_SOCK": "/tmp/agent",
                "OPENAI_API_KEY": "secret",
                "HPC_TOOLS_CONFIG": "/protected/config.toml",
            },
            clear=True,
        ):
            filtered = restricted_launch._sanitized_server_environment("9001")
        self.assertEqual("/protected/config.toml", filtered["HPC_TOOLS_CONFIG"])
        self.assertEqual("9001", filtered[delegation.PARENT_JOB_ENV_VAR])
        self.assertNotIn("SSH_AUTH_SOCK", filtered)
        self.assertNotIn("OPENAI_API_KEY", filtered)

    def test_bridge_copies_raw_mcp_bytes_without_interpreting_them(self) -> None:
        connection = mock.Mock()
        mcp_bridge._pipe_to_socket(io.BytesIO(b"mcp bytes"), connection)
        connection.sendall.assert_called_once_with(b"mcp bytes")

    def test_unix_bridge_round_trip_when_local_sockets_are_available(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            root.chmod(0o700)
            path = root / "mcp.sock"
            results: list[int] = []
            errors: list[OSError] = []

            def run_server() -> None:
                try:
                    results.append(
                        mcp_bridge.serve(
                            path,
                            [
                                sys.executable,
                                "-c",
                                (
                                    "import sys; data=sys.stdin.buffer.read(); "
                                    "sys.stdout.buffer.write(data); "
                                    "sys.stdout.buffer.flush()"
                                ),
                            ],
                        )
                    )
                except OSError as error:
                    errors.append(error)

            server = threading.Thread(target=run_server)
            server.start()
            deadline = time.monotonic() + 5
            while not path.exists() and not errors and time.monotonic() < deadline:
                time.sleep(0.01)
            if errors:
                server.join(timeout=1)
                if errors[0].errno == 1:
                    self.skipTest("sandbox disallows Unix-domain socket binding")
                raise errors[0]
            self.assertTrue(path.exists(), "bridge did not create its socket")
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(path))
            client.sendall(b"mcp bytes")
            client.shutdown(socket.SHUT_WR)
            received = b""
            while True:
                chunk = client.recv(1024)
                if not chunk:
                    break
                received += chunk
            client.close()
            server.join(timeout=5)
            self.assertFalse(server.is_alive())
            self.assertEqual(b"mcp bytes", received)
            self.assertEqual([0], results)


if __name__ == "__main__":
    unittest.main()
