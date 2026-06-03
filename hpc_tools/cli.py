from __future__ import annotations

import argparse
from datetime import datetime
import shlex
import sys

from hpc_tools.config import ConfigError, Profile, load_config, resolve_profile
from hpc_tools.hardware import profile_has_hardware_context, render_hardware_context
from hpc_tools.ssh import run_remote
from hpc_tools import slurm


def build_parser(profile: Profile | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpc")
    parser.add_argument("--profile", help="Profile name from the configuration file")
    parser.add_argument(
        "--config",
        help="Configuration file path; defaults to HPC_TOOLS_CONFIG or ~/.config/hpc-tools/config.toml",
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


def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, args.remote_command, dry_run=args.dry_run)


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


def _validate_date(value: str, name: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ConfigError(f"{name} date must use YYYY-mm-dd format: {value}") from error


if __name__ == "__main__":
    sys.exit(main())
