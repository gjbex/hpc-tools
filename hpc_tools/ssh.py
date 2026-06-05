from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence

from hpc_tools.config import Profile


def build_remote_shell_command(profile: Profile, command: str) -> str:
    parts = [*profile.login_shell, command]
    return " ".join(shlex.quote(part) for part in parts)


def build_ssh_argv(profile: Profile, command: str) -> list[str]:
    return [
        "ssh",
        *profile.ssh_options,
        profile.ssh_target,
        build_remote_shell_command(profile, command),
    ]


def format_command(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def run_remote(profile: Profile, command: str, *, dry_run: bool = False) -> int:
    argv = build_ssh_argv(profile, command)
    if dry_run:
        print(format_command(argv))
        return 0

    completed = subprocess.run(argv, check=False)
    return completed.returncode


def run_remote_capture(
    profile: Profile,
    command: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    argv = build_ssh_argv(profile, command)
    if dry_run:
        print(format_command(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    return subprocess.run(argv, check=False, capture_output=True, text=True)
