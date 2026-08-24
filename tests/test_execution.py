from __future__ import annotations

from dataclasses import replace
import subprocess
import unittest
from unittest import mock

from hpc_tools.config import ConfigError
from hpc_tools.execution import (
    EXECUTOR_ENV_VAR,
    LocalExecutor,
    SshExecutor,
    executor_scope,
    resolve_executor,
    run_command_capture,
)

from test_cli_fixtures import make_profile


class ExecutionTests(unittest.TestCase):
    def test_ssh_executor_builds_login_shell_command(self) -> None:
        plan = SshExecutor().plan(
            make_profile(),
            'cd "$VSC_DATA/Projects/foo" && git status',
        )

        self.assertEqual(plan.executor, "ssh")
        self.assertEqual(plan.argv[:3], ("ssh", "-x", "gjb@genius"))
        self.assertEqual(
            plan.argv[3],
            'bash -l -c \'cd "$VSC_DATA/Projects/foo" && git status\'',
        )
        self.assertEqual(plan.metadata()["ssh_command"], plan.rendered_command)

    def test_local_executor_runs_command_without_ssh(self) -> None:
        profile = replace(make_profile(), target=None, host=None, user=None)
        completed = subprocess.CompletedProcess([], 0, "node01\n", "")

        with mock.patch(
            "hpc_tools.execution.subprocess.run",
            return_value=completed,
        ) as run:
            with executor_scope("local"):
                result = run_command_capture(profile, "hostname")

        self.assertEqual(result.stdout, "node01\n")
        run.assert_called_once_with(
            ("bash", "-l", "-c", "hostname"),
            check=False,
            capture_output=True,
            text=True,
        )
        metadata = LocalExecutor().plan(profile, "hostname").metadata()
        self.assertEqual(metadata["executor"], "local")
        self.assertIsNone(metadata["ssh_command"])

    def test_ssh_executor_rejects_targetless_profile(self) -> None:
        profile = replace(make_profile(), target=None, host=None, user=None)

        with self.assertRaisesRegex(ConfigError, "when using the SSH executor"):
            SshExecutor().plan(profile, "hostname")

    def test_scope_overrides_environment_without_leaking(self) -> None:
        with mock.patch.dict("os.environ", {EXECUTOR_ENV_VAR: "ssh"}, clear=False):
            self.assertEqual(resolve_executor().name, "ssh")
            with executor_scope("local"):
                self.assertEqual(resolve_executor().name, "local")
            self.assertEqual(resolve_executor().name, "ssh")

    def test_unknown_environment_executor_is_rejected(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {EXECUTOR_ENV_VAR: "invalid"},
            clear=False,
        ):
            with self.assertRaisesRegex(ConfigError, "unknown executor"):
                resolve_executor()


if __name__ == "__main__":
    unittest.main()
