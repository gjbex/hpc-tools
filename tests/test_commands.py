from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from hpc_tools.config import ConfigError, Profile
from hpc_tools.cli import (
    _install_hardware_probe_command,
    _statement_command,
    build_parser,
    cmd_clone,
    cmd_install_hardware_probe,
    cmd_write_hardware_probe,
    main,
)
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

    def test_submit_test_only_command(self) -> None:
        command = slurm.submit_command("job.slurm", directory="$VSC_DATA/Projects/demo", test_only=True)

        self.assertEqual(command, "cd $VSC_DATA/Projects/demo && sbatch --test-only job.slurm")

    def test_clone_command_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "clone", "https://github.com/org/repo.git", "--branch", "main"])

        self.assertIs(args.handler, cmd_clone)
        self.assertEqual(args.url, "https://github.com/org/repo.git")
        self.assertEqual(args.branch, "main")

    def test_write_hardware_probe_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["write-hardware-probe", "probe.slurm"])

        self.assertIs(args.handler, cmd_write_hardware_probe)
        self.assertEqual(args.output, "probe.slurm")
        self.assertFalse(args.force)

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
            ]
        )

        self.assertIs(args.handler, cmd_install_hardware_probe)
        self.assertEqual(args.directory, "$VSC_DATA/probes")
        self.assertEqual(args.account, "proj")
        self.assertEqual(args.cluster, "cluster-a")
        self.assertEqual(args.partition, "batch")
        self.assertEqual(args.time, "00:30:00")

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
        self.assertIn("lscpu --cache", stdout.getvalue())

    def test_write_hardware_probe_to_file(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hardware-probe.slurm"
            args = parser.parse_args(["write-hardware-probe", str(output)])

            result = args.handler(args, None)

            self.assertEqual(result, 0)
            self.assertIn("Hardware probe output written", output.read_text(encoding="utf-8"))

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

    def test_optional_commands_visible_when_configured(self) -> None:
        parser = build_parser(make_profile())
        help_text = parser.format_help()

        self.assertIn("quota", help_text)
        self.assertIn("queue", help_text)
        self.assertIn("balance", help_text)
        self.assertIn("statement", help_text)
        self.assertIn("hardware", help_text)

    def test_optional_commands_hidden_when_unconfigured(self) -> None:
        parser = build_parser(
            make_profile(
                quota_command=None,
                queue_command=None,
                sam_balance_command=None,
                sam_statement_command=None,
                hardware_reference=None,
                hardware_url=None,
                slurm_reference=None,
                slurm_url=None,
                storage_reference=None,
                storage_url=None,
            )
        )
        help_text = parser.format_help()

        self.assertNotIn("quota", help_text)
        self.assertNotIn("queue", help_text)
        self.assertNotIn("balance", help_text)
        self.assertNotIn("statement", help_text)
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

    def test_hardware_context_renders_sources(self) -> None:
        profile = make_profile(
            hardware_url="https://example.org/hardware",
            slurm_url="https://example.org/slurm",
            storage_url="https://example.org/storage",
        )

        self.assertEqual(
            render_hardware_context(profile, source_only=True),
            "hardware_url: https://example.org/hardware\n"
            "slurm_url: https://example.org/slurm\n"
            "storage_url: https://example.org/storage",
        )


def make_profile(
    *,
    quota_command: str | None = "myquota",
    queue_command: str | None = "slurm_queuestate",
    sam_balance_command: str | None = "sam-balance",
    sam_statement_command: str | None = "sam-statement",
    hardware_reference: str | None = "examples/references/kuleuven-tier2-hardware.md",
    hardware_url: str | None = "https://example.org/hardware",
    slurm_reference: str | None = "examples/references/kuleuven-tier2-slurm.md",
    slurm_url: str | None = "https://example.org/slurm",
    storage_reference: str | None = "examples/references/kuleuven-tier2-storage.md",
    storage_url: str | None = "https://example.org/storage",
) -> Profile:
    return Profile(
        name="genius",
        target="gjb@genius",
        host="genius",
        user="gjb",
        ssh_options=("-x",),
        login_shell=("bash", "-l", "-c"),
        projects_dir="$VSC_DATA/Projects",
        quota_command=quota_command,
        queue_command=queue_command,
        sam_balance_command=sam_balance_command,
        sam_statement_command=sam_statement_command,
        hardware_reference=hardware_reference,
        hardware_url=hardware_url,
        slurm_reference=slurm_reference,
        slurm_url=slurm_url,
        storage_reference=storage_reference,
        storage_url=storage_url,
        default_cluster="wice",
    )


if __name__ == "__main__":
    unittest.main()
