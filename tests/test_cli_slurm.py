from __future__ import annotations

from test_cli_fixtures import *


class CliCoreTests(unittest.TestCase):
    def test_squeue_uses_user_environment_remotely(self) -> None:
        command = slurm.squeue_user_command("wice")

        self.assertIn("-M wice", command)
        self.assertIn("-u $USER", command)
        self.assertIn("-o", command)

    def test_jobs_parser_defaults_to_all_clusters(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["jobs"])

        self.assertEqual(args.cluster, "all")
        self.assertIn("-M all", slurm.squeue_user_command(args.cluster))

    def test_jobs_parser_accepts_cluster_override(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["jobs", "--cluster", "wice"])

        self.assertEqual(args.cluster, "wice")
        self.assertIn("-M wice", slurm.squeue_user_command(args.cluster))

    def test_squeue_job_command_uses_standard_status_format(self) -> None:
        command = slurm.squeue_job_command("12345", "wice")

        self.assertEqual(
            command,
            "squeue -M wice -j 12345 -o '%.18i %.9P %.32j %.8T %.10M %.10l %.6D %R'",
        )

    def test_job_parser_defaults_to_all_clusters(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["job", "12345"])

        self.assertIs(args.handler, cmd_job)
        self.assertEqual(args.jobid, "12345")
        self.assertEqual(args.cluster, "all")
        self.assertIn("-M all", slurm.squeue_job_command(args.jobid, args.cluster))

    def test_job_parser_accepts_cluster_override(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["job", "12345", "--cluster", "wice"])

        self.assertIs(args.handler, cmd_job)
        self.assertEqual(args.cluster, "wice")
        self.assertIn("-M wice", slurm.squeue_job_command(args.jobid, args.cluster))

    def test_slurm_limits_command_covers_controller_partition_qos_and_assoc(self) -> None:
        command = slurm.slurm_limits_command(cluster="wice", partition="batch", qos="normal")

        self.assertIn("## controller", command)
        self.assertIn("scontrol -M wice show config", command)
        self.assertIn("MaxArraySize", command)
        self.assertIn("## partitions", command)
        self.assertIn("scontrol -M wice show partition batch", command)
        self.assertIn("sinfo -M wice -p batch -o", command)
        self.assertIn("sinfo -M wice -p batch -N -o", command)
        self.assertIn("sacctmgr -n -P show qos normal", command)
        self.assertIn("sacctmgr -n -P show assoc where cluster=wice user=$USER partition=batch", command)
        self.assertIn("MaxSubmitJobsPU", command)

    def test_slurm_limits_parser_accepts_filters(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            ["slurm-limits", "--cluster", "wice", "--partition", "batch", "--qos", "normal"]
        )

        self.assertIs(args.handler, cmd_slurm_limits)
        self.assertEqual(args.cluster, "wice")
        self.assertEqual(args.partition, "batch")
        self.assertEqual(args.qos, "normal")

    def test_submit_test_only_command(self) -> None:
        command = slurm.submit_command("job.slurm", directory="$VSC_DATA/Projects/demo", test_only=True)

        self.assertEqual(command, "cd $VSC_DATA/Projects/demo && sbatch --test-only job.slurm")

    def test_submit_command_accepts_overrides(self) -> None:
        command = slurm.submit_command(
            "job.slurm",
            directory="$VSC_DATA/Projects/demo",
            overrides={
                "account": "proj 123",
                "array": "4",
                "cluster": "wice",
                "cpus_per_task": "4",
                "gpus_per_node": "1",
                "job_name": "pilot",
                "reservation": "pilot",
                "time": "00:05:00",
            },
        )

        self.assertEqual(
            command,
            "cd $VSC_DATA/Projects/demo && sbatch "
            "--account 'proj 123' --array 4 --clusters wice "
            "--cpus-per-task 4 --gpus-per-node 1 --job-name pilot "
            "--reservation pilot --time 00:05:00 job.slurm",
        )

    def test_submit_parser_accepts_slurm_overrides(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "submit",
                "--array",
                "4",
                "-M",
                "wice",
                "-p",
                "batch",
                "-c",
                "36",
                "--gpus-per-node",
                "2",
                "--reservation",
                "pilot",
                "--export",
                "JULIA_SIZE=16384",
                "job.slurm",
            ]
        )

        self.assertIs(args.handler, cmd_submit)
        self.assertEqual(args.array, "4")
        self.assertEqual(args.cluster, "wice")
        self.assertEqual(args.partition, "batch")
        self.assertEqual(args.cpus_per_task, "36")
        self.assertEqual(args.gpus_per_node, "2")
        self.assertEqual(args.reservation, "pilot")
        self.assertEqual(args.export, "JULIA_SIZE=16384")

    def test_submit_parser_accepts_validate_first(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["submit", "--validate-first", "job.slurm"])

        self.assertIs(args.handler, cmd_submit)
        self.assertTrue(args.validate_first)
        self.assertFalse(args.test_only)

    def test_submit_validate_first_runs_test_then_submit(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(
            [
                "submit",
                "--validate-first",
                "--directory",
                "$VSC_DATA/Projects/demo",
                "--array",
                "4",
                "job.slurm",
            ]
        )
        validation = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="sbatch: Job 1 to start later\n",
            stderr="",
        )
        submitted = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Submitted batch job 60351238 on cluster wice\n",
            stderr="",
        )

        stdout = io.StringIO()
        with mock.patch("hpc_tools.commands.slurm.run_remote_capture", side_effect=[validation, submitted]) as run_remote_capture, \
             mock.patch("hpc_tools.commands.slurm.submissions.append_event") as append_event, \
             contextlib.redirect_stdout(stdout):
            result = cmd_submit(args, profile)

        self.assertEqual(result, 0)
        self.assertEqual(
            run_remote_capture.call_args_list[0].args[1],
            "cd $VSC_DATA/Projects/demo && sbatch --test-only --array 4 job.slurm",
        )
        self.assertEqual(
            run_remote_capture.call_args_list[1].args[1],
            "cd $VSC_DATA/Projects/demo && sbatch --array 4 job.slurm",
        )
        self.assertEqual(append_event.call_args.args[0]["job_id"], "60351238")

    def test_submit_validate_first_stops_on_validation_failure(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["submit", "--validate-first", "job.slurm"])
        validation = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="allocation failure: Requested node configuration is not available\n",
        )

        stderr = io.StringIO()
        with mock.patch("hpc_tools.commands.slurm.run_remote_capture", return_value=validation) as run_remote_capture, \
             mock.patch("hpc_tools.commands.slurm.submissions.append_event") as append_event, \
             contextlib.redirect_stderr(stderr):
            result = cmd_submit(args, profile)

        self.assertEqual(result, 1)
        self.assertEqual(len(run_remote_capture.call_args_list), 1)
        self.assertIn("--test-only", run_remote_capture.call_args.args[1])
        append_event.assert_not_called()

    def test_log_submission_appends_submitted_event(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(
            [
                "submit",
                "--directory",
                "$VSC_DATA/Projects/demo",
                "--array",
                "4",
                "--reservation",
                "pilot",
                "job.slurm",
            ]
        )

        with mock.patch("hpc_tools.commands.slurm.submissions.append_event") as append_event:
            _log_submission(
                profile=profile,
                args=args,
                command="cd $VSC_DATA/Projects/demo && sbatch --array 4 --reservation pilot job.slurm",
                overrides={"array": "4", "reservation": "pilot"},
                sbatch_output="Submitted batch job 60351238 on cluster wice\n",
            )

        event = append_event.call_args.args[0]
        self.assertEqual(event["event"], "submitted")
        self.assertEqual(event["job_id"], "60351238")
        self.assertEqual(event["cluster"], "wice")
        self.assertEqual(event["remote_directory"], "$VSC_DATA/Projects/demo")
        self.assertEqual(event["jobscript"], "job.slurm")
        self.assertEqual(event["slurm_overrides"], {"array": "4", "reservation": "pilot"})

    def test_status_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["status"])

        self.assertIs(args.handler, cmd_status)

    def test_status_command_shows_full_report(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["status"])

        html_body = """\
        <html>
          <head><title>Tier 2 Leuven status</title></head>
          <body>
            <h1>All systems running fine</h1>
            <p>No maintenance planned currently.</p>
          </body>
        </html>
        """
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = html_body.encode("utf-8")
        response.headers.get_content_charset.return_value = "utf-8"

        with mock.patch("hpc_tools.commands.slurm.urlopen", return_value=response) as urlopen, \
             mock.patch("hpc_tools.commands.slurm.run_remote_capture") as run_remote_capture, \
             mock.patch("hpc_tools.commands.slurm.submissions.read_events", return_value=[]) as read_events:
            run_remote_capture.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="file system: $VSC_DATA\nBlocks: 573G* of 600G\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="ID Name Balance Reserved Available\n142 geniusdefaultslurmaccount 0 0 0\n", stderr=""),
            ]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = args.handler(args, profile)

        self.assertEqual(result, 0)
        self.assertEqual(urlopen.call_args.args[0], profile.status_url)
        self.assertEqual([call.args[1] for call in run_remote_capture.call_args_list], ["myquota", "sam-balance"])
        read_events.assert_called_once()
        text = stdout.getvalue()
        self.assertIn("== status page ==", text)
        self.assertIn("Tier 2 Leuven status", text)
        self.assertIn("All systems running fine", text)
        self.assertIn("No maintenance planned currently.", text)
        self.assertIn("== quota ==", text)
        self.assertIn("file system: $VSC_DATA", text)
        self.assertIn("Blocks: 573G* of 600G", text)
        self.assertIn("== balance ==", text)
        self.assertIn("geniusdefaultslurmaccount", text)
        self.assertIn("== submissions ==", text)
        self.assertIn("No submissions.", text)

    def test_status_command_shows_full_report_with_issues(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["status"])

        html_body = """\
        <html>
          <body>
            <h1>Service update</h1>
            <p>Planned maintenance on 2026-06-20.</p>
            <p>Minor incident on the login node.</p>
          </body>
        </html>
        """
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = html_body.encode("utf-8")
        response.headers.get_content_charset.return_value = "utf-8"

        with mock.patch("hpc_tools.commands.slurm.urlopen", return_value=response), \
             mock.patch("hpc_tools.commands.slurm.run_remote_capture") as run_remote_capture, \
             mock.patch("hpc_tools.commands.slurm.submissions.read_events", return_value=[]):
            run_remote_capture.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout="file system: $VSC_DATA\nBlocks: 599G of 600G\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="ID Name Balance Reserved Available\n142 geniusdefaultslurmaccount 0 0 0\n", stderr=""),
            ]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = args.handler(args, profile)

        self.assertEqual(result, 0)
        text = stdout.getvalue()
        self.assertIn("== status page ==", text)
        self.assertIn("Service update", text)
        self.assertIn("Planned maintenance on 2026-06-20.", text)
        self.assertIn("Minor incident on the login node.", text)
        self.assertIn("== quota ==", text)
        self.assertIn("file system: $VSC_DATA", text)
        self.assertIn("Blocks: 599G of 600G", text)
        self.assertIn("== balance ==", text)
        self.assertIn("geniusdefaultslurmaccount", text)
        self.assertIn("== submissions ==", text)
        self.assertIn("No submissions.", text)

    def test_statement_command_requires_account_and_accepts_date_range(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "statement",
                "--account",
                "proj-123",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
            ]
        )

        self.assertEqual(args.account, "proj-123")
        self.assertEqual(args.start, "2026-01-01")
        self.assertEqual(args.end, "2026-01-31")

    def test_statement_command_builds_remote_command(self) -> None:
        command = _statement_command(
            "sam-statement",
            account="proj 123",
            start="2026-01-01",
            end="2026-01-31",
        )

        self.assertEqual(
            command,
            "sam-statement --account 'proj 123' --start 2026-01-01 --end 2026-01-31",
        )

    def test_statement_command_rejects_invalid_dates(self) -> None:
        with self.assertRaises(ConfigError):
            _statement_command("sam-statement", account="proj-123", start="01-01-2026")

    def test_quote_command_accepts_slurm_options(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "quote",
                "srun",
                "-M",
                "wice",
                "-p",
                "gpu_a100",
                "-N",
                "1",
                "--gpus=2",
                "-t",
                "02:00:00",
                "-A",
                "proj-123",
            ]
        )

        self.assertEqual(args.quote_args[0], "srun")
        self.assertIn("--gpus=2", args.quote_args)

    def test_quote_command_builds_remote_command(self) -> None:
        command = _quote_command(
            "sam-quote",
            ["srun", "-M", "wice", "-p", "gpu_a100", "-A", "proj 123"],
        )

        self.assertEqual(
            command,
            "sam-quote srun -M wice -p gpu_a100 -A 'proj 123'",
        )

    def test_quote_command_rejects_missing_account(self) -> None:
        with self.assertRaises(ConfigError):
            _quote_command("sam-quote", ["srun", "-M", "wice", "-p", "gpu_a100"])

    def test_quote_command_rejects_missing_submit_command(self) -> None:
        with self.assertRaises(ConfigError):
            _quote_command("sam-quote", [])

