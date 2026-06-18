from __future__ import annotations

import contextlib
import io
import json
from importlib import resources
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hpc_tools.config import ConfigError, Profile
from hpc_tools.cli import (
    _doctor_command,
    _install_cuda_device_properties_command,
    _install_hardware_probe_command,
    _log_submission,
    _module_spider_command,
    _quote_command,
    _repo_status_command,
    _fetch_status_page,
    _site_env_command,
    _statement_command,
    _storage_inspect_command,
    build_parser,
    cmd_clone,
    cmd_doctor,
    cmd_install_container,
    cmd_install_hardware_probe,
    cmd_install_probe,
    cmd_job,
    cmd_paths,
    cmd_projects,
    cmd_repo_status,
    cmd_slurm_limits,
    cmd_site_env,
    cmd_status,
    cmd_storage_inspect,
    cmd_submit,
    cmd_write_container,
    cmd_write_hardware_probe,
    cmd_write_probe,
    main,
)
from hpc_tools import mcp_server
from hpc_tools.plugins import benchmark_support
from hpc_tools.hardware import render_hardware_context
from hpc_tools.ssh import build_ssh_argv
from hpc_tools import slurm


class CommandTests(unittest.TestCase):
    def test_ssh_command_quotes_remote_command(self) -> None:
        profile = make_profile()

        argv = build_ssh_argv(profile, 'cd "$VSC_DATA/Projects/foo" && git status')

        self.assertEqual(argv[0:3], ["ssh", "-x", "gjb@genius"])
        self.assertEqual(
            argv[3],
            'bash -l -c \'cd "$VSC_DATA/Projects/foo" && git status\'',
        )

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

    def test_doctor_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["doctor"])

        self.assertIs(args.handler, cmd_doctor)
        command = _doctor_command()
        self.assertIn("## identity", command)
        self.assertIn("hostname; whoami; pwd", command)
        self.assertIn("## slurm-tools", command)
        self.assertIn("command -v \"$tool\"", command)
        self.assertIn("sacctmgr", command)

    def test_site_env_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["site-env"])

        self.assertIs(args.handler, cmd_site_env)
        command = _site_env_command()
        self.assertIn("## environment", command)
        self.assertIn("HOME|DATA|SCRATCH|WORK|PROJECT|TMP|SLURM", command)
        self.assertIn("## helper-tools", command)
        self.assertIn("beegfs-ctl", command)
        self.assertIn("module --version", command)

    def test_storage_inspect_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect", "$VSC_DATA/Projects/demo"])

        self.assertIs(args.handler, cmd_storage_inspect)
        self.assertEqual(args.path, "$VSC_DATA/Projects/demo")
        command = _storage_inspect_command(args.path)
        self.assertIn("## path", command)
        self.assertIn("ls -ld $VSC_DATA/Projects/demo", command)
        self.assertIn("df -hT $VSC_DATA/Projects/demo", command)
        self.assertIn("du -sh $VSC_DATA/Projects/demo", command)
        self.assertIn("mount | sed -n '1,80p'", command)

    def test_storage_inspect_defaults_to_current_directory(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["storage", "inspect"])

        self.assertEqual(args.path, ".")
        self.assertIn("df -hT .", _storage_inspect_command(args.path))

    def test_module_spider_parser_and_command_quotes_name(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["module-spider", "DMTCP; rm -rf /"])

        self.assertEqual(args.name, "DMTCP; rm -rf /")
        self.assertEqual(_module_spider_command(args.name), "module spider 'DMTCP; rm -rf /' 2>&1")

    def test_repo_status_parser_and_command(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(["repo", "status", "--directory", "$VSC_DATA/Projects/demo"])

        self.assertIs(args.handler, cmd_repo_status)
        self.assertEqual(args.directory, "$VSC_DATA/Projects/demo")
        command = _repo_status_command(args.directory)
        self.assertIn("test -d $VSC_DATA/Projects/demo", command)
        self.assertIn("git status --short --branch", command)
        self.assertIn("git remote -v", command)
        self.assertIn("git log -1 --oneline", command)

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
        with mock.patch("hpc_tools.cli.run_remote_capture", side_effect=[validation, submitted]) as run_remote_capture, \
             mock.patch("hpc_tools.cli.submissions.append_event") as append_event, \
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
        with mock.patch("hpc_tools.cli.run_remote_capture", return_value=validation) as run_remote_capture, \
             mock.patch("hpc_tools.cli.submissions.append_event") as append_event, \
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

        with mock.patch("hpc_tools.cli.submissions.append_event") as append_event:
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

    def test_clone_command_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "clone", "https://github.com/org/repo.git", "--branch", "main"])

        self.assertIs(args.handler, cmd_clone)
        self.assertEqual(args.url, "https://github.com/org/repo.git")
        self.assertEqual(args.branch, "main")

    def test_clone_parser_accepts_directory_override(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "clone",
                "https://github.com/org/repo.git",
                "--branch",
                "main",
                "--directory",
                "$VSC_SCRATCH/repos",
                "--name",
                "demo",
            ]
        )

        self.assertIs(args.handler, cmd_clone)
        self.assertEqual(args.directory, "$VSC_SCRATCH/repos")
        self.assertEqual(args.name, "demo")

    def test_clone_uses_directory_override(self) -> None:
        profile = make_profile(projects_dir=None)
        parser = build_parser(profile)
        args = parser.parse_args(
            [
                "--dry-run",
                "clone",
                "https://github.com/org/repo.git",
                "--directory",
                "$VSC_SCRATCH/repos",
            ]
        )

        with mock.patch("hpc_tools.cli.run_remote") as run_remote:
            cmd_clone(args, profile)

        self.assertEqual(
            run_remote.call_args.args[1],
            "cd $VSC_SCRATCH/repos && git clone https://github.com/org/repo.git",
        )

    def test_projects_quotes_directory_paths(self) -> None:
        profile = make_profile(projects_dir="/data/My Projects")
        args = type("Args", (), {"dry_run": False})()

        with mock.patch("hpc_tools.cli.run_remote") as run_remote:
            cmd_projects(args, profile)

        self.assertEqual(
            run_remote.call_args.args[1],
            "ls -ld '/data/My Projects' 2>/dev/null && ls -1 '/data/My Projects'",
        )

    def test_clone_requires_directory_when_projects_dir_is_missing(self) -> None:
        profile = make_profile(projects_dir=None)
        parser = build_parser(profile)
        args = parser.parse_args(["clone", "https://github.com/org/repo.git"])

        with self.assertRaises(ConfigError):
            cmd_clone(args, profile)

    def test_paths_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["paths"])

        self.assertIs(args.handler, cmd_paths)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = args.handler(args, None)

        self.assertEqual(result, 0)
        self.assertIn("container_generic_template:", stdout.getvalue())

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

        with mock.patch("hpc_tools.cli.urlopen", return_value=response) as urlopen, \
             mock.patch("hpc_tools.cli.run_remote_capture") as run_remote_capture, \
             mock.patch("hpc_tools.cli.submissions.read_events", return_value=[]) as read_events:
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

        with mock.patch("hpc_tools.cli.urlopen", return_value=response), \
             mock.patch("hpc_tools.cli.run_remote_capture") as run_remote_capture, \
             mock.patch("hpc_tools.cli.submissions.read_events", return_value=[]):
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

    def test_submissions_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["submissions", "--log", "/tmp/log.jsonl", "list"])

        self.assertEqual(args.command, "submissions")
        self.assertEqual(args.submissions_command, "list")
        self.assertEqual(str(args.log), "/tmp/log.jsonl")

    def test_references_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["references", "list"])

        self.assertEqual(args.command, "references")
        self.assertEqual(args.references_command, "list")

    def test_plugins_list_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["plugins", "list"])

        self.assertEqual(args.command, "plugins")
        self.assertEqual(args.plugins_command, "list")

    def test_mcp_console_script_entry_point_is_available(self) -> None:
        self.assertTrue(callable(mcp_server.main))

    def test_benchmark_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["benchmark", "summarize", "results/"])

        self.assertEqual(args.command, "benchmark")
        self.assertEqual(args.benchmark_command, "summarize")
        self.assertIs(args.handler, benchmark_support.cmd_benchmark_summarize)

    def test_benchmark_main_json_is_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one.csv"
            path.write_text("seconds\n10\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["--json", "benchmark", "summarize", str(path)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("summaries", payload)
        self.assertNotIn("stdout", payload)

    def test_r_scan_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["r", "scan", "Script/Main.R"])

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "scan")

    def test_r_check_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "check",
                "Script/Main.R",
                "--module",
                "R/4.4.2",
                "--cran-bundle",
                "R-bundle-CRAN/2024.11",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "check")
        self.assertEqual(args.module, "R/4.4.2")
        self.assertEqual(args.cran_bundle, "R-bundle-CRAN/2024.11")

    def test_r_plan_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "plan-install",
                "Script/Main.R",
                "--module",
                "R/4.4.2",
                "--partition",
                "batch_icelake",
                "--output",
                "install.slurm",
                "--archive-package",
                "PrevMap=https://example.org/PrevMap.tar.gz",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "plan-install")
        self.assertEqual(args.partition, "batch_icelake")
        self.assertEqual(str(args.output), "install.slurm")

    def test_r_verify_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "verify-install",
                "--job-output",
                "/tmp/job.out",
                "--package",
                "PrevMap",
                "--package",
                "INLA",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "verify-install")
        self.assertEqual(args.packages, ["PrevMap", "INLA"])

    def test_r_submit_install_parser(self) -> None:
        parser = build_parser(make_profile())
        args = parser.parse_args(
            [
                "r",
                "submit-install",
                "install.slurm",
                "--directory",
                "$VSC_DATA/Projects/demo",
                "--account",
                "proj123",
                "--cluster",
                "wice",
                "--partition",
                "batch_icelake",
            ]
        )

        self.assertEqual(args.command, "r")
        self.assertEqual(args.r_command, "submit-install")
        self.assertEqual(str(args.jobscript), "install.slurm")
        self.assertEqual(args.account, "proj123")

    def test_paths_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["paths"])

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("config: /tmp/xdg/hpc-tools/config.toml", output)
        self.assertIn("profile_references: /tmp/xdg/hpc-tools/profiles/<profile>", output)
        self.assertIn("reference_sets: /tmp/xdg/hpc-tools/reference-sets", output)
        self.assertIn("codex_skills: ~/.codex/skills/", output)
        self.assertIn("cuda_device_properties_template:", output)
        self.assertIn("cuda_device_properties_source:", output)
        self.assertIn("package_uninstall: pipx uninstall hpc-tools", output)
        self.assertIn("hpc-cluster-onboarding", output)
        self.assertIn("hpc-slurm-job-arrays", output)
        self.assertIn("hpc-slurm-benchmark", output)

    def test_paths_main_json_wraps_text_output(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["paths", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["returncode"], 0)
        self.assertEqual(payload["stderr"], "")
        self.assertIn("config:", payload["stdout"])
        self.assertIn("paths", payload["argv"])

    def test_python_scan_main_json_stays_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "analysis.py").write_text("import mmh3\n", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(["python", "scan", str(root), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("mmh3", payload["packages"])
        self.assertIn(str(root / "analysis.py"), payload["scanned_files"][0])
        self.assertNotIn("stdout", payload)

    def test_references_list_main_does_not_require_config(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/xdg"}, clear=True), contextlib.redirect_stdout(stdout):
            result = main(["references", "list"])

        self.assertEqual(result, 0)
        self.assertIn("No reference sets.", stdout.getvalue())

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
            result = args.handler(args, None)

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

            result = args.handler(args, None)

            self.assertEqual(result, 0)
            self.assertIn("Hardware probe output written", output.read_text(encoding="utf-8"))

    def test_write_container_bundle_to_directory(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            args = parser.parse_args(["write-container", "--kind", "generic", str(output)])

            result = args.handler(args, None)

            self.assertEqual(result, 0)
            self.assertTrue((output / "create_apptainer_container.slurm").exists())
            self.assertIn(
                "apptainer build",
                (output / "create_apptainer_container.slurm").read_text(encoding="utf-8"),
            )

    def test_write_hardware_probe_rejects_existing_file_without_force(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"
            output.write_text("existing", encoding="utf-8")
            args = parser.parse_args(["write-hardware-probe", str(output)])

            with self.assertRaises(ConfigError):
                args.handler(args, None)

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

            result = args.handler(args, None)

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

    def test_install_hardware_probe_command_writes_remote_file(self) -> None:
        command = _install_hardware_probe_command(
            "$VSC_DATA/probes",
            "probe.slurm",
            "#!/bin/bash\n#SBATCH --job-name=hardware-probe\n",
        )

        self.assertIn("mkdir -p $VSC_DATA/probes", command)
        self.assertIn("cd $VSC_DATA/probes", command)
        self.assertIn("cat > probe.slurm", command)
        self.assertIn("#SBATCH --job-name=hardware-probe", command)
        self.assertIn("chmod +x probe.slurm", command)

    def test_install_cuda_device_properties_command_writes_remote_bundle(self) -> None:
        command = _install_cuda_device_properties_command(
            "$VSC_DATA/probes",
            "cuda-device-properties.slurm",
        )

        self.assertIn("mkdir -p $VSC_DATA/probes", command)
        self.assertIn("cd $VSC_DATA/probes", command)
        self.assertIn("mkdir -p cuda", command)
        self.assertIn("cat > cuda-device-properties.slurm", command)
        self.assertIn("cat > cuda/CMakeLists.txt", command)
        self.assertIn("cat > cuda/device_properties.cu", command)
        self.assertIn("cudaGetDeviceProperties", command)
        self.assertIn("chmod +x cuda-device-properties.slurm", command)

    def test_install_container_bundle_writes_remote_bundle(self) -> None:
        profile = make_profile()
        parser = build_parser(profile)
        args = parser.parse_args(["install-container", "--kind", "generic", "--directory", "$VSC_DATA/containers"])

        with mock.patch("hpc_tools.cli.run_remote", return_value=0) as run_remote:
            result = cmd_install_container(args, profile)

        self.assertEqual(result, 0)
        command = run_remote.call_args.args[1]
        self.assertIn("mkdir -p $VSC_DATA/containers", command)
        self.assertIn("cat > create_apptainer_container.slurm", command)
        self.assertIn("apptainer build", command)

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

    def test_optional_commands_visible_when_configured(self) -> None:
        parser = build_parser(make_profile())
        help_text = parser.format_help()

        self.assertIn("quota", help_text)
        self.assertIn("queue", help_text)
        self.assertIn("balance", help_text)
        self.assertIn("statement", help_text)
        self.assertIn("quote", help_text)
        self.assertIn("hardware", help_text)

    def test_optional_commands_hidden_when_unconfigured(self) -> None:
        parser = build_parser(
            make_profile(
                quota_command=None,
                queue_command=None,
                sam_balance_command=None,
                sam_statement_command=None,
                sam_quote_command=None,
                hardware_reference=None,
                hardware_url=None,
                slurm_reference=None,
                slurm_url=None,
                storage_reference=None,
                storage_url=None,
                status_url=None,
            )
        )
        help_text = parser.format_help()

        self.assertNotIn("quota", help_text)
        self.assertNotIn("queue", help_text)
        self.assertNotIn("balance", help_text)
        self.assertNotIn("statement", help_text)
        self.assertNotIn("quote", help_text)
        self.assertNotIn("hardware           Show profile hardware", help_text)

    def test_hidden_optional_command_is_rejected_if_invoked(self) -> None:
        parser = build_parser(make_profile(quota_command=None))

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args(["quota"])

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

    def test_hardware_context_renders_sources(self) -> None:
        profile = make_profile(
            hardware_url="https://example.org/hardware",
            slurm_url="https://example.org/slurm",
            storage_url="https://example.org/storage",
            status_url="https://status.example.org/",
        )

        self.assertEqual(
            render_hardware_context(profile, source_only=True),
            "hardware_url: https://example.org/hardware\n"
            "slurm_url: https://example.org/slurm\n"
            "storage_url: https://example.org/storage\n"
            "status_url: https://status.example.org/",
        )


def make_profile(
    *,
    projects_dir: str | None = "$VSC_DATA/Projects",
    quota_command: str | None = "myquota",
    queue_command: str | None = "slurm_queuestate",
    sam_balance_command: str | None = "sam-balance",
    sam_statement_command: str | None = "sam-statement",
    sam_quote_command: str | None = "sam-quote",
    hardware_reference: str | None = "examples/references/kuleuven-tier2-hardware.md",
    hardware_url: str | None = "https://example.org/hardware",
    slurm_reference: str | None = "examples/references/kuleuven-tier2-slurm.md",
    slurm_url: str | None = "https://example.org/slurm",
    storage_reference: str | None = "examples/references/kuleuven-tier2-storage.md",
    storage_url: str | None = "https://example.org/storage",
    status_url: str | None = "https://status.example.org/",
    reference_set: str | None = None,
    email: str | None = "gjb@example.org",
) -> Profile:
    return Profile(
        name="genius",
        target="gjb@genius",
        host="genius",
        user="gjb",
        ssh_options=("-x",),
        login_shell=("bash", "-l", "-c"),
        projects_dir=projects_dir,
        quota_command=quota_command,
        queue_command=queue_command,
        sam_balance_command=sam_balance_command,
        sam_statement_command=sam_statement_command,
        sam_quote_command=sam_quote_command,
        hardware_reference=hardware_reference,
        hardware_url=hardware_url,
        slurm_reference=slurm_reference,
        slurm_url=slurm_url,
        storage_reference=storage_reference,
        storage_url=storage_url,
        status_url=status_url,
        reference_set=reference_set,
        default_cluster="wice",
        email=email,
    )


if __name__ == "__main__":
    unittest.main()
