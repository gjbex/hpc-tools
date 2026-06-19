from __future__ import annotations

import argparse
from importlib import resources
from typing import Any

from hpc_tools import plugin_system
from hpc_tools.commands.common import _section_command, _tool_check_loop
from hpc_tools.config import (
    ConfigError,
    Profile,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
)
from hpc_tools.ssh import run_remote


def register(subparsers: Any, handlers: Any) -> None:
    register_local(subparsers, handlers)
    register_doctor(subparsers, handlers)
    register_site_env(subparsers, handlers)
    register_run(subparsers, handlers)


def register_run(subparsers: Any, handlers: Any) -> None:
    run_parser = subparsers.add_parser("run", help="Run a command on the remote host")
    run_parser.add_argument("remote_command", help="Command to run through the configured login shell")
    run_parser.set_defaults(handler=handlers.cmd_run)


def register_doctor(subparsers: Any, handlers: Any) -> None:
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check remote login identity and core Slurm tool availability",
    )
    doctor_parser.set_defaults(handler=handlers.cmd_doctor)


def register_site_env(subparsers: Any, handlers: Any) -> None:
    site_env_parser = subparsers.add_parser(
        "site-env",
        help="Inspect remote site environment variables and common HPC helper tools",
    )
    site_env_parser.set_defaults(handler=handlers.cmd_site_env)


def register_local(subparsers: Any, handlers: Any) -> None:
    paths_parser = subparsers.add_parser(
        "paths",
        help="Show hpc-tools config, reference, skill, and package paths",
    )
    paths_parser.set_defaults(handler=handlers.cmd_paths)

    plugins_parser = subparsers.add_parser(
        "plugins",
        help="Inspect installed hpc-tools plugins",
    )
    plugins_subparsers = plugins_parser.add_subparsers(
        dest="plugins_command",
        metavar="<subcommand>",
        required=True,
    )

    plugins_list_parser = plugins_subparsers.add_parser(
        "list",
        help="List installed core and external plugins",
    )
    plugins_list_parser.set_defaults(handler=handlers.cmd_plugins_list)

    plugins_info_parser = plugins_subparsers.add_parser(
        "info",
        help="Show one installed plugin",
    )
    plugins_info_parser.add_argument("name", help="Plugin name")
    plugins_info_parser.set_defaults(handler=handlers.cmd_plugins_info)

def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, args.remote_command, dry_run=args.dry_run)

def cmd_doctor(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _doctor_command(), dry_run=args.dry_run)

def cmd_site_env(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _site_env_command(), dry_run=args.dry_run)

def cmd_paths(args: argparse.Namespace, profile: Profile | None) -> int:
    del args, profile
    package_probe = resources.files("hpc_tools.data").joinpath("hardware-probe.slurm")
    package_cuda_probe = resources.files("hpc_tools.data").joinpath("cuda-device-properties.slurm")
    package_cuda_source = resources.files("hpc_tools.data").joinpath("cuda")
    package_container_generic = resources.files("hpc_tools.data").joinpath(
        "containers", "apptainer", "create_apptainer_container.slurm"
    )
    package_container_r = resources.files("hpc_tools.data").joinpath("containers", "r", "create_r_container.slurm")
    package_container_conda = resources.files("hpc_tools.data").joinpath("containers", "conda", "create_conda_container.slurm")
    config_dir = default_config_dir()
    print(f"config: {default_config_path()}")
    print(f"profile_references: {config_dir / 'profiles' / '<profile>'}")
    print(f"reference_sets: {default_reference_sets_dir()}")
    print("codex_skills: ~/.codex/skills/")
    print(f"hardware_probe_template: {package_probe}")
    print(f"cuda_device_properties_template: {package_cuda_probe}")
    print(f"cuda_device_properties_source: {package_cuda_source}")
    print(f"container_generic_template: {package_container_generic}")
    print(f"container_r_template: {package_container_r}")
    print(f"container_conda_template: {package_container_conda}")
    print()
    print("package_uninstall: pipx uninstall hpc-tools")
    print("optional_user_state:")
    print(f"  {config_dir}")
    print(f"  {default_reference_sets_dir()}")
    print("optional_copied_skills:")
    print("  ~/.codex/skills/_shared")
    print("  ~/.codex/skills/hpc-cluster-onboarding")
    print("  ~/.codex/skills/hpc-cluster-discovery")
    print("  ~/.codex/skills/hpc-filesystem-environment")
    print("  ~/.codex/skills/hpc-deploy-build")
    print("  ~/.codex/skills/hpc-slurm-jobs")
    print("  ~/.codex/skills/hpc-slurm-job-arrays")
    print("  ~/.codex/skills/hpc-slurm-benchmark")
    return 0

def cmd_plugins_list(args: argparse.Namespace, profile: Profile | None) -> int:
    del args, profile
    print(plugin_system.format_plugins(plugin_system.load_plugins()))
    return 0

def cmd_plugins_info(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    plugin = plugin_system.get_plugin(args.name)
    if plugin is None:
        raise ConfigError(f"unknown plugin: {args.name}")

    print(
        "\n".join(
            [
                f"name: {plugin.name}",
                f"version: {plugin.version}",
                f"source: {plugin.source}",
                f"description: {plugin.description}",
            ]
        )
    )
    return 0

def _doctor_command() -> str:
    return "; ".join(
        [
            _section_command("identity", "hostname; whoami; pwd"),
            _section_command(
                "slurm-tools",
                _tool_check_loop(["sbatch", "sinfo", "scontrol", "sacct", "sacctmgr"]),
            ),
        ]
    )

def _site_env_command() -> str:
    return "; ".join(
        [
            _section_command(
                "environment",
                "env | grep -Ei 'HOME|DATA|SCRATCH|WORK|PROJECT|TMP|SLURM' | sort || true",
            ),
            _section_command(
                "helper-tools",
                _tool_check_loop(["quota", "lfs", "beegfs-ctl", "mmlsquota", "module"]),
            ),
            _section_command("module-system", "module --version 2>&1 || true"),
        ]
    )

