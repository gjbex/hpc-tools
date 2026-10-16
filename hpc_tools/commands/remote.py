from __future__ import annotations

import argparse
import posixpath
import shlex
from typing import Any

from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.commands.common import _quote_remote_path_expression
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import run_command
from hpc_tools.filesystem import FilesystemService
from hpc_tools.hardware import render_hardware_context
from hpc_tools.remote_filesystem import (
    ensure_remote_directory,
    list_remote_directory,
    resolve_granted_path,
)


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
        help="Remote directory to inspect; defaults to profile projects_dir",
    )
    storage_inspect_parser.set_defaults(
        handler=handlers.cmd_storage_inspect,
        operation_id="filesystem.inspect",
    )


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
    repo_status_parser.set_defaults(
        handler=handlers.cmd_repo_status,
        operation_id="repository.status",
    )


def register_quota(subparsers: Any, profile: Any, handlers: Any) -> None:
    del profile
    quota_parser = subparsers.add_parser("quota", help="Show remote quota usage")
    quota_parser.set_defaults(handler=handlers.cmd_quota, operation_id="cluster.quota")


def register_workspace(subparsers: Any, handlers: Any) -> None:
    register_projects(subparsers, handlers)
    register_clone(subparsers, handlers)


def register_projects(subparsers: Any, handlers: Any) -> None:
    projects_parser = subparsers.add_parser("projects", help="List the remote project directory")
    projects_parser.set_defaults(
        handler=handlers.cmd_projects,
        operation_id="filesystem.projects",
    )


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
    clone_parser.set_defaults(handler=handlers.cmd_clone, operation_id="repository.clone")


def register_module_spider(subparsers: Any, handlers: Any) -> None:
    spider_parser = subparsers.add_parser("module-spider", help="Search Lmod modules")
    spider_parser.add_argument("name", help="Module name or search term")
    spider_parser.set_defaults(handler=handlers.cmd_module_spider, operation_id="cluster.modules")


def register_hardware(subparsers: Any, profile: Any, handlers: Any) -> None:
    del profile
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
    hardware_parser.set_defaults(
        handler=handlers.cmd_hardware,
        operation_id="references.context",
    )

def cmd_storage_inspect(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.inspect", profile, namespace_arguments(args))
    selected_path = profile.projects_dir if args.path in {None, "."} else args.path
    if not selected_path:
        raise ConfigError(
            f"profile '{profile.name}' does not define projects_dir; pass a path"
        )
    if args.dry_run:
        print(f"filesystem list {selected_path}")
        return 0
    selected, entries, truncated = list_remote_directory(
        profile,
        selected_path,
        roots=profile.capabilities.remote_roots.list,
    )
    print(f"path: {selected}")
    for entry in entries:
        size = "-" if entry.size is None else str(entry.size)
        print(f"{entry.kind}\t{size}\t{entry.name}")
    if truncated:
        print("[listing truncated]")
    return 0

def cmd_repo_status(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("repository.status", profile, namespace_arguments(args))
    if not args.dry_run:
        list_remote_directory(
            profile,
            args.directory,
            roots=profile.capabilities.remote_roots.list,
        )
        selected, root = resolve_granted_path(
            f"{args.directory}/.git/HEAD",
            profile.capabilities.remote_roots.read,
        )
        head = FilesystemService(profile).read_text(
            selected,
            roots=profile.capabilities.remote_roots.read,
            root=root,
        )
        if not head.ok:
            detail = head.failure.message if head.failure else "unknown filesystem failure"
            raise ConfigError(f"could not inspect repository metadata: {detail}")
    return run_command(profile, _repo_status_command(args.directory), dry_run=args.dry_run)

def cmd_quota(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("cluster.quota", profile, namespace_arguments(args))
    if not profile.quota_command:
        raise ConfigError(f"profile '{profile.name}' does not define quota_command")
    return run_command(profile, profile.quota_command, dry_run=args.dry_run)

def cmd_projects(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.projects", profile, namespace_arguments(args))
    if not profile.projects_dir:
        raise ConfigError(f"profile '{profile.name}' does not define projects_dir")
    if args.dry_run:
        print(f"filesystem list {profile.projects_dir}")
        return 0
    selected, entries, truncated = list_remote_directory(
        profile,
        profile.projects_dir,
        roots=profile.capabilities.remote_roots.list,
    )
    print(f"path: {selected}")
    for entry in entries:
        print(entry.name)
    if truncated:
        print("[listing truncated]")
    return 0

def cmd_clone(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("repository.clone", profile, namespace_arguments(args))
    selected_directory, name, command = clone_plan(
        profile,
        args.url,
        directory=args.directory,
        name=args.name,
        branch=args.branch,
    )
    if not args.dry_run:
        prepare_clone_destination(profile, selected_directory, name)
    return run_command(profile, command, dry_run=args.dry_run)


def clone_plan(
    profile: Profile,
    url: str,
    *,
    directory: str | None = None,
    name: str | None = None,
    branch: str | None = None,
) -> tuple[str, str, str]:
    selected_parent = directory or profile.projects_dir
    if not selected_parent:
        raise ConfigError(
            f"profile '{profile.name}' does not define projects_dir; pass directory"
        )
    _validate_clone_source(url)
    destination_name = name or _clone_destination_name(url)
    if "/" in destination_name or destination_name in {"", ".", ".."}:
        raise ConfigError("clone destination name must be one path component")
    selected_directory, _ = resolve_granted_path(
        selected_parent,
        profile.capabilities.remote_roots.write,
    )
    parts = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "clone",
        "--no-recurse-submodules",
    ]
    if branch:
        parts.extend(["--branch", branch])
    parts.extend(["--", url, destination_name])
    command = (
        f"cd {_quote_remote_path_expression(selected_directory)} && "
        f"{' '.join(shlex.quote(part) for part in parts)}"
    )
    return selected_directory, destination_name, command


def prepare_clone_destination(profile: Profile, directory: str, name: str) -> None:
    ensure_remote_directory(
        profile,
        directory,
        roots=profile.capabilities.remote_roots.write,
    )
    _, entries, truncated = list_remote_directory(
        profile,
        directory,
        roots=profile.capabilities.remote_roots.write,
    )
    if truncated:
        raise ConfigError(
            "clone destination cannot be proven absent because the parent listing was truncated"
        )
    if any(entry.name == name for entry in entries):
        raise ConfigError(f"clone destination already exists: {name}")

def cmd_module_spider(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("cluster.modules", profile, namespace_arguments(args))
    return run_command(profile, _module_spider_command(args.name), dry_run=args.dry_run)

def cmd_hardware(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("references.context", profile, namespace_arguments(args))
    if args.source and args.path:
        raise ConfigError("use only one of --source or --path")
    print(render_hardware_context(profile, source_only=args.source, path_only=args.path))
    return 0

def _module_spider_command(name: str) -> str:
    return f"module spider {shlex.quote(name)} 2>&1"

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


def _clone_destination_name(url: str) -> str:
    candidate = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    candidate = posixpath.basename(candidate)
    if not candidate or candidate in {".", ".."}:
        raise ConfigError("could not derive a safe clone destination; pass --name")
    return candidate


def _validate_clone_source(url: str) -> None:
    lowered = url.lower()
    if (
        not url
        or url != url.strip()
        or url.startswith(("/", "./", "../", "~", "$"))
        or lowered.startswith("file:")
        or "\0" in url
        or "\n" in url
        or "\r" in url
    ):
        raise ConfigError(
            "clone source must be a remote network URL; local and file sources are not supported"
        )
