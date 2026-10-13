from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import shlex
import subprocess

from hpc_tools.config import ConfigError, Profile


EXECUTOR_ENV_VAR = "HPC_TOOLS_EXECUTOR"
DEFAULT_EXECUTOR = "ssh"
EXECUTOR_NAMES = ("ssh", "local")


def format_command(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


@dataclass(frozen=True)
class ExecutionPlan:
    executor: str
    argv: tuple[str, ...]

    @property
    def rendered_command(self) -> str:
        return format_command(self.argv)

    def metadata(self) -> dict[str, str | None]:
        return {
            "executor": self.executor,
            "execution_command": self.rendered_command,
            "ssh_command": self.rendered_command if self.executor == "ssh" else None,
        }


class CommandExecutor(ABC):
    name: str

    def plan(self, profile: Profile, command: str) -> ExecutionPlan:
        return ExecutionPlan(self.name, tuple(self.build_argv(profile, command)))

    @abstractmethod
    def build_argv(self, profile: Profile, command: str) -> list[str]:
        """Build the process argument vector for one cluster command."""

    def run(
        self,
        profile: Profile,
        command: str,
        *,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_plan(
            self.plan(profile, command),
            capture_output=capture_output,
        )

    def run_plan(
        self,
        plan: ExecutionPlan,
        *,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            plan.argv,
            check=False,
            capture_output=capture_output,
            text=capture_output,
        )

    def run_plan_bytes(
        self,
        plan: ExecutionPlan,
        *,
        input_data: bytes,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run a fixed protocol command with bounded binary transport."""
        return subprocess.run(
            plan.argv,
            check=False,
            input=input_data,
            capture_output=True,
            timeout=timeout,
        )


class SshExecutor(CommandExecutor):
    name = "ssh"

    def build_argv(self, profile: Profile, command: str) -> list[str]:
        target = profile.ssh_target
        if not target:
            raise ConfigError(
                f"profile '{profile.name}' must define 'ssh_target' or 'host' "
                "when using the SSH executor"
            )
        remote_command = format_command([*profile.login_shell, command])
        return ["ssh", *profile.ssh_options, target, remote_command]


class LocalExecutor(CommandExecutor):
    name = "local"

    def build_argv(self, profile: Profile, command: str) -> list[str]:
        return [*profile.login_shell, command]


_EXECUTORS: dict[str, CommandExecutor] = {
    "ssh": SshExecutor(),
    "local": LocalExecutor(),
}
_EXECUTOR_CONTEXT: ContextVar[str | None] = ContextVar(
    "hpc_tools_executor",
    default=None,
)


def resolve_executor(name: str | None = None) -> CommandExecutor:
    selected = (
        name
        or _EXECUTOR_CONTEXT.get()
        or os.environ.get(EXECUTOR_ENV_VAR)
        or DEFAULT_EXECUTOR
    )
    try:
        return _EXECUTORS[selected]
    except KeyError as error:
        choices = ", ".join(EXECUTOR_NAMES)
        raise ConfigError(
            f"unknown executor '{selected}'; expected one of: {choices}"
        ) from error


@contextmanager
def executor_scope(name: str | None) -> Iterator[CommandExecutor]:
    executor = resolve_executor(name)
    token = _EXECUTOR_CONTEXT.set(executor.name)
    try:
        yield executor
    finally:
        _EXECUTOR_CONTEXT.reset(token)


def execution_plan(profile: Profile, command: str) -> ExecutionPlan:
    return resolve_executor().plan(profile, command)


def run_command(
    profile: Profile,
    command: str,
    *,
    dry_run: bool = False,
) -> int:
    executor = resolve_executor()
    plan = executor.plan(profile, command)
    if dry_run:
        print(plan.rendered_command)
        return 0
    return executor.run_plan(plan).returncode


def run_command_capture(
    profile: Profile,
    command: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    executor = resolve_executor()
    plan = executor.plan(profile, command)
    if dry_run:
        print(plan.rendered_command)
        return subprocess.CompletedProcess(plan.argv, 0, "", "")
    return executor.run_plan(plan, capture_output=True)
