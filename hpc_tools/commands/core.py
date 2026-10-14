from __future__ import annotations

import argparse
from importlib import resources
import json
from pathlib import Path
from typing import Any

from hpc_tools import plugin_system, submissions
from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.capabilities import narrow_policy
from hpc_tools.commands.common import _section_command, _tool_check_loop
from hpc_tools.config import (
    ConfigError,
    Profile,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
)
from hpc_tools.execution import run_command


def register(subparsers: Any, handlers: Any) -> None:
    register_local(subparsers, handlers)
    register_doctor(subparsers, handlers)
    register_site_env(subparsers, handlers)
    register_run(subparsers, handlers)


def register_run(subparsers: Any, handlers: Any) -> None:
    run_parser = subparsers.add_parser("run", help="Run a command on the remote host")
    run_parser.add_argument("remote_command", help="Command to run through the configured login shell")
    run_parser.set_defaults(handler=handlers.cmd_run, operation_id="remote.shell")


def register_doctor(subparsers: Any, handlers: Any) -> None:
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check remote login identity and core Slurm tool availability",
    )
    doctor_parser.set_defaults(handler=handlers.cmd_doctor, operation_id="cluster.doctor")


def register_site_env(subparsers: Any, handlers: Any) -> None:
    site_env_parser = subparsers.add_parser(
        "site-env",
        help="Inspect remote site environment variables and common HPC helper tools",
    )
    site_env_parser.set_defaults(handler=handlers.cmd_site_env, operation_id="cluster.site-env")


def register_local(subparsers: Any, handlers: Any) -> None:
    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Show the selected profile's effective capability grants",
    )
    capabilities_parser.set_defaults(
        handler=handlers.cmd_capabilities,
        operation_id="capabilities.show",
    )

    paths_parser = subparsers.add_parser(
        "paths",
        help="Show hpc-tools config, reference, skill, and package paths",
    )
    paths_parser.set_defaults(handler=handlers.cmd_paths, operation_id="paths.show")

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
    plugins_list_parser.set_defaults(handler=handlers.cmd_plugins_list, operation_id="plugins.list")

    plugins_info_parser = plugins_subparsers.add_parser(
        "info",
        help="Show one installed plugin",
    )
    plugins_info_parser.add_argument("name", help="Plugin name")
    plugins_info_parser.set_defaults(handler=handlers.cmd_plugins_info, operation_id="plugins.info")

def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("remote.shell", profile, namespace_arguments(args))
    return run_command(profile, args.remote_command, dry_run=args.dry_run)

def cmd_doctor(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("cluster.doctor", profile, namespace_arguments(args))
    return run_command(profile, _doctor_command(), dry_run=args.dry_run)

def cmd_site_env(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("cluster.site-env", profile, namespace_arguments(args))
    return run_command(profile, _site_env_command(), dry_run=args.dry_run)

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
    print(f"submissions_database: {submissions.default_database_path()}")
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


def cmd_capabilities(args: argparse.Namespace, profile: Profile | None) -> int:
    if profile is None:
        raise ConfigError("capabilities requires a selected profile")
    require_authorized("capabilities.show", profile, namespace_arguments(args))
    display_policy = narrow_policy(profile.capabilities, args.capability)
    payload = {
        "profile": profile.name,
        "source": {
            "config": (
                str(Path(args.config).expanduser())
                if args.config
                else str(default_config_path())
            ),
            "profile": profile.name,
        },
        "execution_grants": profile.capabilities.public_summary(),
        "display_grants": display_policy.public_summary(),
        "display_filter_only": True,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"profile: {payload['profile']}")
    print(f"source: {payload['source']['config']} [{profile.name}]")
    print(f"execution max level: {profile.capabilities.max_level.value}")
    print(f"display max level: {display_policy.max_level.value}")
    scopes = profile.capabilities.scopes
    print("scopes: " + (", ".join(scopes) if scopes else "none"))
    print("remote roots:")
    for grant, roots in profile.capabilities.remote_roots.public_summary().items():
        print(f"  {grant}: " + (", ".join(roots) if roots else "none"))
    print("display filter only: yes")
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
                f"contract: {'v' + str(plugin.contract_version) if plugin.available else 'rejected'}",
                f"status: {'available' if plugin.available else 'rejected'}",
                f"description: {plugin.description}",
                "operations: " + (
                    ", ".join(operation.id for operation in plugin.operations)
                    if plugin.operations
                    else "none"
                ),
                *(
                    [f"contract_error: {plugin.contract_error}"]
                    if plugin.contract_error
                    else []
                ),
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
