from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import textwrap

from hpc_tools import plugin_system
from hpc_tools.authorization import CapabilityAuthorizationError
from hpc_tools.capabilities import CAPABILITY_LEVELS
from hpc_tools.cli_visibility import apply_cli_visibility
from hpc_tools.commands import register_builtin_commands
from hpc_tools.commands.agent import cmd_agent_audit, cmd_agent_export
from hpc_tools.commands.common import (
    _quote_remote_path_expression,
    _section_command,
    _tool_check_loop,
)
from hpc_tools.commands.core import (
    _doctor_command,
    _site_env_command,
    cmd_capabilities,
    cmd_doctor,
    cmd_paths,
    cmd_plugins_info,
    cmd_plugins_list,
    cmd_run,
    cmd_site_env,
)
from hpc_tools.commands.probes import (
    _add_probe_directive_options,
    _container_bundle,
    _cuda_device_properties_bundle,
    _hardware_probe_template,
    _resolve_mail_user,
    _write_bundle_assets,
    _write_cuda_device_properties_bundle,
    cmd_install_container,
    cmd_install_hardware_probe,
    cmd_install_probe,
    cmd_write_container,
    cmd_write_hardware_probe,
    cmd_write_probe,
)
from hpc_tools.commands.references import (
    cmd_references_attach,
    cmd_references_create,
    cmd_references_detach,
    cmd_references_export,
    cmd_references_import,
    cmd_references_list,
    cmd_references_show,
    cmd_references_validate,
)
from hpc_tools.commands.remote import (
    _module_spider_command,
    _repo_status_command,
    cmd_clone,
    cmd_hardware,
    cmd_module_spider,
    cmd_projects,
    cmd_quota,
    cmd_repo_status,
    cmd_storage_inspect,
)
from hpc_tools.commands.slurm import (
    _add_submit_override_arguments,
    _fetch_status_page,
    _html_to_text,
    _log_submission,
    _quote_args_have_account,
    _quote_command,
    _statement_command,
    _submit_overrides,
    _validate_date,
    build_site_status_report,
    cmd_balance,
    cmd_cancel,
    cmd_job,
    cmd_jobs,
    cmd_queue,
    cmd_quote,
    cmd_sacct,
    cmd_slurm_limits,
    cmd_statement,
    cmd_status,
    cmd_submit,
)
from hpc_tools.commands.submissions import (
    cmd_submissions_close,
    cmd_submissions_list,
    cmd_submissions_mark_analysed,
    cmd_submissions_mark_collected,
    cmd_submissions_observe,
)
from hpc_tools.config import (
    ConfigError,
    Profile,
    default_config_path,
    load_config,
    resolve_profile,
)
from hpc_tools.execution import EXECUTOR_NAMES, executor_scope


LOCAL_COMMANDS = {
    "paths",
    "write-hardware-probe",
    "write-probe",
    "write-container",
    "submissions",
    "references",
    "plugins",
    "agent",
}
PROBE_KINDS = {"hardware", "cuda-device-properties"}
CONTAINER_KINDS = {"agent", "agent-boundary", "generic", "r", "conda"}
JSON_NATIVE_HANDLERS = {
    "cmd_capabilities",
    "cmd_benchmark_summarize",
    "cmd_benchmark_compare",
    "cmd_cxx_scan",
    "cmd_python_scan",
    "cmd_python_inspect_deps",
    "cmd_python_check",
    "cmd_python_verify_install",
    "cmd_r_scan",
    "cmd_r_check",
    "cmd_r_verify_install",
    "cmd_agent_audit",
    "cmd_agent_export",
}


class GroupedCommandParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.command_groups: list[CommandGroup] = []

    def format_help(self) -> str:
        help_text = super().format_help()
        if not self.command_groups:
            return help_text
        return _replace_command_help_section(help_text, self.command_groups)

    def error(self, message: str) -> None:
        message = re.sub(
            r"invalid choice: ([^ ]+) \(choose from .*\)",
            r"unknown or unavailable choice: \1",
            message,
        )
        super().error(message)


