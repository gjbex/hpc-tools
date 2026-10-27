from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from hpc_tools import mcp_bridge


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp extra is not installed")
class CreditBudgetAcceptanceTests(unittest.TestCase):
    """Exercise the delegated credit path through the real MCP transports."""

    def test_real_stdio_bridge_accepts_boundary_and_rejects_next_minor_unit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="hpc-credit-acceptance-") as directory:
            root = Path(directory)
            paths = self._write_fixture(root)
            socket_directory = root / "socket"
            socket_directory.mkdir(mode=0o700)
            socket_path = socket_directory / "mcp.sock"
            environment = os.environ.copy()
            environment.pop("PYTHONUNBUFFERED", None)
            environment.update(
                {
                    "HPC_TOOLS_PARENT_JOB_ID": "9001",
                    "HPC_TOOLS_ACCEPTANCE_QUOTE_LOG": str(paths["quote_log"]),
                    "HPC_TOOLS_ACCEPTANCE_SBATCH_LOG": str(paths["sbatch_log"]),
                    "PATH": f"{paths['bin']}:{environment.get('PATH', '')}",
                    "XDG_CONFIG_HOME": str(paths["config_home"]),
                }
            )
            server_command = [
                sys.executable,
                "-m",
                "hpc_tools.mcp_server",
                "--executor",
                "local",
                "--preset",
                "slurm-job",
                "--profile",
                "example",
                "--config",
                str(paths["config"]),
                "--delegation",
                str(paths["manifest"]),
                "--ledger",
                str(paths["ledger"]),
            ]
            bridge = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "hpc_tools.mcp_bridge",
                    "serve",
                    "--socket",
                    str(socket_path),
                    "--",
                    *server_command,
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self._wait_for_bridge(bridge, socket_path)
                self.assertEqual(0o600, stat.S_IMODE(socket_path.stat().st_mode))
                observations = asyncio.run(
                    asyncio.wait_for(
                        self._exercise_protocol(socket_path, environment, paths),
                        timeout=30,
                    )
                )
                bridge.wait(timeout=10)
            finally:
                if bridge.poll() is None:
                    bridge.terminate()
                    try:
                        bridge.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        bridge.kill()
                        bridge.wait(timeout=5)

            diagnostics = bridge.stderr.read() if bridge.stderr is not None else ""
            self.assertEqual(0, bridge.returncode, diagnostics)
            self.assertFalse(socket_path.exists())
            self.assertFalse(mcp_bridge.readiness_path(socket_path).exists())

            exact = observations["exact"]
            replay = observations["replay"]
            denied = observations["denied"]
            runtime = observations["runtime"]
            self.assertTrue(exact["allowed"])
            self.assertTrue(exact["executed"])
            self.assertTrue(exact["ledger_recorded"])
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["executed"])
            self.assertFalse(denied["allowed"])
            self.assertEqual("budget.total_credits", denied["denial"]["code"])

            usage = runtime["delegation"]["usage"]
            self.assertEqual(1, usage["used_submissions"])
            self.assertEqual(1, usage["remaining"]["max_submissions"])
            self.assertEqual(2, usage["requested_resources"]["nodes"])
            self.assertEqual(2, usage["remaining"]["max_total_nodes"])
            self.assertEqual(
                {"value": 10, "scale": 0, "unit": "credits"},
                usage["quoted_credit"]["consumed_quoted_maximum"],
            )
            self.assertEqual(
                {"value": 0, "scale": 0, "unit": "credits"},
                usage["quoted_credit"]["remaining_quoted_maximum"],
            )

            quote_calls = paths["quote_log"].read_text(encoding="utf-8").splitlines()
            sbatch_calls = paths["sbatch_log"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(quote_calls))
            self.assertIn("--array 0-1", quote_calls[0])
            self.assertIn("--nodes 1", quote_calls[0])
            self.assertEqual(3, len(sbatch_calls))
            self.assertEqual(2, sum("--test-only" in call for call in sbatch_calls))
            self.assertEqual(1, sum("--test-only" not in call for call in sbatch_calls))
            submitted = next(call for call in sbatch_calls if "--test-only" not in call)
            self.assertEqual(quote_calls[0].removeprefix("sbatch "), submitted)

            public_payload = json.dumps(observations, sort_keys=True)
            for protected in (paths["manifest"], paths["ledger"]):
                self.assertNotIn(str(protected), public_payload)
            public_state = json.dumps(
                {"denied": denied, "runtime": runtime}, sort_keys=True
            )
            self.assertNotIn(str(paths["state"]), public_state)
            self.assertNotIn(str(paths["quote_helper"]), public_state)

    async def _exercise_protocol(
        self,
        socket_path: Path,
        environment: dict[str, str],
        paths: dict[str, Path],
    ) -> dict[str, object]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "hpc_tools.mcp_bridge",
                "connect",
                "--socket",
                str(socket_path),
            ],
            env=environment,
            cwd=str(ROOT),
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                resources = await session.list_resources()
                self.assertEqual(
                    {
                        "hpc_jobs",
                        "hpc_job",
                        "hpc_job_accounting",
                        "hpc_cancel_job",
                        "hpc_quote_job",
                        "hpc_validate_job",
                        "hpc_submit_job",
                    },
                    {tool.name for tool in tools.tools},
                )
                self.assertEqual(
                    {
                        "hpc://runtime",
                        "hpc://cluster/hardware",
                        "hpc://cluster/slurm",
                        "hpc://cluster/storage",
                    },
                    {str(resource.uri) for resource in resources.resources},
                )

                exact_arguments = {
                    "jobscript": "job.sh",
                    "directory": str(paths["run"]),
                    "container": str(paths["container"]),
                    "idempotency_key": "exact-boundary",
                    "account": "proj",
                    "array": "0-1",
                    "cluster": "example-cluster",
                    "job_name": "exact",
                    "nodes": "1",
                    "partition": "batch",
                }
                exact_quote = await self._call_tool(
                    session, "hpc_quote_job", exact_arguments
                )
                self.assertEqual(
                    {"value": 10, "scale": 0, "unit": "credits"},
                    exact_quote["quote_evidence"]["quoted_cost"],
                )
                exact_validation = await self._call_tool(
                    session,
                    "hpc_validate_job",
                    exact_arguments
                    | {"quote_evidence": exact_quote["quote_evidence"]},
                )
                submit_arguments = exact_arguments | {
                    "quote_evidence": exact_quote["quote_evidence"],
                    "validation_evidence": exact_validation["validation_evidence"],
                    "dry_run": False,
                }
                exact = await self._call_tool(
                    session, "hpc_submit_job", submit_arguments
                )
                replay = await self._call_tool(
                    session, "hpc_submit_job", submit_arguments
                )

                over_arguments = exact_arguments | {
                    "array": None,
                    "idempotency_key": "one-minor-unit-over",
                    "job_name": "over",
                }
                over_quote = await self._call_tool(
                    session, "hpc_quote_job", over_arguments
                )
                self.assertEqual(
                    {"value": 1, "scale": 0, "unit": "credits"},
                    over_quote["quote_evidence"]["quoted_cost"],
                )
                over_validation = await self._call_tool(
                    session,
                    "hpc_validate_job",
                    over_arguments
                    | {"quote_evidence": over_quote["quote_evidence"]},
                )
                denied = await self._call_tool(
                    session,
                    "hpc_submit_job",
                    over_arguments
                    | {
                        "quote_evidence": over_quote["quote_evidence"],
                        "validation_evidence": over_validation[
                            "validation_evidence"
                        ],
                        "dry_run": False,
                    },
                )
                runtime_result = await session.read_resource("hpc://runtime")
                runtime = json.loads(runtime_result.contents[0].text)
                return {
                    "exact": exact,
                    "replay": replay,
                    "denied": denied,
                    "runtime": runtime,
                }

    async def _call_tool(self, session: object, name: str, arguments: dict) -> dict:
        result = await session.call_tool(name, arguments)  # type: ignore[attr-defined]
        self.assertFalse(result.isError, result.content)
        self.assertIsNotNone(result.structuredContent)
        payload = result.structuredContent
        assert payload is not None
        self.assertIn("result", payload)
        return payload["result"]

    def _wait_for_bridge(
        self,
        bridge: subprocess.Popen[str],
        socket_path: Path,
    ) -> None:
        ready = mcp_bridge.readiness_path(socket_path)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if ready.is_file() and socket_path.exists():
                return
            if bridge.poll() is not None:
                diagnostics = bridge.stderr.read() if bridge.stderr is not None else ""
                self.fail(f"MCP bridge exited before becoming ready: {diagnostics}")
            time.sleep(0.02)
        self.fail("MCP bridge did not publish readiness within 10 seconds")

    def _write_fixture(self, root: Path) -> dict[str, Path]:
        paths = {
            name: root / name
            for name in ("state", "work", "output", "input", "bin")
        }
        for path in paths.values():
            path.mkdir(mode=0o700)
        config_home = root / "config-home"
        (config_home / "hpc-tools").mkdir(parents=True, mode=0o700)
        paths["config_home"] = config_home

        run = paths["work"] / "run"
        run.mkdir()
        (run / "job.sh").write_text("#!/bin/sh\necho accepted\n", encoding="utf-8")
        paths["run"] = run
        container = root / "worker.sif"
        container.write_bytes(b"test container")
        container.chmod(0o600)
        paths["container"] = container
        apptainer = root / "apptainer"
        apptainer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        apptainer.chmod(0o700)

        quote_log = root / "quote.log"
        sbatch_log = root / "sbatch.log"
        paths["quote_log"] = quote_log
        paths["sbatch_log"] = sbatch_log
        quote_helper = root / "quote-helper"
        quote_helper.write_text(
            textwrap.dedent(
                """
                #!/bin/sh
                set -eu
                printf '%s\n' "$*" >> "$HPC_TOOLS_ACCEPTANCE_QUOTE_LOG"
                cost=1
                case " $* " in
                  *" --job-name exact "*) cost=10 ;;
                esac
                printf '{"format_version":1,"maximum_cost":{"value":%s,"scale":0,"unit":"credits"}}\n' "$cost"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        quote_helper.chmod(0o700)
        paths["quote_helper"] = quote_helper

        sbatch = paths["bin"] / "sbatch"
        sbatch.write_text(
            textwrap.dedent(
                """
                #!/bin/sh
                set -eu
                printf '%s\n' "$*" >> "$HPC_TOOLS_ACCEPTANCE_SBATCH_LOG"
                case " $* " in
                  *" --test-only "*) printf 'sbatch: Job 7001 to start later\n' ;;
                  *) printf 'Submitted batch job 7001 on cluster example-cluster\n' ;;
                esac
                """
            ).lstrip(),
            encoding="utf-8",
        )
        sbatch.chmod(0o700)

        reference_root = root / "references"
        reference_root.mkdir()
        for name in ("hardware", "slurm", "storage"):
            reference = reference_root / f"{name}.md"
            reference.write_text(f"# {name}\n", encoding="utf-8")
            paths[name] = reference

        config = root / "config.toml"
        config.write_text(
            textwrap.dedent(
                f"""
                default_profile = "example"

                [profiles.example]
                login_shell = ["/bin/sh", "-c"]
                hardware_reference = "{paths['hardware']}"
                slurm_reference = "{paths['slurm']}"
                storage_reference = "{paths['storage']}"
                sam_quote_command = "{quote_helper}"
                sam_quote_format = "hpc-tools-credit-quote-v1"
                default_cluster = "example-cluster"

                [profiles.example.capabilities]
                version = 1
                max_level = "job-lifecycle"
                scopes = [
                    "accounting.read",
                    "delegation-ledger.read",
                    "job.validate",
                    "local-state.write",
                    "submission-record.write",
                ]

                [profiles.example.capabilities.remote_roots]
                list = []
                read = []
                write = []
                delete = []
                install = []
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        config.chmod(0o600)
        paths["config"] = config

        manifest = root / "delegation.toml"
        manifest.write_text(
            textwrap.dedent(
                f"""
                format_version = 4
                id = "credit-acceptance"
                issuer = "acceptance-test"
                profile = "example"
                parent_job_id = "9001"
                issued_at = "2026-01-01T00:00:00Z"
                expires_at = "2099-01-01T00:00:00Z"

                [network]
                mode = "model-only"

                [allowed]
                accounts = ["proj"]
                clusters = ["example-cluster"]
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

                [per_job_limits]
                nodes = 1
                array_tasks = 2

                [budget]
                max_submissions = 2
                max_active_jobs = 2
                max_total_nodes = 4
                max_total_array_tasks = 4

                [credit_budget]
                unit = "credits"
                scale = 0
                maximum_total = 10
                maximum_per_job = 10
                quote_ttl_seconds = 300
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        manifest.chmod(0o600)
        paths["manifest"] = manifest
        paths["ledger"] = root / "ledger.sqlite3"
        return paths
