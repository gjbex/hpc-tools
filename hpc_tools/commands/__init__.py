from __future__ import annotations

import contextlib
from typing import Any

from hpc_tools.commands import core, probes, references, remote, slurm, submissions


def register_builtin_commands(subparsers: Any, profile: Any, handlers: Any) -> None:
    with _command_group(subparsers, "Local setup and metadata"):
        core.register_local(subparsers, handlers)
        references.register(subparsers, handlers)

    with _command_group(subparsers, "Cluster inspection"):
        core.register_doctor(subparsers, handlers)
        slurm.register_status(subparsers, profile, handlers)
        core.register_site_env(subparsers, handlers)
        remote.register_hardware(subparsers, profile, handlers)
        remote.register_storage(subparsers, handlers)
        remote.register_quota(subparsers, profile, handlers)
        remote.register_module_spider(subparsers, handlers)
        slurm.register_limits(subparsers, handlers)

    with _command_group(subparsers, "Remote workspace"):
        remote.register_projects(subparsers, handlers)
        remote.register_repo(subparsers, handlers)
        remote.register_clone(subparsers, handlers)
        core.register_run(subparsers, handlers)

    with _command_group(subparsers, "Packaged assets"):
        probes.register_probes(subparsers, handlers)
        probes.register_containers(subparsers, handlers)

    with _command_group(subparsers, "Slurm accounting and safety"):
        slurm.register_accounting(subparsers, profile, handlers)

    with _command_group(subparsers, "Slurm job lifecycle"):
        slurm.register_lifecycle(subparsers, profile, handlers)
        submissions.register(subparsers, handlers)


@contextlib.contextmanager
def _command_group(subparsers: Any, title: str) -> object:
    group = getattr(subparsers, "group", None)
    if group is None:
        yield
        return
    with group(title):
        yield
