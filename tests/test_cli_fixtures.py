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
    cmd_cancel,
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



def _find_help_line(lines: list[str], text: str, start: int) -> int:
    for index in range(start, len(lines)):
        line = lines[index]
        if text.endswith(":") and line == text:
            return index
        if not text.endswith(":") and line.startswith(f"{text} "):
            return index
    raise AssertionError(f"help line not found after {start}: {text}")

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


__all__ = [name for name in globals() if not name.startswith("__")]
