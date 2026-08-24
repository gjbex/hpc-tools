from __future__ import annotations

from test_mcp_fixtures import *
from hpc_tools import submissions
from hpc_tools.config import ConfigError
from hpc_tools.execution import executor_scope


class McpServerFeatureTests(McpFixtures, unittest.TestCase):
    def test_remote_read_tool_dry_run_returns_structured_ssh_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            result = mcp_server.hpc_jobs(config=str(config_path), cluster="wice", dry_run=True)

        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["dry_run"])
        self.assertIn("squeue -M wice", result["command"])
        self.assertIn("ssh -x genius", result["ssh_command"])

    def test_remote_read_tool_captures_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="JOBID\n123\n", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed) as remote:
                result = mcp_server.hpc_job(config=str(config_path), jobid="123", cluster="wice")

        self.assertEqual(result["stdout"], "JOBID\n123\n")
        self.assertEqual(result["stderr"], "")
        self.assertFalse(result["dry_run"])
        self.assertIn("squeue -M wice -j 123", result["command"])
        remote.assert_called_once()

    def test_remote_read_tool_supports_local_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            with executor_scope("local"):
                result = mcp_server.hpc_jobs(
                    config=str(config_path),
                    cluster="wice",
                    dry_run=True,
                )

        self.assertEqual(result["executor"], "local")
        self.assertIn("bash -l -c", result["execution_command"])
        self.assertIsNone(result["ssh_command"])

    def test_cancel_job_requires_confirm_and_non_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            with mock.patch("hpc_tools.mcp.common.run_command_capture") as execute:
                unconfirmed = mcp_server.hpc_cancel_job(
                    "12345",
                    config=str(config_path),
                    cluster="wice",
                    dry_run=False,
                )
                confirmed_preview = mcp_server.hpc_cancel_job(
                    "12345",
                    config=str(config_path),
                    cluster="wice",
                    confirm=True,
                )

        self.assertFalse(unconfirmed["executed"])
        self.assertTrue(unconfirmed["confirm_required"])
        self.assertFalse(confirmed_preview["executed"])
        self.assertTrue(confirmed_preview["dry_run"])
        execute.assert_not_called()

    def test_cancel_job_executes_and_logs_matching_submission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            log_path = root / "submissions.jsonl"
            submissions.append_event(
                {
                    "event": "submitted",
                    "run_id": "run-1",
                    "profile": "genius",
                    "job_id": "12345",
                    "cluster": "wice",
                    "jobscript": "job.slurm",
                    "remote_directory": "$VSC_DATA/Projects/demo",
                },
                path=log_path,
            )
            completed = mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch(
                "hpc_tools.mcp.common.run_command_capture",
                return_value=completed,
            ) as execute:
                result = mcp_server.hpc_cancel_job(
                    "12345",
                    config=str(config_path),
                    cluster="wice",
                    reason="superseded",
                    log=str(log_path),
                    dry_run=False,
                    confirm=True,
                )

            events = submissions.read_events(log_path)

        self.assertTrue(result["executed"])
        self.assertEqual(result["logged_run_ids"], ["run-1"])
        self.assertEqual(result["command"], "scancel -M wice 12345")
        self.assertEqual(events[-1]["event"], "cancel_requested")
        self.assertEqual(events[-1]["reason"], "superseded")
        self.assertIsNone(result["log_error"])
        execute.assert_called_once()

    def test_cancel_job_preserves_success_when_local_log_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch(
                "hpc_tools.mcp.common.run_command_capture",
                return_value=completed,
            ), mock.patch(
                "hpc_tools.mcp.tools.submissions.append_cancel_requested_events",
                side_effect=OSError("read-only log"),
            ):
                result = mcp_server.hpc_cancel_job(
                    "12345",
                    config=str(config_path),
                    dry_run=False,
                    confirm=True,
                )

        self.assertTrue(result["executed"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["logged_run_ids"], [])
        self.assertEqual(result["log_error"], "read-only log")

    def test_cancel_job_rejects_non_job_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            with self.assertRaises(ConfigError):
                mcp_server.hpc_cancel_job(
                    "--user=someone",
                    config=str(config_path),
                    dry_run=False,
                    confirm=True,
                )

    def test_status_tool_returns_structured_combined_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed_quota = mock.Mock(
                returncode=0,
                stdout="file system: $VSC_DATA\nBlocks: 573G* of 600G\n",
                stderr="",
            )
            completed_balance = mock.Mock(
                returncode=0,
                stdout="ID Name Balance\n142 geniusdefaultslurmaccount 0\n",
                stderr="",
            )

            with mock.patch("hpc_tools.commands.slurm._fetch_status_page", return_value="All systems running fine"), \
                    mock.patch("hpc_tools.commands.slurm.run_command_capture", side_effect=[completed_quota, completed_balance]), \
                    mock.patch("hpc_tools.commands.slurm.submissions.read_events", return_value=[]):
                result = mcp_server.hpc_status(config=str(config_path))

        self.assertTrue(result["ok"])
        self.assertEqual(result["failures"], 0)
        self.assertEqual([section["title"] for section in result["sections"]], [
            "status page",
            "quota",
            "balance",
            "submissions",
        ])
        self.assertIn("All systems running fine", result["sections"][0]["lines"])
        self.assertIn("Blocks: 573G* of 600G", result["sections"][1]["lines"])
        self.assertIn("geniusdefaultslurmaccount", "\n".join(result["sections"][2]["lines"]))
        self.assertEqual(result["submissions"], [])

    def test_slurm_limits_tool_returns_best_effort_parsed_fields(self) -> None:
        stdout = textwrap.dedent(
            """
            ## controller
            ClusterName             = wice
            MaxArraySize            = 1001

            ## partitions
            PartitionName=batch
               AllowGroups=ALL AllowAccounts=ALL DenyQos=lp_big_tier2
               DefaultTime=01:00:00 MaxTime=3-00:00:00 State=UP TotalCPUs=12384 TotalNodes=172
               DefMemPerCPU=3400 MaxMemPerCPU=3400
               TRES=cpu=12384,mem=42793600M,node=172,billing=31533

            PartitionName=gpu_a100
               DefaultTime=01:00:00 MaxTime=3-00:00:00 State=UP TotalCPUs=288 TotalNodes=4
               TRES=cpu=288,mem=2016000M,node=4,gres/gpu=16,gres/gpu:a100-sxm4-80gb=16

            ## partition-summary
            CLUSTER: wice
            PARTITION|AVAIL|TIMELIMIT|NODES|CPUS|MEMORY|GRES|AVAIL_FEATURES
            batch*|up|3-00:00:00|172|72|248800|(null)|icelake
            gpu_a100|up|3-00:00:00|4|72|504000|gpu:a100-sxm4-80gb:4(S:0-3)|icelake

            ## partition-nodes
            CLUSTER: wice
            NODELIST|CPUS|MEMORY|GRES|STATE
            l33c20n1|72|248800|(null)|idle

            ## qos
            normal||500|||||
            long||20|node=10||||7-00:00:00

            ## associations
            wice|lpt2_sysadmin|vsc30140||lpt2_sysadmin|||||||
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout=stdout, stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed):
                result = mcp_server.hpc_slurm_limits(config=str(config_path), cluster="wice")

        self.assertEqual(result["parse_warnings"], [])
        self.assertEqual(result["parsed"]["controller"]["ClusterName"], "wice")
        self.assertEqual(result["parsed"]["controller"]["MaxArraySize"], "1001")
        partitions = {partition["PartitionName"]: partition for partition in result["parsed"]["partitions"]}
        self.assertEqual(partitions["batch"]["MaxTime"], "3-00:00:00")
        self.assertFalse(partitions["batch"]["has_gpu"])
        self.assertTrue(partitions["gpu_a100"]["has_gpu"])
        self.assertEqual(result["parsed"]["partition_summary"][0]["partition"], "batch*")
        self.assertEqual(result["parsed"]["partition_summary"][0]["nodes"], 172)
        self.assertEqual(result["parsed"]["partition_nodes"][0]["state"], "idle")
        self.assertEqual(result["parsed"]["qos"][0]["name"], "normal")
        self.assertEqual(result["parsed"]["associations"][0]["account"], "lpt2_sysadmin")

    def test_module_spider_tool_searches_remote_lmod_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(
                returncode=0,
                stdout=(
                    "DMTCP: DMTCP/3.0.0-GCCcore-12.3.0\n"
                    "  You will need to load all module(s) on any one of the lines below.\n"
                    "    cluster/wice/batch_long\n"
                    "    cluster/genius/batch_skylake\n"
                ),
                stderr="",
            )

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed) as remote:
                result = mcp_server.hpc_module_spider(
                    config=str(config_path),
                    name="DMTCP; rm -rf /",
                )

        self.assertIn("DMTCP/3.0.0-GCCcore-12.3.0", result["stdout"])
        self.assertIn("module spider 'DMTCP; rm -rf /' 2>&1", result["command"])
        self.assertEqual(result["parsed"]["modules"], ["DMTCP/3.0.0-GCCcore-12.3.0"])
        self.assertEqual(result["parsed"]["availability_contexts"], [
            "cluster/genius/batch_skylake",
            "cluster/wice/batch_long",
        ])
        self.assertEqual(result["parse_warnings"], [])
        self.assertFalse(result["dry_run"])
        remote.assert_called_once()

    def test_read_only_tools_do_not_write_local_or_remote_state_when_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            log_path = root / "hpc-tools" / "submissions.jsonl"

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ), mock.patch("hpc_tools.mcp.common.run_command_capture") as remote:
                jobs = mcp_server.hpc_jobs(cluster="wice", dry_run=True)
                hardware_sources = mcp_server.hpc_hardware_sources()
                active = mcp_server.hpc_submissions_list()

        self.assertTrue(jobs["dry_run"])
        self.assertEqual(hardware_sources["profile"], "genius")
        self.assertEqual(active["submissions"], [])
        self.assertFalse(log_path.exists())
        remote.assert_not_called()

    def test_references_create_requires_confirm_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                preview = mcp_server.hpc_references_create("baseline")
                self.assertTrue(preview["confirm_required"])
                self.assertFalse((root / "hpc-tools" / "reference-sets" / "baseline").exists())

                result = mcp_server.hpc_references_create("baseline", confirm=True)

        self.assertTrue(result["created"])
        self.assertEqual(result["reference_set"]["name"], "baseline")
        self.assertFalse(result["confirm_required"])

    def test_references_attach_requires_confirm_before_config_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self._write_config(root)
            self._write_reference_set(root, "baseline")

            with mock.patch.dict(
                "os.environ",
                {"HPC_TOOLS_CONFIG": str(config_path), "XDG_CONFIG_HOME": str(root)},
                clear=False,
            ):
                preview = mcp_server.hpc_references_attach("baseline")
                self.assertTrue(preview["confirm_required"])
                self.assertNotIn("reference_set", config_path.read_text(encoding="utf-8"))

                result = mcp_server.hpc_references_attach("baseline", confirm=True)

                self.assertTrue(result["attached"])
                self.assertIn('reference_set = "baseline"', config_path.read_text(encoding="utf-8"))

    def test_submissions_close_requires_confirm_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "submissions.jsonl"

            preview = mcp_server.hpc_submissions_close(
                "run-1",
                reason="done",
                log=str(log_path),
            )
            self.assertTrue(preview["confirm_required"])
            self.assertFalse(log_path.exists())

            result = mcp_server.hpc_submissions_close(
                "run-1",
                reason="done",
                log=str(log_path),
                confirm=True,
            )

            self.assertTrue(result["appended"])
            self.assertIn('"event": "closed"', log_path.read_text(encoding="utf-8"))

    def test_write_probe_requires_confirm_before_writing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"

            preview = mcp_server.hpc_write_probe(output=str(output), account="proj")
            self.assertTrue(preview["confirm_required"])
            self.assertIn("#SBATCH --account=proj", preview["contents"])
            self.assertFalse(output.exists())

            result = mcp_server.hpc_write_probe(
                output=str(output),
                account="proj",
                confirm=True,
            )

            self.assertTrue(result["written"])
            self.assertIn("#SBATCH --account=proj", output.read_text(encoding="utf-8"))

    def test_write_container_requires_confirm_before_writing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"

            preview = mcp_server.hpc_write_container(output=str(output))
            self.assertTrue(preview["confirm_required"])
            self.assertIn("create_apptainer_container.slurm", preview["files"])
            self.assertFalse(output.exists())

            result = mcp_server.hpc_write_container(output=str(output), confirm=True)

            self.assertTrue(result["written"])
            self.assertTrue((output / "create_apptainer_container.slurm").exists())

    def test_install_probe_preview_does_not_execute_without_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))

            with mock.patch("hpc_tools.mcp.common.run_command_capture") as remote:
                result = mcp_server.hpc_install_probe(
                    config=str(config_path),
                    directory="$VSC_DATA/probes",
                    account="proj",
                    dry_run=False,
                )

        self.assertTrue(result["confirm_required"])
        self.assertFalse(result["executed"])
        self.assertIn("cat > hardware-probe.slurm", result["command"])
        remote.assert_not_called()

    def test_install_container_executes_only_with_confirm_and_not_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = self._write_config(Path(directory))
            completed = mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch("hpc_tools.mcp.common.run_command_capture", return_value=completed) as remote:
                result = mcp_server.hpc_install_container(
                    config=str(config_path),
                    directory="$VSC_DATA/containers",
                    confirm=True,
                    dry_run=False,
                )

        self.assertTrue(result["executed"])
        self.assertFalse(result["dry_run"])
        self.assertIn("cat > create_apptainer_container.slurm", result["command"])
        remote.assert_called_once()
