from __future__ import annotations

import subprocess

from hpc_tools.config import Profile
from hpc_tools.execution import SshExecutor, format_command


def build_remote_shell_command(profile: Profile, command: str) -> str:
    return format_command([*profile.login_shell, command])


def build_ssh_argv(profile: Profile, command: str) -> list[str]:
    return SshExecutor().build_argv(profile, command)


def run_remote(profile: Profile, command: str, *, dry_run: bool = False) -> int:
    executor = SshExecutor()
    plan = executor.plan(profile, command)
    if dry_run:
        print(plan.rendered_command)
        return 0
    return executor.run_plan(plan).returncode


def run_remote_capture(
    profile: Profile,
    command: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    executor = SshExecutor()
    plan = executor.plan(profile, command)
    if dry_run:
        print(plan.rendered_command)
        return subprocess.CompletedProcess(plan.argv, 0, "", "")
    return executor.run_plan(plan, capture_output=True)
