from __future__ import annotations

import argparse
from datetime import datetime
from importlib import resources
from pathlib import Path
import shlex
import sys

from hpc_tools.config import ConfigError, Profile, default_config_dir, default_config_path, load_config, resolve_profile
from hpc_tools.hardware import profile_has_hardware_context, render_hardware_context
from hpc_tools.ssh import run_remote
from hpc_tools import slurm


LOCAL_COMMANDS = {"paths", "write-hardware-probe"}


def build_parser(profile: Profile | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpc")
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

    paths_parser = subparsers.add_parser(
        "paths",
        help="Show hpc-tools config, reference, skill, and package paths",
    )
    paths_parser.set_defaults(handler=cmd_paths)

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

    clone_parser = subparsers.add_parser("clone", help="Clone a Git repository into projects_dir")
    clone_parser.add_argument("url", help="Git repository URL")
    clone_parser.add_argument("--branch", "-b", help="Branch to clone")
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
    jobs_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    jobs_parser.set_defaults(handler=cmd_jobs)

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
    submit_parser.set_defaults(handler=cmd_submit)

    sacct_parser = subparsers.add_parser("sacct", help="Show Slurm accounting for a job")
    sacct_parser.add_argument("jobid", help="Slurm job ID")
    sacct_parser.add_argument("--cluster", "-M", help="Slurm cluster name")
    sacct_parser.set_defaults(handler=cmd_sacct)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    try:
        pre_args, _ = _build_pre_parser().parse_known_args(argv)
        if _should_parse_without_config(argv):
            parser = build_parser()
            args = parser.parse_args(argv)
            return args.handler(args, None)
        config = load_config(pre_args.config)
        profile = resolve_profile(config, pre_args.profile)
        parser = build_parser(profile)
        args = parser.parse_args(argv)
        return args.handler(args, profile)
    except ConfigError as error:
        parser = build_parser()
        parser.exit(2, f"hpc: configuration error: {error}\n")


def _build_pre_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile")
    parser.add_argument("--config")
    return parser


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
    if remaining[0] == "write-hardware-probe":
        return not (pre_args.profile or pre_args.config or "--mail-notifications" in remaining)
    return remaining[0] in LOCAL_COMMANDS


def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, args.remote_command, dry_run=args.dry_run)


def cmd_paths(args: argparse.Namespace, profile: Profile | None) -> int:
    del args, profile
    package_probe = resources.files("hpc_tools.data").joinpath("hardware-probe.slurm")
    config_dir = default_config_dir()
    print(f"config: {default_config_path()}")
    print(f"profile_references: {config_dir / 'profiles' / '<profile>'}")
    print("codex_skills: ~/.codex/skills/")
    print(f"hardware_probe_template: {package_probe}")
    print()
    print("package_uninstall: pipx uninstall hpc-tools")
    print("optional_user_state:")
    print(f"  {config_dir}")
    print("optional_copied_skills:")
    print("  ~/.codex/skills/_shared")
    print("  ~/.codex/skills/hpc-cluster-onboarding")
    print("  ~/.codex/skills/hpc-cluster-discovery")
    print("  ~/.codex/skills/hpc-filesystem-environment")
    print("  ~/.codex/skills/hpc-deploy-build")
    print("  ~/.codex/skills/hpc-slurm-jobs")
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
    if not profile.projects_dir:
        raise ConfigError(f"profile '{profile.name}' does not define projects_dir")
    parts = ["git", "clone"]
    if args.branch:
        parts.extend(["--branch", args.branch])
    parts.append(args.url)
    if args.name:
        parts.append(args.name)
    command = f"cd {profile.projects_dir} && {' '.join(shlex.quote(part) for part in parts)}"
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
    template = _hardware_probe_template(args, profile)
    if args.output == "-":
        sys.stdout.write(template)
        return 0

    output_path = Path(args.output).expanduser()
    if output_path.exists() and not args.force:
        raise ConfigError(f"output file already exists: {output_path}; use --force to overwrite")
    output_path.write_text(template, encoding="utf-8")
    return 0


def cmd_install_hardware_probe(args: argparse.Namespace, profile: Profile) -> int:
    command = _install_hardware_probe_command(
        args.directory,
        args.name,
        _hardware_probe_template(args, profile),
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
    cluster = args.cluster or profile.default_cluster
    return run_remote(profile, slurm.squeue_user_command(cluster), dry_run=args.dry_run)


def cmd_submit(args: argparse.Namespace, profile: Profile) -> int:
    command = slurm.submit_command(
        args.jobscript,
        directory=args.directory,
        test_only=args.test_only,
    )
    return run_remote(profile, command, dry_run=args.dry_run)


def cmd_sacct(args: argparse.Namespace, profile: Profile) -> int:
    cluster = args.cluster or profile.default_cluster
    return run_remote(profile, slurm.sacct_command(args.jobid, cluster), dry_run=args.dry_run)


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
