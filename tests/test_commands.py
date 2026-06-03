from __future__ import annotations

import contextlib
import io
import unittest

from hpc_tools.config import ConfigError, Profile
from hpc_tools.cli import _statement_command, build_parser, cmd_clone
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
        self.assertNotIn("hardware", help_text)

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
