from __future__ import annotations

from typing import Any


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
