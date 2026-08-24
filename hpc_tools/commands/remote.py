from __future__ import annotations

import argparse
import shlex
from typing import Any

from hpc_tools.commands.common import _quote_remote_path_expression, _section_command
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import run_command
from hpc_tools.hardware import profile_has_hardware_context
from hpc_tools.hardware import render_hardware_context


def register(subparsers: Any, profile: Any, handlers: Any) -> None:
    register_storage(subparsers, handlers)
    register_repo(subparsers, handlers)
    register_quota(subparsers, profile, handlers)
    register_workspace(subparsers, handlers)
    register_module_spider(subparsers, handlers)
    register_hardware(subparsers, profile, handlers)


def register_storage(subparsers: Any, handlers: Any) -> None:
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
    storage_inspect_parser.set_defaults(handler=handlers.cmd_storage_inspect)


def register_repo(subparsers: Any, handlers: Any) -> None:
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
    repo_status_parser.set_defaults(handler=handlers.cmd_repo_status)


def register_quota(subparsers: Any, profile: Any, handlers: Any) -> None:
    if profile is None or profile.quota_command:
        quota_parser = subparsers.add_parser("quota", help="Show remote quota usage")
        quota_parser.set_defaults(handler=handlers.cmd_quota)


def register_workspace(subparsers: Any, handlers: Any) -> None:
    register_projects(subparsers, handlers)
    register_clone(subparsers, handlers)


def register_projects(subparsers: Any, handlers: Any) -> None:
    projects_parser = subparsers.add_parser("projects", help="List the remote project directory")
    projects_parser.set_defaults(handler=handlers.cmd_projects)


def register_clone(subparsers: Any, handlers: Any) -> None:
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
    clone_parser.set_defaults(handler=handlers.cmd_clone)


def register_module_spider(subparsers: Any, handlers: Any) -> None:
    spider_parser = subparsers.add_parser("module-spider", help="Search Lmod modules")
    spider_parser.add_argument("name", help="Module name or search term")
    spider_parser.set_defaults(handler=handlers.cmd_module_spider)


def register_hardware(subparsers: Any, profile: Any, handlers: Any) -> None:
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
        hardware_parser.set_defaults(handler=handlers.cmd_hardware)

def cmd_storage_inspect(args: argparse.Namespace, profile: Profile) -> int:
    return run_command(profile, _storage_inspect_command(args.path), dry_run=args.dry_run)

def cmd_repo_status(args: argparse.Namespace, profile: Profile) -> int:
    return run_command(profile, _repo_status_command(args.directory), dry_run=args.dry_run)

def cmd_quota(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.quota_command:
        raise ConfigError(f"profile '{profile.name}' does not define quota_command")
    return run_command(profile, profile.quota_command, dry_run=args.dry_run)

def cmd_projects(args: argparse.Namespace, profile: Profile) -> int:
    if not profile.projects_dir:
        raise ConfigError(f"profile '{profile.name}' does not define projects_dir")
    remote_path = _quote_remote_path_expression(profile.projects_dir)
    command = f"ls -ld {remote_path} 2>/dev/null && ls -1 {remote_path}"
    return run_command(profile, command, dry_run=args.dry_run)

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
    return run_command(profile, command, dry_run=args.dry_run)

def cmd_module_spider(args: argparse.Namespace, profile: Profile) -> int:
    return run_command(profile, _module_spider_command(args.name), dry_run=args.dry_run)

def cmd_hardware(args: argparse.Namespace, profile: Profile) -> int:
    if args.source and args.path:
        raise ConfigError("use only one of --source or --path")
    print(render_hardware_context(profile, source_only=args.source, path_only=args.path))
    return 0

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
