from __future__ import annotations

from test_plugin_fixtures import *


class PluginFeatureTests(unittest.TestCase):
    def test_r_scan_follows_source_file_and_detects_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script_dir = root / "Script"
            script_dir.mkdir()
            (script_dir / "autoexec.R").write_text(
                "library(dplyr)\nlibrary(sf)\n",
                encoding="utf-8",
            )
            (script_dir / "main.R").write_text(
                'source("autoexec.R")\nres <- readxl::read_excel("data.xlsx")\n',
                encoding="utf-8",
            )

            result = r_support.scan_target(script_dir / "main.R")

        self.assertEqual(sorted(result.packages), ["dplyr", "readxl", "sf"])
        self.assertEqual(len(result.scanned_files), 2)

    def test_r_scan_reads_description_with_continuation_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "DESCRIPTION").write_text(
                """Package: demo
Imports: dplyr,
    ggplot2
Depends: R (>= 4.3),
    Matrix
LinkingTo: Rcpp
""",
                encoding="utf-8",
            )

            result = r_support.scan_target(root)

        self.assertEqual(sorted(result.packages), ["Matrix", "Rcpp", "dplyr", "ggplot2"])

    def test_r_scan_command_runs_without_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.R"
            path.write_text("library(ggplot2)\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = r_support.cmd_r_scan(
                    type("Args", (), {"target": path, "json": False})(),
                    None,
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("ggplot2", stdout.getvalue())

    def test_build_check_command_loads_modules_and_emits_status_lines(self) -> None:
        command = r_support.build_check_command(
            ["PrevMap", "INLA"],
            ["R/4.4.2", "R-bundle-CRAN/2024.11"],
        )

        self.assertIn("module load R/4.4.2 R-bundle-CRAN/2024.11", command)
        self.assertIn("Rscript -e", command)
        self.assertIn("\\t", command)

    def test_render_install_script_uses_archive_and_extra_repo(self) -> None:
        script = r_support.render_install_script(
            missing_packages=["PrevMap", "INLA", "dlnm"],
            module="R/4.4.2",
            cran_bundle="R-bundle-CRAN/2024.11",
            bioc_bundle="R-bundle-Bioconductor/3.20",
            cluster="wice",
            partition="batch_icelake",
            job_name="r-install",
            time="01:00:00",
            cpus_per_task="4",
            library_root_template=r_support.DEFAULT_LIBRARY_ROOT_TEMPLATE,
            arch_guard="icelake",
            archive_packages={"PrevMap": "https://example.org/PrevMap.tar.gz"},
            extra_repos={"INLA": "https://inla.r-inla-download.org/R/testing"},
        )

        self.assertIn("#SBATCH --clusters=wice", script)
        self.assertIn("#SBATCH --partition=batch_icelake", script)
        self.assertIn('"https://example.org/PrevMap.tar.gz"', script)
        self.assertIn('repos = NULL, type = "source", dependencies = TRUE', script)
        self.assertIn('INLA = "https://inla.r-inla-download.org/R/testing"', script)
        self.assertIn('if [[ "${VSC_ARCH_LOCAL}" != "icelake" ]]', script)
        self.assertIn("print(.libPaths())", script)

    def test_parse_verify_output_extracts_statuses_and_library_paths(self) -> None:
        output = """PrevMap OK
INLA OK
dlnm MISSING

Library paths:
[1] "/data/Rlibs/icelake"
[2] "/apps/R/library"

Session info:
"""
        result = r_support.parse_verify_output(output, ["PrevMap", "INLA", "dlnm"])

        self.assertEqual(result.statuses["PrevMap"], "OK")
        self.assertEqual(result.statuses["dlnm"], "MISSING")
        self.assertIn('/data/Rlibs/icelake', result.library_paths[0])

    def test_build_stage_script_command_writes_remote_script(self) -> None:
        command = r_support.build_stage_script_command(
            directory="$VSC_DATA/Projects/demo",
            remote_name="install.slurm",
            contents="#!/bin/bash\n",
        )

        self.assertIn("mkdir -p $VSC_DATA/Projects/demo", command)
        self.assertIn("cat > install.slurm", command)
        self.assertIn("chmod +x install.slurm", command)

    def test_build_quote_args_for_install_job(self) -> None:
        args = r_support.build_quote_args(
            remote_script_path="/remote/install.slurm",
            account="proj123",
            cluster="wice",
            partition="batch_icelake",
            reservation=None,
            time="01:00:00",
            nodes="1",
            cpus_per_task="4",
        )

        self.assertEqual(
            args,
            [
                "sbatch",
                "/remote/install.slurm",
                "-A",
                "proj123",
                "-M",
                "wice",
                "-p",
                "batch_icelake",
                "-t",
                "01:00:00",
                "-N",
                "1",
                "-c",
                "4",
            ],
        )

    def test_r_check_command_uses_remote_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.R"
            path.write_text("library(PrevMap)\n", encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "target": path,
                    "packages": [],
                    "module": "R/4.4.2",
                    "cran_bundle": "R-bundle-CRAN/2024.11",
                    "bioc_bundle": None,
                    "dry_run": False,
                    "json": False,
                },
            )()
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="PrevMap\tMISSING\n",
                stderr="",
            )
            stdout = io.StringIO()
            profile = type("Profile", (), {})()
            with mock.patch("hpc_tools.plugins.r.remote_verify.run_command_capture", return_value=completed) as remote, \
                 contextlib.redirect_stdout(stdout):
                exit_code = r_support.cmd_r_check(args, profile)

        self.assertEqual(exit_code, 0)
        self.assertTrue(remote.called)
        self.assertIn("Missing:", stdout.getvalue())

    def test_r_submit_install_stages_quotes_validates_submits_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "install.slurm"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "jobscript": script,
                    "directory": "$VSC_DATA/Projects/demo",
                    "account": "proj123",
                    "remote_name": None,
                    "cluster": "wice",
                    "partition": "batch_icelake",
                    "reservation": None,
                    "time": "01:00:00",
                    "cpus_per_task": "4",
                    "nodes": "1",
                    "skip_quote": False,
                    "no_validate_first": False,
                    "dry_run": False,
                },
            )()
            profile = type(
                "Profile",
                (),
                {"name": "genius", "default_cluster": "wice", "sam_quote_command": "sam-quote"},
            )()
            stage = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            quote = subprocess.CompletedProcess(args=[], returncode=0, stdout="600\n", stderr="")
            validate = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            submit = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Submitted batch job 12345 on cluster wice\n",
                stderr="",
            )

            with mock.patch(
                "hpc_tools.plugins.r.commands.run_command_capture",
                side_effect=[stage, quote, validate, submit],
            ) as remote, mock.patch("hpc_tools.plugins.r.install_plan.submissions.append_event") as append_event:
                exit_code = r_support.cmd_r_submit_install(args, profile)

        self.assertEqual(exit_code, 0)
        self.assertEqual(remote.call_count, 4)
        event = append_event.call_args.args[0]
        self.assertEqual(event["event"], "submitted")
        self.assertEqual(event["job_id"], "12345")
        self.assertEqual(event["jobscript"], "install.slurm")
