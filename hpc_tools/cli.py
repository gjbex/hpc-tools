from __future__ import annotations

import argparse
import shlex
import sys

from hpc_tools.config import ConfigError, Profile, load_config, resolve_profile
from hpc_tools.ssh import run_remote
from hpc_tools import slurm


def build_parser() -> argparse.ArgumentParser:
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

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a command on the remote host")
    run_parser.add_argument("remote_command", help="Command to run through the configured login shell")
    run_parser.set_defaults(handler=cmd_run)

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

    queue_parser = subparsers.add_parser("queue", help="Show remote Slurm queue occupancy")
    queue_parser.set_defaults(handler=cmd_queue)

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
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        profile = resolve_profile(config, args.profile)
        return args.handler(args, profile)
    except ConfigError as error:
        parser.exit(2, f"hpc: configuration error: {error}\n")


def cmd_run(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(profile, args.remote_command, dry_run=args.dry_run)


def cmd_quota(args: argparse.Namespace, profile: Profile) -> int:
    command = profile.quota_command or "myquota"
    return run_remote(profile, command, dry_run=args.dry_run)


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


def cmd_queue(args: argparse.Namespace, profile: Profile) -> int:
    return run_remote(
        profile,
        slurm.queue_state_command(profile.queue_command),
        dry_run=args.dry_run,
    )


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


if __name__ == "__main__":
    sys.exit(main())
