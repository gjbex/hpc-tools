from __future__ import annotations

import contextlib
import hashlib
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
import tomllib
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from unittest import mock

from hpc_tools import delegation, mcp_bridge, restricted_jobs, restricted_launch
from hpc_tools.capabilities import (
    POLICY_VERSION,
    CapabilityLevel,
    CapabilityPolicy,
    RemoteRootGrants,
)
from hpc_tools.config import ConfigError, Profile
from hpc_tools.mcp import server as mcp_registry


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
                format_version = 4
                id = "delegate-1"
                issuer = "operator"
                profile = "cluster"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [network]
                mode = "model-only"

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
        config_path = root / "config.toml"
        config_path.write_text(
            textwrap.dedent(
                """
                default_profile = "cluster"

                [profiles.cluster]
                ssh_target = "cluster"
                default_cluster = "alpha"
                sam_quote_command = "quote"

                [profiles.cluster.capabilities]
                version = 1
                max_level = "job-lifecycle"
                scopes = []
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        paths["config"] = config_path
        policy = self._profile().capabilities
        runtime = delegation.load_runtime(
            manifest_path,
            profile="cluster",
            ledger_path=root / "ledger.sqlite3",
            parent_job_id="9001",
            profile_policy=policy,
            config_path=config_path,
            config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        )
        return runtime, paths

    def _profile(self) -> Profile:
        return Profile(
            name="cluster", target=None, host=None, user=None, ssh_options=(),
            login_shell=("bash", "-l", "-c"), projects_dir=None,
            quota_command=None, queue_command=None, sam_balance_command=None,
            sam_statement_command=None, sam_quote_command="quote",
            sam_quote_format=None,
            hardware_reference=None, hardware_url=None, slurm_reference=None,
            slurm_url=None, storage_reference=None, storage_url=None,
            status_url=None, reference_set=None, default_cluster="alpha", email=None,
            capabilities=CapabilityPolicy(
                version=POLICY_VERSION,
                max_level=CapabilityLevel.JOB_LIFECYCLE,
                scopes=(),
                remote_roots=RemoteRootGrants(),
            ),
        )

    def _manifest_template(self, root: Path, paths: dict[str, Path]) -> Path:
        template = root / "delegation-template.toml"
        template.write_text(
            textwrap.dedent(
                f"""
                template_version = 1
                id_prefix = "delegate"
                issuer = "operator"
                profile = "cluster"
                lifetime_seconds = 3600

                [network]
                mode = "model-only"

                [allowed]
                accounts = ["project"]
                clusters = ["alpha"]
                partitions = ["batch"]
                qos = []
                reservations = []
                containers = ["{paths['container']}"]
                script_sha256 = []
                roots = ["{paths['work']}"]

                [filesystem]
                state_root = "{paths['state']}"
                work_root = "{paths['work']}"
                output_root = "{paths['output']}"
                input_roots = ["{paths['input']}"]
                apptainer_path = "{paths['apptainer']}"
                max_file_blocks = 1024
                max_open_files = 128

                [budget]
                max_submissions = 2
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        template.chmod(0o600)
        return template

    def test_packaged_codex_agent_is_pinned_ephemeral_and_relay_only(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        definition = assets.joinpath("Apptainer.def").read_text(encoding="utf-8")
        files_section = definition.split("%files", 1)[1].split("%post", 1)[0]
        wrapper = assets.joinpath("codex-agent").read_text(encoding="utf-8")
        configs = {
            mode: tomllib.loads(
                assets.joinpath(f"codex-config-{mode}.toml").read_text(
                    encoding="utf-8"
                )
            )
            for mode in (
                "model-only",
                "model-indexed-search",
                "model-live-search",
            )
        }

        self.assertIn(
            "From: node@sha256:"
            "048ed02c5fd52e86fda6fbd2f6a76cf0d4492fd6c6fee9e2c463ed5108da0e34",
            definition,
        )
        self.assertIn("npm install --global @openai/codex@0.150.1", definition)
        self.assertNotIn("@openai/codex@latest", definition)
        self.assertIn('test "$(codex --version)" = "codex-cli 0.150.1"', definition)
        for command in restricted_launch.FORBIDDEN_COMMANDS:
            self.assertIn(command, definition)
        for forbidden_asset in (
            "delegation-template.toml",
            "restricted-agent.slurm",
            "build-agent-image.slurm",
            "image-build-record.md",
            "auth.json",
            "delegations.sqlite3",
        ):
            self.assertNotIn(forbidden_asset, files_section)
        self.assertIn("/root/.codex", definition)
        self.assertIn("test ! -e \"$protected_path\"", definition)
        self.assertIn("mktemp -d /tmp/codex-home.XXXXXX", wrapper)
        self.assertIn("--strict-config", wrapper)
        self.assertIn("--ephemeral", wrapper)
        self.assertIn("--json", wrapper)
        self.assertIn("--sandbox workspace-write", wrapper)
        self.assertIn("--skip-git-repo-check", wrapper)
        self.assertNotIn("set -x", wrapper)
        self.assertIn("case \"${HPC_TOOLS_AGENT_NETWORK_MODE:-}\"", wrapper)
        for mode in configs:
            self.assertIn(f"    {mode})", wrapper)
        self.assertLess(
            wrapper.index('case "${HPC_TOOLS_AGENT_NETWORK_MODE:-}"'),
            wrapper.index('if [ -z "${HPC_TOOLS_MCP_SOCKET:-}" ]'),
        )
        self.assertLess(
            wrapper.index('if [ -z "${HPC_TOOLS_MCP_SOCKET:-}" ]'),
            wrapper.index("codex login"),
        )
        self.assertEqual(
            {
                "model-only": "disabled",
                "model-indexed-search": "indexed",
                "model-live-search": "live",
            },
            {mode: config["web_search"] for mode, config in configs.items()},
        )
        for config in configs.values():
            self.assertEqual("workspace-write", config["sandbox_mode"])
            self.assertFalse(config["allow_login_shell"])
            self.assertFalse(config["sandbox_workspace_write"]["network_access"])
            self.assertEqual(
                {
                    "inherit": "all",
                    "ignore_default_excludes": False,
                    "experimental_use_profile": False,
                    "filters": {
                        "OPENAI_API_KEY": "exclude",
                        "CODEX_ACCESS_TOKEN": "exclude",
                        "HTTP_PROXY": "exclude",
                        "HTTPS_PROXY": "exclude",
                        "NO_PROXY": "exclude",
                        "SSL_CERT_FILE": "exclude",
                        "SSL_CERT_DIR": "exclude",
                        "REQUESTS_CA_BUNDLE": "exclude",
                        "CURL_CA_BUNDLE": "exclude",
                        "HPC_TOOLS_AGENT_NETWORK_MODE": "exclude",
                        "HPC_TOOLS_MCP_SOCKET": "exclude",
                    },
                },
                config["shell_environment_policy"],
            )
            self.assertEqual(
                {
                    "command": "hpc-mcp-relay",
                    "required": True,
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 300,
                },
                config["mcp_servers"]["hpc-tools"],
            )
        self.assertNotIn("hpc-agent-reap", definition)

    def test_parent_template_requests_requeue_and_forwards_lifecycle_signals(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        template = assets.joinpath("restricted-agent.slurm").read_text(
            encoding="utf-8"
        )
        manifest = tomllib.loads(
            assets.joinpath("delegation-template.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(template.startswith("#!/bin/bash -l\n"))
        self.assertIn("#SBATCH --requeue", template)
        self.assertIn("#SBATCH --signal=B:USR1@600", template)
        self.assertIn("#SBATCH --open-mode=append", template)
        self.assertNotIn("\n#SBATCH --account=", template)
        self.assertNotIn("\n#SBATCH --partition=", template)
        self.assertIn("##SBATCH --account=<account>", template)
        self.assertIn("##SBATCH --partition=<partition>", template)
        self.assertIn("command -v hpc-agent-launch", template)
        self.assertIn('require_trusted_file "$apptainer_path"', template)
        self.assertIn('require_private_file "$agent_env_file"', template)
        self.assertIn('require_private_directory "$runtime_directory"', template)
        self.assertIn("warning_seconds=600", template)
        self.assertEqual(600, manifest["lifecycle"]["warning_seconds"])
        self.assertIn('--manifest-template "$manifest_template"', template)
        self.assertIn('--manifest-output "$manifest_output"', template)
        self.assertIn('delegation-${SLURM_JOB_ID}.toml', template)
        self.assertIn('--runtime-directory "$runtime_directory"', template)
        self.assertIn('--agent-env-file "$agent_env_file"', template)
        self.assertIn('--network-env-file "$network_env_file"', template)
        self.assertIn('--prompt-file "$prompt_file"', template)
        self.assertIn('--agent-image-sha256 "$agent_image_sha256"', template)
        self.assertNotIn('< "$prompt_file"', template)
        self.assertIn("trap forward_requeue USR1", template)
        self.assertIn("trap forward_termination TERM INT", template)
        self.assertIn('if ! kill -0 "$launcher_pid"', template)

    def test_packaged_agent_shell_entry_points_have_valid_syntax(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        entry_points = (
            ("bash", "restricted-agent.slurm"),
            ("bash", "build-agent-image.slurm"),
            ("sh", "codex-agent"),
        )

        for shell, name in entry_points:
            with self.subTest(name=name), resources.as_file(
                assets.joinpath(name)
            ) as path:
                completed = subprocess.run(
                    [shell, "-n", str(path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)

    def test_parent_template_preflights_private_inputs_before_launch(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        source = assets.joinpath("restricted-agent.slurm").read_text(
            encoding="utf-8"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "protected"
            manifests = protected / "manifests"
            runtime = root / "runtime"
            command_directory = root / "bin"
            for path in (protected, manifests, runtime, command_directory):
                path.mkdir(mode=0o700)

            manifest_template = protected / "delegation-template.toml"
            manifest_template.write_text(
                assets.joinpath("delegation-template.toml").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            credential = protected / "codex.env"
            credential.write_text("OPENAI_API_KEY=not-a-real-secret\n", encoding="utf-8")
            network = protected / "network.env"
            network.write_text("HTTPS_PROXY=http://proxy.invalid\n", encoding="utf-8")
            prompt = protected / "task.md"
            prompt.write_text("A reviewed bounded task.\n", encoding="utf-8")
            for path in (manifest_template, credential, network, prompt):
                path.chmod(0o600)

            config = root / "config.toml"
            config.write_text("default_profile = \"example\"\n", encoding="utf-8")
            config.chmod(0o644)
            agent_image = root / "agent.sif"
            agent_image.write_bytes(b"reviewed image")
            agent_image.chmod(0o444)
            digest = hashlib.sha256(agent_image.read_bytes()).hexdigest()
            apptainer = root / "apptainer"
            apptainer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            apptainer.chmod(0o755)

            capture = root / "launcher-arguments.txt"
            launcher = command_directory / "hpc-agent-launch"
            launcher.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE_PATH"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o700)

            replacements = {
                "apptainer_path=/usr/bin/apptainer": f"apptainer_path={apptainer}",
                "manifest_template=/path/to/protected/delegation-template.toml": (
                    f"manifest_template={manifest_template}"
                ),
                "manifest_directory=/path/to/protected/materialized-manifests": (
                    f"manifest_directory={manifests}"
                ),
                "ledger=/path/to/protected/delegations.sqlite3": (
                    f"ledger={protected / 'delegations.sqlite3'}"
                ),
                "config=${HPC_TOOLS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/hpc-tools/config.toml}": (
                    f"config={config}"
                ),
                "agent_image=/path/to/restricted-codex.sif": (
                    f"agent_image={agent_image}"
                ),
                "agent_image_sha256=REPLACE_WITH_REVIEWED_LOWERCASE_SHA256": (
                    f"agent_image_sha256={digest}"
                ),
                "agent_env_file=/path/to/protected/codex.env": (
                    f"agent_env_file={credential}"
                ),
                "network_env_file=  # Optional: /path/to/protected/network.env": (
                    f"network_env_file={network}"
                ),
                "prompt_file=/path/to/protected/reviewed-task.md": (
                    f"prompt_file={prompt}"
                ),
            }
            rendered = source
            for old, new in replacements.items():
                self.assertIn(old, rendered)
                rendered = rendered.replace(old, new, 1)
            job = root / "restricted-agent.slurm"
            job.write_text(rendered, encoding="utf-8")
            environment = os.environ | {
                "CAPTURE_PATH": str(capture),
                "PATH": f"{command_directory}{os.pathsep}{os.environ['PATH']}",
                "SLURM_JOB_ID": "9001",
                "SLURM_TMPDIR": str(runtime),
            }

            completed = subprocess.run(
                ["bash", str(job)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            arguments = capture.read_text(encoding="utf-8").splitlines()
            self.assertIn("--runtime-directory", arguments)
            self.assertIn(str(runtime), arguments)
            self.assertIn("--network-env-file", arguments)
            self.assertIn(str(network), arguments)
            self.assertIn("--manifest-output", arguments)
            self.assertIn(str(manifests / "delegation-9001.toml"), arguments)
            combined_output = completed.stdout + completed.stderr + "\n".join(arguments)
            self.assertNotIn("not-a-real-secret", combined_output)
            self.assertNotIn("http://proxy.invalid", combined_output)

            capture.unlink()
            credential.chmod(0o644)
            rejected = subprocess.run(
                ["bash", str(job)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("mode 0600", rejected.stderr)
            self.assertFalse(capture.exists())

    def test_packaged_codex_agent_exposes_only_the_delegated_slurm_skill(self) -> None:
        assets = resources.files("hpc_tools.data").joinpath("containers", "agent")
        skill_root = assets.joinpath("skills", "hpc-delegated-slurm")
        skill = skill_root.joinpath("SKILL.md").read_text(encoding="utf-8")
        task = assets.joinpath("task.md").read_text(encoding="utf-8")
        definition = assets.joinpath("Apptainer.def").read_text(encoding="utf-8")
        wrapper = assets.joinpath("codex-agent").read_text(encoding="utf-8")

        self.assertEqual(
            ["hpc-delegated-slurm"],
            sorted(path.name for path in assets.joinpath("skills").iterdir()),
        )
        self.assertIn("Use $hpc-delegated-slurm", task)
        self.assertIn("skills/hpc-delegated-slurm /opt/hpc-tools/skills", definition)
        self.assertIn('cp -R /opt/hpc-tools/skills "$codex_home/skills"', wrapper)
        for name in mcp_registry.SLURM_JOB_TOOL_NAMES:
            self.assertIn(f"`{name}`", skill)
        for uri in mcp_registry.SLURM_JOB_RESOURCE_URIS:
            self.assertIn(f"`{uri}`", skill)
        self.assertIn("credit_budget.maximum_total", skill)
        self.assertIn("quote.expired", skill)
        self.assertIn("zero-cost quote", skill)
        self.assertIn("do not convert, round, or infer", skill)
        for forbidden in ("hpc --profile", "sbatch ", "squeue ", "ssh "):
            self.assertNotIn(forbidden, skill)
        for reference in ("job-design.md", "arrays.md", "result-validation.md"):
            self.assertTrue(skill_root.joinpath("references", reference).is_file())

    def test_packaged_boundary_fixture_contains_no_agent_or_scheduler_client(self) -> None:
        definition = (
            resources.files("hpc_tools.data")
            .joinpath("containers", "agent-boundary", "Apptainer.def")
            .read_text(encoding="utf-8")
        )

        self.assertIn("restricted agent boundary fixture", definition)
        self.assertIn(
            "From: python@sha256:"
            "519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7",
            definition,
        )
        self.assertIn("hpc-mcp-relay", definition)
        self.assertNotIn("@openai/codex", definition)
        self.assertNotIn("codex-agent", definition)
        for command in restricted_launch.FORBIDDEN_COMMANDS:
            self.assertIn(command, definition)

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
            self.assertTrue(
                str(prepared.overrides["output"]).startswith(prepared.output_directory)
            )
            self.assertTrue(str(prepared.overrides["error"]).startswith(prepared.output_directory))
            self.assertEqual(0o500, stat.S_IMODE((state_directory / "payload.sh").stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(Path(prepared.output_directory).stat().st_mode))
            self.assertIsNone(prepared.discard())
            self.assertFalse(state_directory.exists())
            self.assertFalse(Path(prepared.output_directory).exists())

    def test_requeue_generation_invalidates_prepared_job_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            arguments = {
                "runtime": runtime,
                "profile": self._profile(),
                "jobscript": "job.sh",
                "directory": str(paths["run"]),
                "container": str(paths["container"]),
                "idempotency_key": "request-1",
                "overrides": {"account": "project", "cluster": "alpha"},
                "stage": False,
            }
            before = restricted_jobs.prepare_job(**arguments)
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            ledger.begin_draining(runtime.manifest, reason="SIGUSR1")
            ledger.request_requeue(runtime.manifest)
            ledger.record_requeue_result(runtime.manifest, accepted=True)
            restarted = ledger.begin_controller(runtime.manifest, restart_count=1)
            restarted_runtime = replace(
                runtime,
                controller_generation=int(restarted["generation"]),
            )
            after = restricted_jobs.prepare_job(
                **(arguments | {"runtime": restarted_runtime})
            )

            self.assertEqual(1, before.shape["controller_generation"])
            self.assertEqual(2, after.shape["controller_generation"])
            self.assertNotEqual(before.shape["shape_token"], after.shape["shape_token"])

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
            self.assertEqual(paths["output"], Path(prepared.output_directory).parent)
            self.assertTrue(
                str(prepared.overrides["output"]).startswith(
                    prepared.output_directory
                )
            )
            persistent = restricted_jobs.prepare_job(
                runtime,
                profile=self._profile(),
                jobscript="job.sh",
                directory=str(paths["run"]),
                container=str(paths["container"]),
                idempotency_key="request-1",
                overrides={"account": "project", "cluster": "alpha"},
                stage=False,
            )
            self.assertEqual(prepared.jobscript, persistent.jobscript)
            self.assertEqual(prepared.overrides, persistent.overrides)
            self.assertEqual(prepared.output_directory, persistent.output_directory)
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

    def test_manifest_network_mode_is_the_only_container_mode_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            socket_directory = Path(directory) / "socket"
            socket_directory.mkdir(mode=0o700)
            for mode in delegation.AgentNetworkMode:
                with self.subTest(mode=mode.value):
                    manifest = replace(
                        runtime.manifest,
                        network=delegation.AgentNetworkPolicy(mode),
                    )
                    command = restricted_launch.build_apptainer_command(
                        manifest=manifest,
                        agent_image=paths["container"],
                        socket_directory=socket_directory,
                        agent_command=["codex-agent", "-"],
                    )
                    self.assertIn(
                        f"{restricted_launch.NETWORK_MODE_ENV_VAR}={mode.value}",
                        command,
                    )

            with self.assertRaisesRegex(ConfigError, "exactly 'codex-agent -'"):
                restricted_launch._validate_agent_command(
                    ["codex-agent", "-c", 'web_search="live"', "-"]
                )

    def test_template_selection_previews_first_generation_and_verifies_requeue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, paths = self._fixture(root)
            template = self._manifest_template(root, paths)
            output = root / "materialized.toml"
            now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

            with mock.patch.dict(
                os.environ,
                {delegation.CONTROLLER_RESTART_ENV_VAR: "0"},
                clear=False,
            ):
                manifest, evidence, payload = restricted_launch._select_manifest(
                    manifest_path=None,
                    manifest_template_path=template,
                    manifest_output_path=output,
                    profile="cluster",
                    parent_job_id="9001",
                    dry_run=False,
                    now=now,
                )
            self.assertEqual("delegate-9001", manifest.identifier)
            self.assertIsNotNone(evidence)
            self.assertIsNotNone(payload)
            self.assertFalse(output.exists())
            delegation.publish_materialized_manifest(output, payload)

            with mock.patch.dict(
                os.environ,
                {delegation.CONTROLLER_RESTART_ENV_VAR: "1"},
                clear=False,
            ):
                requeued, requeue_evidence, pending = (
                    restricted_launch._select_manifest(
                        manifest_path=None,
                        manifest_template_path=template,
                        manifest_output_path=output,
                        profile="cluster",
                        parent_job_id="9001",
                        dry_run=False,
                        now=datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc),
                    )
                )
            self.assertEqual(manifest.digest, requeued.digest)
            self.assertEqual(evidence.template_sha256, requeue_evidence.template_sha256)
            self.assertIsNone(pending)

    def test_template_mismatch_and_expiry_precede_ledger_or_runtime_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, paths = self._fixture(root)
            template = self._manifest_template(root, paths)
            output = root / "materialized.toml"
            delegation.materialize_manifest_template(
                template,
                output,
                expected_profile="cluster",
                parent_job_id="9001",
                now=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
            )
            ledger_path = root / "new-ledger.sqlite3"
            launch_kwargs = {
                "manifest_path": None,
                "manifest_template_path": template,
                "manifest_output_path": output,
                "ledger_path": ledger_path,
                "profile": "cluster",
                "agent_image": paths["container"],
                "agent_image_sha256": hashlib.sha256(
                    paths["container"].read_bytes()
                ).hexdigest(),
                "agent_command": ["codex-agent", "-"],
                "runtime_base": root,
                "config_path": paths["config"],
            }

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "max_submissions = 2", "max_submissions = 3"
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SLURM_JOB_ID": "9001",
                        delegation.CONTROLLER_RESTART_ENV_VAR: "1",
                    },
                    clear=False,
                ),
                mock.patch.object(delegation.DelegationLedger, "register") as register,
                mock.patch("hpc_tools.restricted_launch.subprocess.Popen") as popen,
                self.assertRaisesRegex(ConfigError, "does not match"),
            ):
                restricted_launch.launch(**launch_kwargs)
            register.assert_not_called()
            popen.assert_not_called()
            self.assertFalse(ledger_path.exists())

            template.write_text(
                template.read_text(encoding="utf-8").replace(
                    "max_submissions = 3", "max_submissions = 2"
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SLURM_JOB_ID": "9001",
                        delegation.CONTROLLER_RESTART_ENV_VAR: "1",
                    },
                    clear=False,
                ),
                mock.patch.object(delegation.DelegationLedger, "register") as register,
                mock.patch("hpc_tools.restricted_launch.subprocess.Popen") as popen,
                self.assertRaisesRegex(ConfigError, "expired"),
            ):
                restricted_launch.launch(
                    **launch_kwargs,
                    now=datetime(2026, 10, 27, 13, 0, 1, tzinfo=timezone.utc),
                )
            register.assert_not_called()
            popen.assert_not_called()
            self.assertFalse(ledger_path.exists())

    def test_template_and_output_paths_cannot_overlap_container_binds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, paths = self._fixture(root)
            template = self._manifest_template(root, paths)
            output = paths["work"] / "materialized.toml"
            ledger_path = root / "new-ledger.sqlite3"
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SLURM_JOB_ID": "9001",
                        delegation.CONTROLLER_RESTART_ENV_VAR: "0",
                    },
                    clear=False,
                ),
                self.assertRaisesRegex(ConfigError, "overlaps container bind"),
            ):
                restricted_launch.launch(
                    manifest_path=None,
                    manifest_template_path=template,
                    manifest_output_path=output,
                    ledger_path=ledger_path,
                    profile="cluster",
                    agent_image=paths["container"],
                    agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    runtime_base=root,
                    config_path=paths["config"],
                    dry_run=True,
                    now=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
                )
            self.assertFalse(output.exists())
            self.assertFalse(ledger_path.exists())

            exposed_template = paths["work"] / "delegation-template.toml"
            exposed_template.write_bytes(template.read_bytes())
            exposed_template.chmod(0o600)
            safe_output = root / "materialized.toml"
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SLURM_JOB_ID": "9001",
                        delegation.CONTROLLER_RESTART_ENV_VAR: "0",
                    },
                    clear=False,
                ),
                self.assertRaisesRegex(ConfigError, "overlaps container bind"),
            ):
                restricted_launch.launch(
                    manifest_path=None,
                    manifest_template_path=exposed_template,
                    manifest_output_path=safe_output,
                    ledger_path=ledger_path,
                    profile="cluster",
                    agent_image=paths["container"],
                    agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    runtime_base=root,
                    config_path=paths["config"],
                    dry_run=True,
                    now=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
                )
            self.assertFalse(safe_output.exists())
            self.assertFalse(ledger_path.exists())

    def test_agent_image_digest_mismatch_precedes_ledger_and_bridge_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            paths["manifest"].chmod(0o600)
            expected_sha256 = hashlib.sha256(
                paths["container"].read_bytes()
            ).hexdigest()
            paths["container"].write_bytes(b"modified container")
            ledger_path = root / "new-ledger.sqlite3"

            with (
                mock.patch.dict(os.environ, {"SLURM_JOB_ID": "9001"}, clear=True),
                mock.patch.object(delegation.DelegationLedger, "register") as register,
                mock.patch("hpc_tools.restricted_launch.subprocess.Popen") as popen,
                self.assertRaisesRegex(ConfigError, "agent image SHA-256 mismatch"),
            ):
                restricted_launch.launch(
                    manifest_path=paths["manifest"],
                    ledger_path=ledger_path,
                    profile="cluster",
                    agent_image=paths["container"],
                    agent_image_sha256=expected_sha256,
                    agent_command=["codex-agent", "-"],
                    runtime_base=root,
                    config_path=paths["config"],
                )

            register.assert_not_called()
            popen.assert_not_called()
            self.assertFalse(ledger_path.exists())

    def test_parent_attempt_artifacts_snapshot_prompt_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, paths = self._fixture(Path(directory))
            prompt = Path(directory) / "task.md"
            prompt.write_text("bounded objective\n", encoding="utf-8")
            prompt.chmod(0o600)
            template = Path(directory) / "delegation-template.toml"
            template.write_text("template_version = 1\n", encoding="utf-8")
            template.chmod(0o600)
            materialization = delegation.ManifestMaterialization(
                template_path=template,
                template_sha256="a" * 64,
                template_version=1,
                manifest_path=runtime.manifest.source_path,
                manifest_sha256=runtime.manifest.digest,
            )
            with (
                mock.patch(
                    "hpc_tools.restricted_launch._read_image_text",
                    side_effect=["codex-cli 0.150.1\n", "model = 'test'\n"],
                ) as read_image,
                mock.patch(
                    "hpc_tools.restricted_launch._git_revision",
                    return_value={"commit": "abc", "dirty": False},
                ),
            ):
                artifacts = restricted_launch._prepare_agent_artifacts(
                    manifest=runtime.manifest,
                    policy=runtime.manifest.filesystem,
                    generation=1,
                    prompt_file=prompt,
                    agent_image=paths["container"],
                    expected_agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    verified_agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    controller_authority=runtime.controller_authority,
                    network_environment=restricted_launch.NetworkEnvironmentEvidence(
                        supplied=True,
                        sha256="b" * 64,
                    ),
                    manifest_materialization=materialization,
                )

            self.assertEqual("bounded objective\n", artifacts.prompt_path.read_text(encoding="utf-8"))
            provenance = json.loads(artifacts.provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(5, provenance["format_version"])
            self.assertEqual("codex-cli 0.150.1", provenance["codex"]["version"])
            self.assertEqual("abc", provenance["work_source"]["commit"])
            self.assertEqual(
                runtime.controller_authority.policy_sha256,
                provenance["controller_authority"]["policy_sha256"],
            )
            self.assertEqual(
                str(paths["config"]),
                provenance["controller_authority"]["config_path"],
            )
            self.assertEqual(
                hashlib.sha256(paths["container"].read_bytes()).hexdigest(),
                provenance["agent_image"]["sha256"],
            )
            self.assertEqual(
                provenance["agent_image"]["sha256"],
                provenance["agent_image"]["expected_sha256"],
            )
            self.assertEqual(
                {
                    "mode": "model-only",
                    "web_search": "disabled",
                    "command_network_access": False,
                    "environment": {"supplied": True, "sha256": "b" * 64},
                },
                provenance["network"],
            )
            self.assertEqual(
                materialization.public_summary(),
                provenance["manifest"]["materialization"],
            )
            self.assertEqual(
                [
                    "cat",
                    "/opt/hpc-tools/config/model-only.toml",
                ],
                read_image.call_args_list[1].args[2],
            )
            self.assertNotIn("proxy-secret", json.dumps(provenance))
            self.assertEqual("", artifacts.diagnostic_log.read_text(encoding="utf-8"))
            for path in (
                artifacts.provenance_path,
                artifacts.prompt_path,
                artifacts.event_log,
                artifacts.diagnostic_log,
            ):
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

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
                    {
                        "HOME",
                        "HPC_TOOLS_AGENT_NETWORK_MODE",
                        "HPC_TOOLS_MCP_SOCKET",
                        "PATH",
                        "LC_CTYPE",
                    }
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
                    agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    runtime_base=runtime_base,
                    config_path=paths["config"],
                    dry_run=True,
                )
            rendered = stdout.getvalue()
            self.assertEqual(0, result)
            self.assertIn("--containall", rendered)
            self.assertNotIn(str(paths["state"]), rendered)
            self.assertNotIn(str(runtime.ledger_path), rendered)

    def test_launcher_rejects_credit_budget_before_preparing_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            paths["manifest"].write_text(
                paths["manifest"].read_text(encoding="utf-8")
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
            with (
                mock.patch.dict(os.environ, {"SLURM_JOB_ID": "9001"}, clear=True),
                mock.patch(
                    "hpc_tools.restricted_launch._prepare_policy_paths"
                ) as prepare_paths,
                self.assertRaisesRegex(ConfigError, "sam_quote_format"),
            ):
                restricted_launch.launch(
                    manifest_path=paths["manifest"],
                    ledger_path=runtime.ledger_path,
                    profile="cluster",
                    agent_image=paths["container"],
                    agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    runtime_base=root / "runtime",
                    config_path=paths["config"],
                    dry_run=True,
                )

            prepare_paths.assert_not_called()

    def test_launcher_registers_one_host_cleanup_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            reaper = root / "hpc-agent-reap"
            reaper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            reaper.chmod(0o700)
            submitted = mock.Mock(returncode=0, stdout="7001;alpha\n", stderr="")
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            with (
                mock.patch("hpc_tools.restricted_launch.shutil.which", return_value=str(reaper)),
                mock.patch(
                    "hpc_tools.restricted_launch.subprocess.run",
                    return_value=submitted,
                ) as run,
                mock.patch.dict(
                    os.environ,
                    {"SLURM_JOB_ACCOUNT": "project", "SLURM_JOB_PARTITION": "batch"},
                    clear=True,
                ),
            ):
                first = restricted_launch._ensure_cleanup_job(
                    manifest=runtime.manifest,
                    ledger=ledger,
                    ledger_path=runtime.ledger_path,
                    profile="cluster",
                    parent_job_id="9001",
                )
                second = restricted_launch._ensure_cleanup_job(
                    manifest=runtime.manifest,
                    ledger=ledger,
                    ledger_path=runtime.ledger_path,
                    profile="cluster",
                    parent_job_id="9001",
                )

            self.assertEqual("7001", first)
            self.assertEqual(first, second)
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertIn("--dependency=afterany:9001", command)
            self.assertIn("--account=project", command)
            self.assertIn("--partition=batch", command)
            cleanup_script = paths["state"] / "parent-cleanup.sh"
            self.assertEqual(0o500, stat.S_IMODE(cleanup_script.stat().st_mode))
            self.assertIn("--parent-job-id 9001", cleanup_script.read_text(encoding="utf-8"))
            self.assertEqual("7001", ledger.cleanup_job_id(runtime.manifest))

    def test_launcher_requeues_only_the_bound_parent_and_records_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self._fixture(Path(directory))
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            ledger.begin_draining(runtime.manifest, reason="SIGUSR1")
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch(
                "hpc_tools.restricted_launch.subprocess.run", return_value=completed
            ) as run:
                result = restricted_launch._request_parent_requeue(
                    ledger=ledger,
                    manifest=runtime.manifest,
                    parent_job_id="9001",
                )

            self.assertEqual(0, result)
            run.assert_called_once_with(
                ["scontrol", "requeue", "9001"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                "continuation-pending",
                ledger.controller_summary(runtime.manifest)["state"],
            )

    def test_launcher_records_failed_requeue_as_terminal_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self._fixture(Path(directory))
            ledger = delegation.DelegationLedger(runtime.ledger_path)
            ledger.begin_draining(runtime.manifest, reason="SIGUSR1")
            completed = mock.Mock(returncode=1, stdout="", stderr="requeue denied")
            with mock.patch(
                "hpc_tools.restricted_launch.subprocess.run", return_value=completed
            ):
                result = restricted_launch._request_parent_requeue(
                    ledger=ledger,
                    manifest=runtime.manifest,
                    parent_job_id="9001",
                )

            controller = ledger.controller_summary(runtime.manifest)
            self.assertEqual(2, result)
            self.assertEqual("final", controller["state"])
            self.assertIn("timeout-requeue-failed", controller["reason"])

    def test_network_environment_is_allowlisted_and_hashed_without_disclosure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credential = root / "credential.env"
            credential.write_text("OPENAI_API_KEY=credential-secret\n", encoding="utf-8")
            credential.chmod(0o600)
            network = root / "network.env"
            network.write_text(
                "HTTPS_PROXY=https://proxy-secret@example.invalid:8443\n"
                "NO_PROXY=127.0.0.1,localhost\n"
                "SSL_CERT_FILE=/etc/ssl/certs/site.pem\n",
                encoding="utf-8",
            )
            network.chmod(0o600)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)

            generated, evidence = restricted_launch._materialize_agent_environment(
                runtime,
                credential_file=credential,
                network_file=network,
            )

            self.assertIsNotNone(generated)
            assert generated is not None
            self.assertEqual(0o600, stat.S_IMODE(generated.stat().st_mode))
            contents = generated.read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY=credential-secret", contents)
            self.assertIn("HTTPS_PROXY=https://proxy-secret", contents)
            self.assertTrue(evidence.supplied)
            expected_network = (
                "HTTPS_PROXY=https://proxy-secret@example.invalid:8443\n"
                "NO_PROXY=127.0.0.1,localhost\n"
                "SSL_CERT_FILE=/etc/ssl/certs/site.pem\n"
            ).encode("utf-8")
            self.assertEqual(
                hashlib.sha256(expected_network).hexdigest(), evidence.sha256
            )
            self.assertNotIn("proxy-secret", json.dumps(evidence.public_summary()))

    def test_network_environment_rejects_injection_and_arbitrary_names(self) -> None:
        rejected = (
            "APPTAINERENV_ESCAPE",
            "SINGULARITYENV_ESCAPE",
            "LD_PRELOAD",
            "BASH_ENV",
            "HPC_TOOLS_AGENT_NETWORK_MODE",
            "ARBITRARY",
        )
        for name in rejected:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "network.env"
                path.write_text(f"{name}=secret\n", encoding="utf-8")
                path.chmod(0o600)
                with self.assertRaisesRegex(ConfigError, "unsupported.*variable"):
                    restricted_launch._parse_environment_file(
                        path,
                        label="network environment file",
                        allowed_names=restricted_launch.NETWORK_ENV_NAMES,
                    )

        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "credential.env"
            credential.write_text(
                "OPENAI_API_KEY=secret\nHTTPS_PROXY=https://proxy.invalid\n",
                encoding="utf-8",
            )
            credential.chmod(0o600)
            with self.assertRaisesRegex(ConfigError, "unsupported.*HTTPS_PROXY"):
                restricted_launch._parse_environment_file(
                    credential,
                    label="agent environment file",
                    allowed_names=restricted_launch.AGENT_CREDENTIAL_ENV_NAMES,
                )

    def test_dry_run_uses_generated_env_file_without_printing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, paths = self._fixture(root)
            paths["manifest"].chmod(0o600)
            credential = root / "credential.env"
            credential.write_text("OPENAI_API_KEY=credential-secret\n", encoding="utf-8")
            credential.chmod(0o600)
            network = root / "network.env"
            network.write_text(
                "HTTPS_PROXY=https://proxy-secret@example.invalid\n",
                encoding="utf-8",
            )
            network.chmod(0o600)
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
                    agent_image_sha256=hashlib.sha256(
                        paths["container"].read_bytes()
                    ).hexdigest(),
                    agent_command=["codex-agent", "-"],
                    runtime_base=runtime_base,
                    agent_env_file=credential,
                    network_env_file=network,
                    config_path=paths["config"],
                    dry_run=True,
                )

            rendered = stdout.getvalue()
            self.assertEqual(0, result)
            self.assertIn("--env-file", rendered)
            self.assertIn("HPC_TOOLS_AGENT_NETWORK_MODE=model-only", rendered)
            self.assertNotIn("credential-secret", rendered)
            self.assertNotIn("proxy-secret", rendered)
            self.assertNotIn(str(credential), rendered)
            self.assertNotIn(str(network), rendered)

    def test_environment_filter_removes_credentials_and_apptainer_injection(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "SSH_AUTH_SOCK": "/tmp/agent",
                "OPENAI_API_KEY": "secret",
                "APPTAINERENV_ESCAPE": "value",
                "SINGULARITYENV_ESCAPE": "value",
                "HPC_TOOLS_AGENT_NETWORK_MODE": "model-live-search",
                "HTTPS_PROXY": "https://ambient-secret@example.invalid",
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
        self.assertNotIn("SINGULARITYENV_ESCAPE", filtered)
        self.assertNotIn("HPC_TOOLS_AGENT_NETWORK_MODE", filtered)
        self.assertNotIn("HTTPS_PROXY", filtered)

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
            ready = mcp_bridge.readiness_path(path)
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
            expected_pid = str(os.getpid())
            while not errors and time.monotonic() < deadline:
                try:
                    if ready.read_text(encoding="ascii").strip() == expected_pid:
                        break
                except FileNotFoundError:
                    pass
                time.sleep(0.01)
            if errors:
                server.join(timeout=1)
                if errors[0].errno == 1:
                    self.skipTest("sandbox disallows Unix-domain socket binding")
                raise errors[0]
            self.assertTrue(ready.exists(), "bridge did not publish readiness")
            self.assertEqual(expected_pid, ready.read_text(encoding="ascii").strip())
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
            self.assertFalse(path.exists())
            self.assertFalse(ready.exists())

    def test_launcher_requires_matching_bridge_readiness_marker(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            path = Path(directory) / "mcp.sock"
            ready = mcp_bridge.readiness_path(path)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path))
            ready.write_text("9999\n", encoding="ascii")
            bridge = mock.Mock(pid=1234, returncode=None)
            bridge.poll.return_value = None

            with (
                mock.patch(
                    "hpc_tools.restricted_launch.time.monotonic",
                    side_effect=[0.0, 0.0, 11.0],
                ),
                mock.patch("hpc_tools.restricted_launch.time.sleep"),
                self.assertRaisesRegex(
                    restricted_launch.ConfigError,
                    "bridge readiness marker",
                ),
            ):
                restricted_launch._wait_for_socket(path, bridge)

            listener.listen(1)
            ready.write_text("1234\n", encoding="ascii")
            restricted_launch._wait_for_socket(path, bridge)
            listener.close()


if __name__ == "__main__":
    unittest.main()
