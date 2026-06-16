from __future__ import annotations

import contextlib
import argparse
import io
import json
from datetime import datetime
from importlib import resources
from pathlib import Path
import shlex
import sys

from hpc_tools.config import (
    ConfigError,
    Profile,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
    load_config,
    resolve_profile,
)
from hpc_tools.hardware import profile_has_hardware_context, render_hardware_context
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
    "cmd_python_scan",
    "cmd_python_inspect_deps",
    "cmd_python_check",
    "cmd_python_verify_install",
    "cmd_r_scan",
    "cmd_r_check",
    "cmd_r_verify_install",
}


def build_parser(profile: Profile | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpc")
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

    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    run_parser = subparsers.add_parser("run", help="Run a command on the remote host")
    run_parser.add_argument("remote_command", help="Command to run through the configured login shell")
    run_parser.set_defaults(handler=cmd_run)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check remote login identity and core Slurm tool availability",
    )
    doctor_parser.set_defaults(handler=cmd_doctor)

    site_env_parser = subparsers.add_parser(
        "site-env",
        help="Inspect remote site environment variables and common HPC helper tools",
    )
    site_env_parser.set_defaults(handler=cmd_site_env)

    storage_parser = subparsers.add_parser(
        "storage",
        help="Inspect remote filesystem paths and storage context",
    )
    storage_subparsers = storage_parser.add_subparsers(
        dest="storage_command",
        metavar="<subcommand>",
        required=True,
    )
    storage_inspect_parser = storage_subparsers.add_parser(
        "inspect",
        help="Inspect one remote path with bounded storage checks",
    )
    storage_inspect_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Remote path to inspect; defaults to the remote current directory",
    )
    storage_inspect_parser.set_defaults(handler=cmd_storage_inspect)

    repo_parser = subparsers.add_parser(
        "repo",
        help="Inspect remote source-code repositories",
    )
    repo_subparsers = repo_parser.add_subparsers(
        dest="repo_command",
        metavar="<subcommand>",
        required=True,
    )
    repo_status_parser = repo_subparsers.add_parser(
        "status",
        help="Show remote Git repository status, remotes, and latest commit",
    )
    repo_status_parser.add_argument(
        "--directory",
        "-C",
        required=True,
        help="Remote repository directory to inspect",
    )
    repo_status_parser.set_defaults(handler=cmd_repo_status)

    paths_parser = subparsers.add_parser(
        "paths",
        help="Show hpc-tools config, reference, skill, and package paths",
    )
    paths_parser.set_defaults(handler=cmd_paths)

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
    plugins_list_parser.set_defaults(handler=cmd_plugins_list)

    plugins_info_parser = plugins_subparsers.add_parser(
        "info",
        help="Show one installed plugin",
    )
    plugins_info_parser.add_argument("name", help="Plugin name")
    plugins_info_parser.set_defaults(handler=cmd_plugins_info)

    references_parser = subparsers.add_parser(
        "references",
        help="Manage shared cluster reference sets",
    )
    references_subparsers = references_parser.add_subparsers(
        dest="references_command",
        metavar="<subcommand>",
        required=True,
    )

    references_list_parser = references_subparsers.add_parser(
        "list",
        help="List installed shared reference sets",
    )
    references_list_parser.set_defaults(handler=cmd_references_list)

    references_show_parser = references_subparsers.add_parser(
        "show",
        help="Show one shared reference set",
    )
    references_show_parser.add_argument("name", help="Reference set name")
    references_show_parser.set_defaults(handler=cmd_references_show)

    references_validate_parser = references_subparsers.add_parser(
        "validate",
        help="Validate one shared reference set",
    )
    references_validate_parser.add_argument("name", help="Reference set name")
    references_validate_parser.set_defaults(handler=cmd_references_validate)

    references_create_parser = references_subparsers.add_parser(
        "create",
        help="Create a shared reference set from the selected profile",
    )
    references_create_parser.add_argument("name", help="Reference set name")
    references_create_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the destination reference set if it already exists",
    )
    references_create_parser.set_defaults(handler=cmd_references_create)

    references_export_parser = references_subparsers.add_parser(
        "export",
        help="Export one shared reference set as a tar.gz archive",
    )
    references_export_parser.add_argument("name", help="Reference set name")
    references_export_parser.add_argument(
        "--output",
        type=Path,
        help="Archive output path; defaults to ./<name>-reference-set.tar.gz",
    )
    references_export_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the archive if it already exists",
    )
    references_export_parser.set_defaults(handler=cmd_references_export)

    references_import_parser = references_subparsers.add_parser(
        "import",
        help="Import a shared reference set archive",
    )
    references_import_parser.add_argument("archive", type=Path, help="Reference set archive path")
    references_import_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing installed reference set",
    )
    references_import_parser.set_defaults(handler=cmd_references_import)

    references_attach_parser = references_subparsers.add_parser(
        "attach",
        help="Attach a shared reference set to the selected profile",
    )
    references_attach_parser.add_argument("name", help="Reference set name")
    references_attach_parser.set_defaults(handler=cmd_references_attach)

    references_detach_parser = references_subparsers.add_parser(
        "detach",
        help="Detach any shared reference set from the selected profile",
    )
    references_detach_parser.set_defaults(handler=cmd_references_detach)

    generic_probe_parser = subparsers.add_parser(
        "write-probe",
        help="Write a packaged probe script or probe asset bundle",
    )
    generic_probe_parser.add_argument(
        "--kind",
        choices=sorted(PROBE_KINDS),
        default="hardware",
        help="Packaged probe kind to write",
    )
    generic_probe_parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help="Output file for hardware, output directory for bundle probes, or '-' for hardware stdout.",
    )
    generic_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    _add_probe_directive_options(generic_probe_parser)
    generic_probe_parser.set_defaults(handler=cmd_write_probe)

    probe_parser = subparsers.add_parser(
        "write-hardware-probe",
        help="Write the packaged Slurm hardware probe script",
    )
    probe_parser.add_argument(
        "output",
        nargs="?",
        default="-",
        help="Output path, or '-' for stdout. Defaults to stdout.",
    )
    probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    _add_probe_directive_options(probe_parser)
    probe_parser.set_defaults(handler=cmd_write_hardware_probe)

    generic_install_probe_parser = subparsers.add_parser(
        "install-probe",
        help="Install a packaged probe script or probe asset bundle on the remote host",
    )
    generic_install_probe_parser.add_argument(
        "--kind",
        choices=sorted(PROBE_KINDS),
        default="hardware",
        help="Packaged probe kind to install",
    )
    generic_install_probe_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory where the probe assets should be written",
    )
    generic_install_probe_parser.add_argument(
        "--name",
        help="Remote script filename; defaults depend on --kind",
    )
    generic_install_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote files if they already exist",
    )
    _add_probe_directive_options(generic_install_probe_parser)
    generic_install_probe_parser.set_defaults(handler=cmd_install_probe)

    container_parser = subparsers.add_parser(
        "write-container",
        help="Write a packaged Apptainer container build bundle",
    )
    container_parser.add_argument(
        "--kind",
        choices=sorted(CONTAINER_KINDS),
        required=True,
        help="Packaged container bundle to write",
    )
    container_parser.add_argument(
        "output",
        help="Output directory for the container bundle",
    )
    container_parser.add_argument(
        "--name",
        help="Primary Slurm script filename; defaults depend on --kind",
    )
    container_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output path if it already exists",
    )
    container_parser.set_defaults(handler=cmd_write_container)

    install_container_parser = subparsers.add_parser(
        "install-container",
        help="Install a packaged Apptainer container build bundle on the remote host",
    )
    install_container_parser.add_argument(
        "--kind",
        choices=sorted(CONTAINER_KINDS),
        required=True,
        help="Packaged container bundle to install",
    )
    install_container_parser.add_argument(
        "--directory",
        "-C",
        required=True,
        help="Remote directory where the bundle should be written",
    )
    install_container_parser.add_argument(
        "--name",
        help="Primary Slurm script filename; defaults depend on --kind",
    )
    install_container_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote files if they already exist",
    )
    install_container_parser.set_defaults(handler=cmd_install_container)

    install_probe_parser = subparsers.add_parser(
        "install-hardware-probe",
        help="Install the packaged Slurm hardware probe script on the remote host",
    )
    install_probe_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory where the probe script should be written",
    )
    install_probe_parser.add_argument(
        "--name",
        default="hardware-probe.slurm",
        help="Remote script filename",
    )
    install_probe_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite remote script if it already exists",
    )
    _add_probe_directive_options(install_probe_parser)
    install_probe_parser.set_defaults(handler=cmd_install_hardware_probe)

    if profile is None or profile.quota_command:
        quota_parser = subparsers.add_parser("quota", help="Show remote quota usage")
        quota_parser.set_defaults(handler=cmd_quota)

    projects_parser = subparsers.add_parser("projects", help="List the remote project directory")
    projects_parser.set_defaults(handler=cmd_projects)

    clone_parser = subparsers.add_parser("clone", help="Clone a Git repository into a remote directory")
    clone_parser.add_argument("url", help="Git repository URL")
    clone_parser.add_argument("--branch", "-b", help="Branch to clone")
    clone_parser.add_argument(
        "--directory",
        "-C",
        help="Remote parent directory for the clone; defaults to profile projects_dir",
    )
    clone_parser.add_argument(
        "--name",
        help="Optional destination directory name passed to git clone",
    )
    clone_parser.set_defaults(handler=cmd_clone)

    spider_parser = subparsers.add_parser("module-spider", help="Search Lmod modules")
    spider_parser.add_argument("name", help="Module name or search term")
    spider_parser.set_defaults(handler=cmd_module_spider)

    if profile_has_hardware_context(profile):
        hardware_parser = subparsers.add_parser(
            "hardware",
            help="Show profile hardware and Slurm reference context",
        )
        hardware_parser.add_argument(
            "--source",
            action="store_true",
            help="Print configured source URLs only",
        )
        hardware_parser.add_argument(
            "--path",
            action="store_true",
            help="Print configured local reference paths only",
        )
        hardware_parser.set_defaults(handler=cmd_hardware)

    if profile is None or profile.queue_command:
        queue_parser = subparsers.add_parser("queue", help="Show remote Slurm queue occupancy")
        queue_parser.set_defaults(handler=cmd_queue)

    if profile is None or profile.sam_balance_command:
        balance_parser = subparsers.add_parser("balance", help="Show Slurm account credit balances")
        balance_parser.set_defaults(handler=cmd_balance)

    if profile is None or profile.sam_statement_command:
        statement_parser = subparsers.add_parser("statement", help="Show Slurm account credit transactions")
        statement_parser.add_argument("--account", required=True, help="Slurm account name")
        statement_parser.add_argument("--start", help="Start date in YYYY-mm-dd format")
        statement_parser.add_argument("--end", help="End date in YYYY-mm-dd format")
        statement_parser.set_defaults(handler=cmd_statement)

    if profile is None or profile.sam_quote_command:
        quote_parser = subparsers.add_parser("quote", help="Estimate Slurm credits for a job")
        quote_parser.add_argument(
            "quote_args",
            nargs=argparse.REMAINDER,
            help="sam-quote submit command and Slurm options, e.g. srun -M wice -p gpu_a100 -A account",
        )
        quote_parser.set_defaults(handler=cmd_quote)

    jobs_parser = subparsers.add_parser("jobs", help="Show current user's Slurm jobs")
    jobs_parser.add_argument(
        "--cluster",
        "-M",
        default="all",
        help="Slurm cluster name; defaults to all visible clusters",
    )
    jobs_parser.set_defaults(handler=cmd_jobs)

    job_parser = subparsers.add_parser("job", help="Show status for one Slurm job")
    job_parser.add_argument("jobid", help="Slurm job ID")
    job_parser.add_argument(
        "--cluster",
        "-M",
        default="all",
        help="Slurm cluster name; defaults to all visible clusters",
    )
    job_parser.set_defaults(handler=cmd_job)

    submit_parser = subparsers.add_parser("submit", help="Submit a Slurm job script")
    submit_parser.add_argument("jobscript", help="Job script path relative to --directory")
    submit_parser.add_argument(
        "--directory",
        "-C",
        default=".",
        help="Remote directory from which to run sbatch",
    )
    submit_parser.add_argument(
        "--test-only",
        action="store_true",
        help="Run sbatch --test-only instead of submitting",
    )
    submit_parser.add_argument(
        "--validate-first",
        action="store_true",
        help="Run sbatch --test-only with the same options before submitting",
    )
    _add_submit_override_arguments(submit_parser)
    submit_parser.set_defaults(handler=cmd_submit)

    sacct_parser = subparsers.add_parser("sacct", help="Show Slurm accounting for a job")
    sacct_parser.add_argument("jobid", help="Slurm job ID")
    sacct_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    sacct_parser.set_defaults(handler=cmd_sacct)

    limits_parser = subparsers.add_parser(
        "slurm-limits",
        help="Show Slurm partition, controller, QoS, and association limits",
    )
    limits_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    limits_parser.add_argument("--partition", "-p", help="Slurm partition name")
    limits_parser.add_argument("--qos", help="Limit QoS output to one QoS name")
    limits_parser.set_defaults(handler=cmd_slurm_limits)

    submissions_parser = subparsers.add_parser(
        "submissions",
        help="Inspect and update the local Slurm submission event log",
    )
    submissions_parser.add_argument(
        "--log",
        type=Path,
        help="Submission JSONL log path; defaults to the hpc-tools config directory",
    )
    submissions_subparsers = submissions_parser.add_subparsers(
        dest="submissions_command",
        metavar="<subcommand>",
        required=True,
    )

    submissions_list_parser = submissions_subparsers.add_parser(
        "list",
        help="List active submissions by replaying the event log",
    )
    submissions_list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include closed submissions",
    )
    submissions_list_parser.set_defaults(handler=cmd_submissions_list)

    submissions_observe_parser = submissions_subparsers.add_parser(
        "observe",
        help="Query Slurm accounting for active submissions and append observed events",
    )
    submissions_observe_parser.add_argument(
        "run_id",
        nargs="?",
        help="Run ID to observe; defaults to all active runs",
    )
    submissions_observe_parser.set_defaults(handler=cmd_submissions_observe)

    submissions_collect_parser = submissions_subparsers.add_parser(
        "mark-collected",
        help="Append a results_collected event for a run",
    )
    submissions_collect_parser.add_argument("run_id", help="Run ID")
    submissions_collect_parser.add_argument(
        "--path",
        required=True,
        help="Local or remote result path",
    )
    submissions_collect_parser.set_defaults(handler=cmd_submissions_mark_collected)

    submissions_analyse_parser = submissions_subparsers.add_parser(
        "mark-analysed",
        help="Append an analysed event for a run",
    )
    submissions_analyse_parser.add_argument("run_id", help="Run ID")
    submissions_analyse_parser.add_argument("--path", required=True, help="Report or notebook path")
    submissions_analyse_parser.set_defaults(handler=cmd_submissions_mark_analysed)

    submissions_close_parser = submissions_subparsers.add_parser(
        "close",
        help="Append a closed event for a run",
    )
    submissions_close_parser.add_argument("run_id", help="Run ID")
    submissions_close_parser.add_argument("--reason", help="Reason for closing this run")
    submissions_close_parser.set_defaults(handler=cmd_submissions_close)

    plugin_system.register_plugin_commands(subparsers, profile)

    return parser


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
    command = f"ls -ld {profile.projects_dir} 2>/dev/null && ls -1 {profile.projects_dir}"
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
    command = f"module spider {shlex.quote(args.name)} 2>&1"
    return run_remote(profile, command, dry_run=args.dry_run)


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