class CommandGroup(SimpleNamespace):
    title: str
    commands: list[tuple[str, str]]


class GroupedSubparsers:
    def __init__(self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        self._subparsers = subparsers
        self.groups: list[CommandGroup] = []
        self._current_group: CommandGroup | None = None

    def add_parser(self, name: str, **kwargs: object) -> argparse.ArgumentParser:
        parser = self._subparsers.add_parser(name, **kwargs)
        if self._current_group is not None:
            self._current_group.commands.append((name, str(kwargs.get("help", ""))))
        return parser

    @contextlib.contextmanager
    def group(self, title: str) -> object:
        group = CommandGroup(title=title, commands=[])
        self.groups.append(group)
        previous_group = self._current_group
        self._current_group = group
        try:
            yield
        finally:
            self._current_group = previous_group

    def __getattr__(self, name: str) -> object:
        return getattr(self._subparsers, name)


def build_parser(
    profile: Profile | None = None,
    *,
    show_disallowed: bool = False,
    capability: str | None = None,
    policy_filter: bool = False,
) -> argparse.ArgumentParser:
    parser = GroupedCommandParser(prog="hpc")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--profile", help="Profile name from the configuration file")
    parser.add_argument(
        "--config",
        help="Configuration file path; defaults to HPC_TOOLS_CONFIG, XDG_CONFIG_HOME, or ~/.config/hpc-tools/config.toml",
    )
    parser.add_argument(
        "--capability",
        choices=[level.value for level in CAPABILITY_LEVELS],
        help="Narrow command discovery to this capability level; never raises or changes execution authority",
    )
    parser.add_argument(
        "--show-disallowed",
        action="store_true",
        help="Show commands denied by the selected profile and annotate the reasons",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected executor command without executing it",
    )
    parser.add_argument(
        "--executor",
        choices=EXECUTOR_NAMES,
        help="Command executor; defaults to HPC_TOOLS_EXECUTOR or ssh",
    )

    subparsers = GroupedSubparsers(
        parser.add_subparsers(dest="command", metavar="<command>", required=True)
    )

    register_builtin_commands(subparsers, profile, _command_handlers())

    with subparsers.group("Workflow plugins"):
        plugin_system.register_plugin_commands(subparsers, profile)
    parser.command_groups = subparsers.groups

    if policy_filter:
        apply_cli_visibility(
            parser,
            profile,
            requested_level=capability,
            show_disallowed=show_disallowed,
        )

    return parser


def _replace_command_help_section(help_text: str, command_groups: list[CommandGroup]) -> str:
    lines = help_text.splitlines()
    try:
        start = lines.index("positional arguments:")
    except ValueError:
        return help_text
    if start + 1 >= len(lines) or not lines[start + 1].strip().startswith("<command>"):
        return help_text

    end = start + 1
    while end < len(lines) and lines[end] not in {"options:", "optional arguments:"}:
        end += 1
    if end == len(lines):
        return help_text

    command_lines = _format_command_groups(command_groups)
    return "\n".join([*lines[:start], *command_lines, "", *lines[end:]]) + "\n"


def _format_command_groups(command_groups: list[CommandGroup]) -> list[str]:
    lines = ["commands:"]
    command_names = [
        name
        for group in command_groups
        for name, _ in group.commands
    ]
    width = max([22, *(len(name) for name in command_names)]) + 2
    for group in command_groups:
        if not group.commands:
            continue
        lines.extend(["", f"  {group.title}:"])
        for name, help_text in group.commands:
            wrapped = textwrap.wrap(help_text, width=52) or [""]
            lines.append(f"    {name:<{width}} {wrapped[0]}".rstrip())
            for continuation in wrapped[1:]:
                lines.append(f"    {'':<{width}} {continuation}".rstrip())
    return lines


def _command_handlers() -> SimpleNamespace:
    return SimpleNamespace(
        PROBE_KINDS=PROBE_KINDS,
        CONTAINER_KINDS=CONTAINER_KINDS,
        add_probe_directive_options=_add_probe_directive_options,
        add_submit_override_arguments=_add_submit_override_arguments,
        cmd_run=cmd_run,
        cmd_capabilities=cmd_capabilities,
        cmd_doctor=cmd_doctor,
        cmd_site_env=cmd_site_env,
        cmd_storage_inspect=cmd_storage_inspect,
        cmd_repo_status=cmd_repo_status,
        cmd_paths=cmd_paths,
        cmd_plugins_list=cmd_plugins_list,
        cmd_plugins_info=cmd_plugins_info,
        cmd_references_list=cmd_references_list,
        cmd_references_show=cmd_references_show,
        cmd_references_validate=cmd_references_validate,
        cmd_references_create=cmd_references_create,
        cmd_references_export=cmd_references_export,
        cmd_references_import=cmd_references_import,
        cmd_references_attach=cmd_references_attach,
        cmd_references_detach=cmd_references_detach,
        cmd_write_probe=cmd_write_probe,
        cmd_write_hardware_probe=cmd_write_hardware_probe,
        cmd_install_probe=cmd_install_probe,
        cmd_write_container=cmd_write_container,
        cmd_install_container=cmd_install_container,
        cmd_install_hardware_probe=cmd_install_hardware_probe,
        cmd_quota=cmd_quota,
        cmd_projects=cmd_projects,
        cmd_clone=cmd_clone,
        cmd_module_spider=cmd_module_spider,
        cmd_hardware=cmd_hardware,
        cmd_queue=cmd_queue,
        cmd_balance=cmd_balance,
        cmd_statement=cmd_statement,
        cmd_quote=cmd_quote,
        cmd_status=cmd_status,
        cmd_jobs=cmd_jobs,
        cmd_job=cmd_job,
        cmd_cancel=cmd_cancel,
        cmd_submit=cmd_submit,
        cmd_sacct=cmd_sacct,
        cmd_slurm_limits=cmd_slurm_limits,
        cmd_submissions_list=cmd_submissions_list,
        cmd_submissions_observe=cmd_submissions_observe,
        cmd_submissions_mark_collected=cmd_submissions_mark_collected,
        cmd_submissions_mark_analysed=cmd_submissions_mark_analysed,
        cmd_submissions_close=cmd_submissions_close,
        cmd_agent_audit=cmd_agent_audit,
        cmd_agent_export=cmd_agent_export,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    json_requested = False
    try:
        original_argv = list(argv)
        argv, json_requested = _strip_json_flag(argv)
        pre_args, _ = _build_pre_parser().parse_known_args(argv)
        profile = _resolve_invocation_profile(argv, pre_args)
        parser = build_parser(
            profile,
            show_disallowed=pre_args.show_disallowed,
            capability=pre_args.capability,
            policy_filter=_help_requested(argv),
        )
        args = parser.parse_args(argv)
        setattr(args, "json", getattr(args, "json", False) or json_requested)
        return _dispatch_command(args, profile, json_requested, original_argv)
    except ConfigError as error:
        if json_requested:
            print(json.dumps(_error_payload(error), indent=2, sort_keys=True))
            return 2
        parser = build_parser(policy_filter=True)
        parser.exit(2, f"hpc: configuration error: {error}\n")


def _build_pre_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile")
    parser.add_argument("--config")
    parser.add_argument("--executor", choices=EXECUTOR_NAMES)
    parser.add_argument(
        "--capability",
        choices=[level.value for level in CAPABILITY_LEVELS],
    )
    parser.add_argument("--show-disallowed", action="store_true")
    return parser


def _resolve_invocation_profile(
    argv: list[str],
    pre_args: argparse.Namespace,
) -> Profile | None:
    config_path = (
        Path(pre_args.config).expanduser()
        if pre_args.config
        else default_config_path()
    )
    explicit_selection = bool(
        pre_args.profile
        or pre_args.config
        or "HPC_TOOLS_CONFIG" in os.environ
    )
    if explicit_selection:
        return resolve_profile(load_config(pre_args.config), pre_args.profile)
    if _help_requested(argv) and config_path.exists():
        return resolve_profile(load_config(pre_args.config), pre_args.profile)
    if not _should_parse_without_config(argv):
        return resolve_profile(load_config(pre_args.config), pre_args.profile)
    return None


def _help_requested(argv: list[str]) -> bool:
    return any(arg in {"-h", "--help"} for arg in argv)


def _strip_json_flag(argv: list[str]) -> tuple[list[str], bool]:
    cleaned: list[str] = []
    json_requested = False
    for arg in argv:
        if arg == "--json":
            json_requested = True
            continue
        cleaned.append(arg)
    return cleaned, json_requested


def _dispatch_command(
    args: argparse.Namespace,
    profile: Profile | None,
    json_requested: bool,
    original_argv: list[str],
) -> int:
    with executor_scope(args.executor):
        return _dispatch_with_executor(
            args,
            profile,
            json_requested,
            original_argv,
        )


def _dispatch_with_executor(
    args: argparse.Namespace,
    profile: Profile | None,
    json_requested: bool,
    original_argv: list[str],
) -> int:
    plugin_system.authorize_plugin_command(args, profile)
    if not json_requested or args.handler.__name__ in JSON_NATIVE_HANDLERS:
        return args.handler(args, profile)

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = args.handler(args, profile)
    except CapabilityAuthorizationError as error:
        print(json.dumps(_error_payload(error), indent=2, sort_keys=True))
        return 2
    except ConfigError as error:
        returncode = 2
        stderr.write(f"hpc: configuration error: {error}\n")

    print(
        json.dumps(
            {
                "argv": original_argv,
                "returncode": returncode,
                "stdout": stdout.getvalue(),
                "stderr": stderr.getvalue(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return returncode


def _error_payload(error: ConfigError) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": str(error),
        "returncode": 2,
    }
    if isinstance(error, CapabilityAuthorizationError):
        payload.update(error.decision.public_summary())
    return payload


def _should_parse_without_config(argv: list[str]) -> bool:
    pre_args, remaining = _build_pre_parser().parse_known_args(argv)
    if pre_args.profile or pre_args.config:
        return False
    if _help_requested(remaining) and pre_args.show_disallowed:
        return True
    if not remaining:
        return False
    if remaining[0] in {"-h", "--help"}:
        return True
    if remaining[0] == "paths":
        return True
    if remaining[0] in {"write-hardware-probe", "write-probe", "write-container"}:
        return _probe_stdout_without_profile(remaining)
    if remaining[0] == "submissions":
        return False
    if remaining[0] == "references":
        return not _references_needs_profile(remaining)
    plugin_requires_profile = plugin_system.plugin_needs_profile(remaining[0], remaining[1:])
    if plugin_requires_profile is not None:
        return not plugin_requires_profile
    if remaining[0] == "agent":
        return False
    return remaining[0] in LOCAL_COMMANDS


def _submissions_needs_profile(remaining: list[str]) -> bool:
    skip_next = False
    for arg in remaining[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-h", "--help"}:
            return False
        if arg == "--database":
            skip_next = True
            continue
        if not arg.startswith("-"):
            return arg == "observe"
    return False


def _probe_stdout_without_profile(remaining: list[str]) -> bool:
    if remaining[0] == "write-container" or "--mail-notifications" in remaining:
        return False
    options_with_values = {
        "--kind",
        "--account",
        "--cluster",
        "--clusters",
        "--partition",
        "--qos",
        "--time",
        "--cpus-per-task",
        "--mail-user",
    }
    positionals: list[str] = []
    skip_next = False
    for value in remaining[1:]:
        if skip_next:
            skip_next = False
            continue
        if value in options_with_values:
            skip_next = True
            continue
        if value.startswith("-") and value != "-":
            continue
        positionals.append(value)
    return not positionals or positionals == ["-"]


def _references_needs_profile(remaining: list[str]) -> bool:
    skip_next = False
    for arg in remaining[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-h", "--help"}:
            continue
        if arg == "--output":
            skip_next = True
            continue
        if not arg.startswith("-"):
            return arg in {"create", "export", "import", "attach", "detach"}
    return False


if __name__ == "__main__":
    sys.exit(main())
