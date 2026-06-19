from __future__ import annotations

import contextlib
import argparse
from dataclasses import asdict
import html
import io
import json
from datetime import datetime
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
import re
import shlex
import sys
import textwrap
from urllib.error import URLError
from urllib.request import urlopen

from hpc_tools.commands import register_builtin_commands
from hpc_tools.config import (
    ConfigError,
    Profile,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
    load_config,
    resolve_profile,
)
from hpc_tools.hardware import render_hardware_context
from hpc_tools import plugin_system
from hpc_tools import references
from hpc_tools.ssh import run_remote, run_remote_capture
from hpc_tools import slurm, submissions


LOCAL_COMMANDS = {
    "paths",
    "write-hardware-probe",
    "write-probe",
    "write-container",
    "submissions",
    "references",
    "plugins",
}
PROBE_KINDS = {"hardware", "cuda-device-properties"}
CONTAINER_KINDS = {"generic", "r", "conda"}
JSON_NATIVE_HANDLERS = {
    "cmd_benchmark_summarize",
    "cmd_benchmark_compare",
    "cmd_python_scan",
    "cmd_python_inspect_deps",
    "cmd_python_check",
    "cmd_python_verify_install",
    "cmd_r_scan",
    "cmd_r_check",
    "cmd_r_verify_install",
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


def build_parser(profile: Profile | None = None) -> argparse.ArgumentParser:
    parser = GroupedCommandParser(prog="hpc")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--profile", help="Profile name from the configuration file")
    parser.add_argument(
        "--config",
        help="Configuration file path; defaults to HPC_TOOLS_CONFIG, XDG_CONFIG_HOME, or ~/.config/hpc-tools/config.toml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the SSH command without executing it",
    )

    subparsers = GroupedSubparsers(
        parser.add_subparsers(dest="command", metavar="<command>", required=True)
    )

    register_builtin_commands(subparsers, profile, _command_handlers())

    with subparsers.group("Workflow plugins"):
        plugin_system.register_plugin_commands(subparsers, profile)
    parser.command_groups = subparsers.groups

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
        cmd_submit=cmd_submit,
        cmd_sacct=cmd_sacct,
        cmd_slurm_limits=cmd_slurm_limits,
        cmd_submissions_list=cmd_submissions_list,
        cmd_submissions_observe=cmd_submissions_observe,
        cmd_submissions_mark_collected=cmd_submissions_mark_collected,
        cmd_submissions_mark_analysed=cmd_submissions_mark_analysed,
        cmd_submissions_close=cmd_submissions_close,
    )


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    json_requested = False
    try:
        original_argv = list(argv)
        argv, json_requested = _strip_json_flag(argv)
        pre_args, _ = _build_pre_parser().parse_known_args(argv)
        if _should_parse_without_config(argv):
            parser = build_parser()
            args = parser.parse_args(argv)
            setattr(args, "json", getattr(args, "json", False) or json_requested)
            return _dispatch_command(args, None, json_requested, original_argv)
        config = load_config(pre_args.config)
        profile = resolve_profile(config, pre_args.profile)
        parser = build_parser(profile)
        args = parser.parse_args(argv)
        setattr(args, "json", getattr(args, "json", False) or json_requested)
        return _dispatch_command(args, profile, json_requested, original_argv)
    except ConfigError as error:
        if json_requested:
            print(
                json.dumps(
                    {
                        "error": str(error),
                        "returncode": 2,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        parser = build_parser()
        parser.exit(2, f"hpc: configuration error: {error}\n")


def _build_pre_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile")
    parser.add_argument("--config")
    return parser


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
    if not json_requested or args.handler.__name__ in JSON_NATIVE_HANDLERS:
        return args.handler(args, profile)

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = args.handler(args, profile)
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


def _add_probe_directive_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="Add #SBATCH --account=<account>")
    parser.add_argument("--cluster", "--clusters", dest="cluster", help="Add #SBATCH --clusters=<cluster>")
    parser.add_argument("--partition", help="Add #SBATCH --partition=<partition>")
    parser.add_argument("--qos", help="Add #SBATCH --qos=<qos>")
    parser.add_argument("--time", help="Replace the template #SBATCH --time value")
    parser.add_argument("--cpus-per-task", help="Add #SBATCH --cpus-per-task=<count>")
    parser.add_argument(
        "--mail-notifications",
        action="store_true",
        help="Add END,FAIL Slurm email notifications using the selected profile email",
    )
    parser.add_argument(
        "--mail-user",
        help="Add END,FAIL Slurm email notifications for this address",
    )


def _should_parse_without_config(argv: list[str]) -> bool:
    pre_args, remaining = _build_pre_parser().parse_known_args(argv)
    if any(arg in ("-h", "--help") for arg in remaining):
        return True
    if not remaining:
        return False
    if remaining[0] == "paths":
        return True
    if remaining[0] in {"write-hardware-probe", "write-probe", "write-container"}:
        return not (pre_args.profile or pre_args.config or "--mail-notifications" in remaining)
    if remaining[0] == "submissions":
        return not _submissions_needs_profile(remaining)
    if remaining[0] == "references":
        return not _references_needs_profile(remaining)
    plugin_requires_profile = plugin_system.plugin_needs_profile(remaining[0], remaining[1:])
    if plugin_requires_profile is not None:
        return not plugin_requires_profile
    return remaining[0] in LOCAL_COMMANDS


def _submissions_needs_profile(remaining: list[str]) -> bool:
    skip_next = False
    for arg in remaining[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-h", "--help"}:
            return False
        if arg == "--log":
            skip_next = True
            continue
        if not arg.startswith("-"):
            return arg == "observe"
    return False


def _references_needs_profile(remaining: list[str]) -> bool:
    skip_next = False
    for arg in remaining[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-h", "--help"}:
            return False
        if arg == "--output":
            skip_next = True
            continue
        if not arg.startswith("-"):
            return arg in {"create", "attach", "detach"}
    return False


def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, args.remote_command, dry_run=args.dry_run)


def cmd_doctor(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _doctor_command(), dry_run=args.dry_run)


def cmd_site_env(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _site_env_command(), dry_run=args.dry_run)


def cmd_storage_inspect(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _storage_inspect_command(args.path), dry_run=args.dry_run)


def cmd_repo_status(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _repo_status_command(args.directory), dry_run=args.dry_run)


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


def cmd_references_list(args: argparse.Namespace, profile: Profile | None) -> int:
    del args, profile
    print(references.format_reference_set_list(references.list_reference_sets()))
    return 0


def cmd_references_show(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    print(references.format_reference_set(references.load_reference_set(args.name)))
    return 0


def cmd_references_validate(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    reference_set = references.validate_reference_set(args.name)
    print(f"Reference set '{reference_set.name}' is valid: {reference_set.path}")
    return 0


def cmd_references_create(args: argparse.Namespace, profile: Profile) -> int:
    reference_set = references.create_reference_set(args.name, profile, force=args.force)
    print(f"Reference set created: {reference_set.path}")
    return 0


def cmd_references_export(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    archive_path = references.export_reference_set(
        args.name,
        output=args.output,
        force=args.force,
    )
    print(f"Reference set archive written: {archive_path}")
    return 0


def cmd_references_import(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    reference_set = references.import_reference_set(args.archive, force=args.force)
    print(f"Reference set imported: {reference_set.path}")
    return 0


def cmd_references_attach(args: argparse.Namespace, profile: Profile) -> int:
    references.load_reference_set(args.name)
    references.set_profile_reference_set(
        Path(args.config).expanduser() if args.config else default_config_path(),
        profile.name,
        args.name,
    )
    print(f"Attached reference set '{args.name}' to profile '{profile.name}'.")
    return 0


def cmd_references_detach(args: argparse.Namespace, profile: Profile) -> int:
    references.set_profile_reference_set(
        Path(args.config).expanduser() if args.config else default_config_path(),
        profile.name,
        None,
    )
    print(f"Detached any reference set from profile '{profile.name}'.")
    return 0


def cmd_quota(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.quota_command:
        raise ConfigError(f"profile '{profile.name}' does not define quota_command")
    return run_remote(profile, profile.quota_command, dry_run=args.dry_run)


def cmd_projects(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.projects_dir:
        raise ConfigError(f"profile '{profile.name}' does not define projects_dir")
    remote_path = _quote_remote_path_expression(profile.projects_dir)
    command = f"ls -ld {remote_path} 2>/dev/null && ls -1 {remote_path}"
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_clone(args: argparse.Namespace, profile: Profile) -> int:
    directory = args.directory or profile.projects_dir
    if not directory:
        raise ConfigError(
            f"profile '{profile.name}' does not define projects_dir; pass --directory"
        )
    parts = ["git", "clone"]
    if args.branch:
        parts.extend(["--branch", args.branch])
    parts.append(args.url)
    if args.name:
        parts.append(args.name)
    command = f"cd {_quote_remote_path_expression(directory)} && {' '.join(shlex.quote(part) for part in parts)}"
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_module_spider(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, _module_spider_command(args.name), dry_run=args.dry_run)


def cmd_hardware(args: argparse.Namespace, profile: Profile) -> int:
    if args.source and args.path:
        raise ConfigError("use only one of --source or --path")
    print(render_hardware_context(profile, source_only=args.source, path_only=args.path))
    return 0


def cmd_write_hardware_probe(args: argparse.Namespace, profile: Profile | None) -> int:
    args.kind = "hardware"
    return cmd_write_probe(args, profile)


def cmd_install_hardware_probe(args: argparse.Namespace, profile: Profile) -> int:
    args.kind = "hardware"
    if not getattr(args, "name", None):
        args.name = "hardware-probe.slurm"
    return cmd_install_probe(args, profile)


def cmd_write_probe(args: argparse.Namespace, profile: Profile | None) -> int:
    if args.kind == "hardware":
        template = _hardware_probe_template(args, profile)
        if args.output == "-":
            sys.stdout.write(template)
            return 0

        output_path = Path(args.output).expanduser()
        if output_path.exists() and not args.force:
            raise ConfigError(f"output file already exists: {output_path}; use --force to overwrite")
        output_path.write_text(template, encoding="utf-8")
        return 0

    if args.kind == "cuda-device-properties":
        if args.output == "-":
            raise ConfigError("write-probe --kind cuda-device-properties requires an output directory")
        _write_cuda_device_properties_bundle(Path(args.output).expanduser(), force=args.force)
        return 0

    raise ConfigError(f"unsupported probe kind: {args.kind}")


def cmd_install_probe(args: argparse.Namespace, profile: Profile) -> int:
    if args.kind == "hardware":
        command = _install_hardware_probe_command(
            args.directory,
            args.name or "hardware-probe.slurm",
            _hardware_probe_template(args, profile),
            force=args.force,
        )
    elif args.kind == "cuda-device-properties":
        command = _install_cuda_device_properties_command(
            args.directory,
            args.name or "cuda-device-properties.slurm",
            force=args.force,
        )
    else:
        raise ConfigError(f"unsupported probe kind: {args.kind}")
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_write_container(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    bundle = _container_bundle(args.kind)
    output_dir = Path(args.output).expanduser()
    _write_bundle_assets(output_dir, bundle, force=args.force)
    print(f"Container bundle written to {output_dir}")
    return 0


def cmd_install_container(args: argparse.Namespace, profile: Profile) -> int:
    bundle = _container_bundle(args.kind)
    command = _install_bundle_command(
        directory=args.directory,
        bundle=bundle,
        force=args.force,
    )
    return run_remote(profile, command, dry_run=args.dry_run)


def _hardware_probe_template(args: argparse.Namespace | None = None, profile: Profile | None = None) -> str:
    template = resources.files("hpc_tools.data").joinpath("hardware-probe.slurm").read_text(
        encoding="utf-8"
    )
    if args is None:
        return template

    insertions = []
    mail_user = _resolve_mail_user(args, profile)
    for option_name, directive_name in [
        ("account", "account"),
        ("cluster", "clusters"),
        ("partition", "partition"),
        ("qos", "qos"),
        ("cpus_per_task", "cpus-per-task"),
    ]:
        value = getattr(args, option_name, None)
        if value:
            insertions.append(f"#SBATCH --{directive_name}={value}")
    if mail_user:
        insertions.append(f"#SBATCH --mail-user={mail_user}")
        insertions.append("#SBATCH --mail-type=END,FAIL")

    rendered = []
    inserted = False
    for line in template.splitlines():
        if line.startswith("#SBATCH --time=") and getattr(args, "time", None):
            rendered.append(f"#SBATCH --time={args.time}")
            continue
        rendered.append(line)
        if line.startswith("#SBATCH --output=") and not inserted:
            rendered.extend(insertions)
            inserted = True
    return "\n".join(rendered) + "\n"


def _resolve_mail_user(args: argparse.Namespace, profile: Profile | None) -> str | None:
    mail_user = getattr(args, "mail_user", None)
    if mail_user:
        return mail_user
    if not getattr(args, "mail_notifications", False):
        return None
    if profile is None or profile.email is None:
        raise ConfigError("--mail-notifications requires a selected profile with an email field")
    return profile.email


def _install_hardware_probe_command(
    directory: str,
    name: str,
    contents: str,
    *,
    force: bool = False,
) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    remote_name = shlex.quote(name)
    overwrite_check = ""
    if not force:
        overwrite_check = (
            f"if [ -e {remote_name} ]; then "
            f"echo 'output file already exists: {name}; use --force to overwrite' >&2; "
            "exit 1; "
            "fi\n"
        )
    delimiter = "HPC_TOOLS_HARDWARE_PROBE_TEMPLATE"
    return (
        f"mkdir -p {remote_dir} && cd {remote_dir} && "
        f"{overwrite_check}"
        f"cat > {remote_name} <<'{delimiter}'\n"
        f"{contents}"
        f"{delimiter}\n"
        f"chmod +x {remote_name}"
    )


def _cuda_device_properties_bundle() -> dict[str, str]:
    data = resources.files("hpc_tools.data")
    return {
        "cuda-device-properties.slurm": data.joinpath("cuda-device-properties.slurm").read_text(
            encoding="utf-8"
        ),
        "cuda/CMakeLists.txt": data.joinpath("cuda", "CMakeLists.txt").read_text(
            encoding="utf-8"
        ),
        "cuda/device_properties.cu": data.joinpath("cuda", "device_properties.cu").read_text(
            encoding="utf-8"
        ),
    }


def _container_bundle(kind: str) -> dict[str, str]:
    data = resources.files("hpc_tools.data").joinpath("containers", "apptainer" if kind == "generic" else kind)
    if kind == "generic":
        return {
            "create_apptainer_container.slurm": data.joinpath("create_apptainer_container.slurm").read_text(
                encoding="utf-8"
            ),
        }
    if kind == "r":
        return {
            "create_r_container.slurm": data.joinpath("create_r_container.slurm").read_text(
                encoding="utf-8"
            ),
            "apt_packages.txt": data.joinpath("apt_packages.txt").read_text(encoding="utf-8"),
            "install_packages.R": data.joinpath("install_packages.R").read_text(encoding="utf-8"),
            "labels.txt": data.joinpath("labels.txt").read_text(encoding="utf-8"),
        }
    if kind == "conda":
        return {
            "create_conda_container.slurm": data.joinpath("create_conda_container.slurm").read_text(
                encoding="utf-8"
            ),
            "environment.yml": data.joinpath("environment.yml").read_text(encoding="utf-8"),
            "labels.txt": data.joinpath("labels.txt").read_text(encoding="utf-8"),
        }
    raise ConfigError(f"unsupported container kind: {kind}")


def _fetch_status_page(url: str) -> str:
    try:
        with urlopen(url, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except (URLError, TimeoutError, OSError) as error:
        raise ConfigError(f"failed to fetch status page {url}: {error}") from error

    text = _html_to_text(body)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return f"{url} (no text content found)"
    return "\n".join(lines[:20])


def _html_to_text(document: str) -> str:
    document = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", document)
    document = re.sub(r"(?i)<br\s*/?>", "\n", document)
    document = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", document)
    document = re.sub(r"<[^>]+>", " ", document)
    document = html.unescape(document)
    document = re.sub(r"[ \t\r\f\v]+", " ", document)
    document = re.sub(r"\n+", "\n", document)
    return document.strip()


def _write_bundle_assets(output_dir: Path, bundle: dict[str, str], *, force: bool = False) -> None:
    for relative_path in bundle:
        destination = output_dir / relative_path
        if destination.exists() and not force:
            raise ConfigError(f"output file already exists: {destination}; use --force to overwrite")

    for relative_path, contents in bundle.items():
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    for relative_path in bundle:
        if relative_path.endswith(".slurm"):
            (output_dir / relative_path).chmod(0o755)


def _install_bundle_command(*, directory: str, bundle: dict[str, str], force: bool = False) -> str:
    remote_dir = slurm._quote_remote_path_expression(directory)
    commands = [f"mkdir -p {remote_dir} && cd {remote_dir}"]
    if not force:
        for relative_path in bundle:
            quoted_path = shlex.quote(relative_path)
            commands.append(
                f"if [ -e {quoted_path} ]; then "
                f"echo 'output file already exists: {relative_path}; use --force to overwrite' >&2; "
                "exit 1; "
                "fi"
            )
    for index, (relative_path, contents) in enumerate(bundle.items()):
        quoted_path = shlex.quote(relative_path)
        delimiter = f"HPC_TOOLS_CONTAINER_BUNDLE_{index}"
        commands.append(
            f"cat > {quoted_path} <<'{delimiter}'\n"
            f"{contents}"
            f"{delimiter}\n"
        )
    for relative_path in bundle:
        if relative_path.endswith(".slurm"):
            commands.append(f"chmod +x {shlex.quote(relative_path)}")
    return "\n".join(commands)


def _write_cuda_device_properties_bundle(output_dir: Path, *, force: bool = False) -> None:
    bundle = _cuda_device_properties_bundle()
    for relative_path in bundle:
        destination = output_dir / relative_path
        if destination.exists() and not force:
            raise ConfigError(f"output file already exists: {destination}; use --force to overwrite")

    for relative_path, contents in bundle.items():
        destination = output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    (output_dir / "cuda-device-properties.slurm").chmod(0o755)


def _install_cuda_device_properties_command(
    directory: str,
    script_name: str,
    *,
    force: bool = False,
) -> str:
    bundle = _cuda_device_properties_bundle()
    remote_dir = slurm._quote_remote_path_expression(directory)
    script_path = shlex.quote(script_name)
    file_map = {
        script_name: bundle["cuda-device-properties.slurm"],
        "cuda/CMakeLists.txt": bundle["cuda/CMakeLists.txt"],
        "cuda/device_properties.cu": bundle["cuda/device_properties.cu"],
    }

    overwrite_checks = []
    if not force:
        for relative_path in file_map:
            quoted_path = shlex.quote(relative_path)
            overwrite_checks.append(
                f"if [ -e {quoted_path} ]; then "
                f"echo 'output file already exists: {relative_path}; use --force to overwrite' >&2; "
                "exit 1; "
                "fi"
            )

    commands = [f"mkdir -p {remote_dir} && cd {remote_dir} && mkdir -p cuda"]
    commands.extend(overwrite_checks)
    for index, (relative_path, contents) in enumerate(file_map.items()):
        quoted_path = shlex.quote(relative_path)
        delimiter = f"HPC_TOOLS_CUDA_DEVICE_PROPERTIES_{index}"
        commands.append(
            f"cat > {quoted_path} <<'{delimiter}'\n"
            f"{contents}"
            f"{delimiter}\n"
        )
    commands.append(f"chmod +x {script_path}")
    return "\n".join(commands)


def cmd_queue(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.queue_command:
        raise ConfigError(f"profile '{profile.name}' does not define queue_command")
    return run_remote(
        profile,
        slurm.queue_state_command(profile.queue_command),
        dry_run=args.dry_run,
    )


def cmd_balance(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_balance_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_balance_command")
    return run_remote(profile, profile.sam_balance_command, dry_run=args.dry_run)


def cmd_statement(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_statement_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_statement_command")
    command = _statement_command(
        profile.sam_statement_command,
        account=args.account,
        start=args.start,
        end=args.end,
    )
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_quote(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.sam_quote_command:
        raise ConfigError(f"profile '{profile.name}' does not define sam_quote_command")
    command = _quote_command(profile.sam_quote_command, args.quote_args)
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_status(args: argparse.Namespace, profile: Profile) -> int:
    report = build_status_report(profile, dry_run=args.dry_run)

    for index, section in enumerate(report["sections"]):
        if index:
            print()
        print(f"== {section['title']} ==")
        lines = section["lines"]
        if lines:
            for line in lines:
                print(line)
        else:
            print("No data.")

    return 0 if report["failures"] == 0 else 1


def build_status_report(profile: Profile, *, dry_run: bool = False) -> dict[str, object]:
    failures = 0
    sections: list[dict[str, object]] = []

    if profile.status_url:
        try:
            status_text = _fetch_status_page(profile.status_url)
        except ConfigError as error:
            sections.append(
                {
                    "title": "status page",
                    "ok": False,
                    "source": profile.status_url,
                    "lines": [f"status page unavailable: {error}"],
                }
            )
            failures += 1
        else:
            sections.append(
                {
                    "title": "status page",
                    "ok": True,
                    "source": profile.status_url,
                    "lines": status_text.splitlines(),
                }
            )
    else:
        sections.append(
            {
                "title": "status page",
                "ok": False,
                "source": None,
                "lines": [f"profile '{profile.name}' does not define status_url"],
            }
        )
        failures += 1

    if profile.quota_command:
        quota_result = run_remote_capture(profile, profile.quota_command, dry_run=dry_run)
        if quota_result.returncode != 0:
            failures += 1
            sections.append(
                {
                    "title": "quota",
                    "ok": False,
                    "command": profile.quota_command,
                    "returncode": quota_result.returncode,
                    "stderr": quota_result.stderr,
                    "lines": [f"quota check failed with return code {quota_result.returncode}"],
                }
            )
        else:
            quota_text = quota_result.stdout.strip()
            sections.append(
                {
                    "title": "quota",
                    "ok": True,
                    "command": profile.quota_command,
                    "returncode": quota_result.returncode,
                    "stderr": quota_result.stderr,
                    "lines": quota_text.splitlines() if quota_text else [],
                }
            )
    else:
        sections.append(
            {
                "title": "quota",
                "ok": False,
                "command": None,
                "lines": [f"profile '{profile.name}' does not define quota_command"],
            }
        )
        failures += 1

    if profile.sam_balance_command:
        balance_result = run_remote_capture(profile, profile.sam_balance_command, dry_run=dry_run)
        if balance_result.returncode != 0:
            failures += 1
            sections.append(
                {
                    "title": "balance",
                    "ok": False,
                    "command": profile.sam_balance_command,
                    "returncode": balance_result.returncode,
                    "stderr": balance_result.stderr,
                    "lines": [f"balance check failed with return code {balance_result.returncode}"],
                }
            )
        else:
            balance_text = balance_result.stdout.strip()
            sections.append(
                {
                    "title": "balance",
                    "ok": True,
                    "command": profile.sam_balance_command,
                    "returncode": balance_result.returncode,
                    "stderr": balance_result.stderr,
                    "lines": balance_text.splitlines() if balance_text else [],
                }
            )
    else:
        sections.append(
            {
                "title": "balance",
                "ok": False,
                "command": None,
                "lines": [f"profile '{profile.name}' does not define sam_balance_command"],
            }
        )
        failures += 1

    records = submissions.active_records(submissions.read_events())
    sections.append(
        {
            "title": "submissions",
            "ok": True,
            "lines": submissions.format_records(records).splitlines(),
        }
    )

    return {
        "profile": profile.name,
        "dry_run": dry_run,
        "failures": failures,
        "ok": failures == 0,
        "sections": sections,
        "submissions": [asdict(record) for record in records],
    }


def cmd_jobs(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, slurm.squeue_user_command(args.cluster), dry_run=args.dry_run)


def cmd_job(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, slurm.squeue_job_command(args.jobid, args.cluster), dry_run=args.dry_run)


def cmd_submit(args: argparse.Namespace, profile: Profile) -> int:
    overrides = _submit_overrides(args)
    command = slurm.submit_command(
        args.jobscript,
        directory=args.directory,
        test_only=args.test_only,
        overrides=overrides,
    )
    validation_command = slurm.submit_command(
        args.jobscript,
        directory=args.directory,
        test_only=True,
        overrides=overrides,
    )
    if args.dry_run:
        if args.validate_first and not args.test_only:
            run_remote(profile, validation_command, dry_run=True)
        return run_remote(profile, command, dry_run=True)
    if args.test_only:
        return run_remote(profile, command, dry_run=False)

    if args.validate_first:
        validation = run_remote_capture(profile, validation_command)
        if validation.stdout:
            print(validation.stdout, end="")
        if validation.stderr:
            print(validation.stderr, end="", file=sys.stderr)
        if validation.returncode != 0:
            return validation.returncode

    completed = run_remote_capture(profile, command)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode == 0:
        _log_submission(
            profile=profile,
            args=args,
            command=command,
            overrides=overrides,
            sbatch_output=completed.stdout + completed.stderr,
        )
    return completed.returncode


def _add_submit_override_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", "-A", help="Override sbatch --account")
    parser.add_argument("--array", help="Override sbatch --array")
    parser.add_argument("--cluster", "-M", help="Override sbatch --clusters")
    parser.add_argument("--dependency", help="Add sbatch --dependency")
    parser.add_argument("--error", help="Override sbatch --error")
    parser.add_argument("--export", dest="export", help="Override sbatch --export")
    parser.add_argument("--job-name", help="Override sbatch --job-name")
    parser.add_argument("--output", help="Override sbatch --output")
    parser.add_argument("--partition", "-p", help="Override sbatch --partition")
    parser.add_argument("--reservation", help="Override sbatch --reservation")
    parser.add_argument("--time", "-t", help="Override sbatch --time")

    parser.add_argument("--nodes", "-N", help="Override sbatch --nodes")
    parser.add_argument("--ntasks", "-n", help="Override sbatch --ntasks")
    parser.add_argument("--ntasks-per-node", help="Override sbatch --ntasks-per-node")
    parser.add_argument("--cpus-per-task", "-c", help="Override sbatch --cpus-per-task")
    parser.add_argument("--mem", help="Override sbatch --mem")
    parser.add_argument("--mem-per-cpu", help="Override sbatch --mem-per-cpu")

    parser.add_argument("--gres", help="Override sbatch --gres")
    parser.add_argument("--gpus", help="Override sbatch --gpus")
    parser.add_argument("--gpus-per-node", help="Override sbatch --gpus-per-node")
    parser.add_argument("--gpus-per-task", help="Override sbatch --gpus-per-task")
    parser.add_argument("--gpu-bind", help="Override sbatch --gpu-bind")


def _submit_overrides(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        name: getattr(args, name)
        for name in slurm.SUBMIT_OPTION_NAMES
    }


def _log_submission(
    *,
    profile: Profile,
    args: argparse.Namespace,
    command: str,
    overrides: dict[str, str | None],
    sbatch_output: str,
) -> None:
    try:
        job_id, cluster = submissions.parse_sbatch_submission(sbatch_output)
    except ValueError as error:
        print(f"hpc: warning: {error}; submission was not logged", file=sys.stderr)
        return
    event = submissions.submitted_event(
        profile=profile.name,
        job_id=job_id,
        cluster=cluster or args.cluster or profile.default_cluster,
        remote_directory=args.directory,
        jobscript=args.jobscript,
        submit_command=command,
        overrides=overrides,
    )
    submissions.append_event(event)


def cmd_submissions_list(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    events = submissions.read_events(args.log)
    records = (
        submissions.records_from_events(events)
        if args.all
        else submissions.active_records(events)
    )
    print(submissions.format_records(records))
    return 0


def cmd_submissions_observe(args: argparse.Namespace, profile: Profile) -> int:
    events = submissions.read_events(args.log)
    records = submissions.active_records(events)
    if args.run_id:
        records = [record for record in records if record.run_id == args.run_id]
    records = [record for record in records if record.profile == profile.name]
    if not records:
        print("No active submissions to observe.")
        return 0

    observed_records = []
    for record in records:
        command = submissions.sacct_observe_command(record.job_id, record.cluster)
        completed = run_remote_capture(profile, command, dry_run=args.dry_run)
        if args.dry_run:
            continue
        if completed.returncode != 0:
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
            continue
        raw_output = completed.stdout
        state, exit_code, elapsed = submissions.parse_sacct_observation(raw_output, record.job_id)
        submissions.append_event(
            submissions.observed_event(
                record,
                state=state,
                exit_code=exit_code,
                elapsed=elapsed,
                raw_output=raw_output,
            ),
            path=args.log,
        )
        observed_records.append(record)

    if args.dry_run:
        print("Dry run; no observations appended.")
        return 0

    refreshed_events = submissions.read_events(args.log)
    observed_run_ids = {record.run_id for record in observed_records}
    refreshed_records = [
        record for record in submissions.records_from_events(refreshed_events)
        if record.run_id in observed_run_ids
    ]
    print(submissions.format_records(refreshed_records))
    return 0


def cmd_submissions_mark_collected(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    submissions.append_event(
        submissions.mark_event(args.run_id, "results_collected", path=args.path),
        path=args.log,
    )
    return 0


def cmd_submissions_mark_analysed(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    submissions.append_event(
        submissions.mark_event(args.run_id, "analysed", path=args.path),
        path=args.log,
    )
    return 0


def cmd_submissions_close(args: argparse.Namespace, profile: Profile | None) -> int:
    del profile
    submissions.append_event(
        submissions.mark_event(args.run_id, "closed", reason=args.reason),
        path=args.log,
    )
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


def cmd_sacct(args: argparse.Namespace, profile: Profile) -> int:
    cluster = args.cluster or profile.default_cluster
    return run_remote(profile, slurm.sacct_command(args.jobid, cluster), dry_run=args.dry_run)


def cmd_slurm_limits(args: argparse.Namespace, profile: Profile) -> int:
    cluster = args.cluster or profile.default_cluster
    return run_remote(
        profile,
        slurm.slurm_limits_command(
            cluster=cluster,
            partition=args.partition,
            qos=args.qos,
        ),
        dry_run=args.dry_run,
    )


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


def _module_spider_command(name: str) -> str:
    return f"module spider {shlex.quote(name)} 2>&1"


def _storage_inspect_command(path: str) -> str:
    remote_path = _quote_remote_path_expression(path)
    return "; ".join(
        [
            _section_command("path", f"pwd; ls -ld {remote_path} 2>/dev/null || true"),
            _section_command(
                "filesystem",
                f"df -hT {remote_path} 2>/dev/null || df -h {remote_path} 2>/dev/null || true",
            ),
            _section_command("usage", f"du -sh {remote_path} 2>/dev/null || true"),
            _section_command("mounts", "mount | sed -n '1,80p'"),
        ]
    )


def _repo_status_command(directory: str) -> str:
    remote_dir = _quote_remote_path_expression(directory)
    return (
        f"test -d {remote_dir} && cd {remote_dir} && {{ "
        "printf '\\n## repository\\n'; pwd; "
        "printf '\\n## status\\n'; git status --short --branch; "
        "printf '\\n## remotes\\n'; git remote -v; "
        "printf '\\n## latest-commit\\n'; git log -1 --oneline; "
        "}"
    )


def _tool_check_loop(tools: list[str]) -> str:
    quoted_tools = " ".join(shlex.quote(tool) for tool in tools)
    return (
        f"for tool in {quoted_tools}; do "
        "printf '%s: ' \"$tool\"; command -v \"$tool\" || true; "
        "done"
    )


def _section_command(title: str, command: str) -> str:
    return f"printf '\\n## {title}\\n'; {command}"


def _quote_remote_path_expression(path: str) -> str:
    if path.startswith("$") or path.startswith("~"):
        return path
    return shlex.quote(path)


def _statement_command(
    base_command: str,
    *,
    account: str,
    start: str | None = None,
    end: str | None = None,
) -> str:
    parts = [base_command, "--account", shlex.quote(account)]
    if start:
        _validate_date(start, "start")
        parts.extend(["--start", shlex.quote(start)])
    if end:
        _validate_date(end, "end")
        parts.extend(["--end", shlex.quote(end)])
    return " ".join(parts)


def _quote_command(base_command: str, quote_args: list[str]) -> str:
    if not quote_args:
        raise ConfigError("quote requires a submit command: sbatch, srun, or salloc")

    submit_command = quote_args[0]
    if submit_command not in {"sbatch", "srun", "salloc"}:
        raise ConfigError("quote first argument must be one of: sbatch, srun, salloc")

    if not _quote_args_have_account(quote_args[1:]):
        raise ConfigError("quote requires a Slurm account option: -A <account> or --account <account>")

    return " ".join([base_command, *(shlex.quote(part) for part in quote_args)])


def _quote_args_have_account(args: list[str]) -> bool:
    for index, arg in enumerate(args):
        if arg in {"-A", "--account"}:
            return index + 1 < len(args) and bool(args[index + 1])
        if arg.startswith("--account=") and arg != "--account=":
            return True
        if arg.startswith("-A") and arg != "-A":
            return True
    return False


def _validate_date(value: str, name: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ConfigError(f"{name} date must use YYYY-mm-dd format: {value}") from error


if __name__ == "__main__":
    sys.exit(main())
