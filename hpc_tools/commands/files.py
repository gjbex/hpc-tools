from __future__ import annotations

import argparse
import base64
from typing import Any

from hpc_tools.authorization import namespace_arguments, require_authorized
from hpc_tools.config import ConfigError, Profile
from hpc_tools.filesystem import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_TRANSFER_BYTES,
    FilesystemLimits,
    FilesystemService,
)
from hpc_tools.remote_filesystem import (
    copy_remote_file,
    list_remote_directory,
    make_remote_directory,
    read_local_regular_file,
    read_remote_file,
    remove_remote_path,
    resolve_granted_path,
    write_local_regular_file,
    write_remote_file,
)


def register(subparsers: Any, handlers: Any) -> None:
    parser = subparsers.add_parser(
        "files",
        help="Read and modify bounded remote files",
    )
    children = parser.add_subparsers(
        dest="files_command",
        metavar="<subcommand>",
        required=True,
    )

    list_parser = children.add_parser("list", help="List one remote directory")
    list_parser.add_argument("path")
    list_parser.add_argument(
        "--max-entries", type=_positive_integer, default=DEFAULT_MAX_ENTRIES
    )
    list_parser.set_defaults(handler=handlers.cmd_files_list, operation_id="filesystem.list")

    read_parser = children.add_parser("read", help="Read one remote regular file")
    read_parser.add_argument("path")
    read_parser.add_argument("--encoding", choices=("utf-8", "base64"), default="utf-8")
    read_parser.add_argument("--max-bytes", type=_positive_integer, default=DEFAULT_MAX_BYTES)
    read_parser.set_defaults(handler=handlers.cmd_files_read, operation_id="filesystem.read")

    download = children.add_parser("download", help="Download one remote regular file")
    download.add_argument("source")
    download.add_argument("output")
    _add_transfer_options(download)
    download.set_defaults(handler=handlers.cmd_files_download, operation_id="filesystem.download")

    upload = children.add_parser("upload", help="Upload one local regular file")
    upload.add_argument("source")
    upload.add_argument("destination")
    _add_transfer_options(upload)
    upload.set_defaults(handler=handlers.cmd_files_upload, operation_id="filesystem.upload")

    copy = children.add_parser("copy", help="Copy one remote regular file")
    copy.add_argument("source")
    copy.add_argument("destination")
    _add_transfer_options(copy)
    copy.set_defaults(handler=handlers.cmd_files_copy, operation_id="filesystem.copy")

    mkdir = children.add_parser("mkdir", help="Create one remote directory")
    mkdir.add_argument("path")
    mkdir.set_defaults(handler=handlers.cmd_files_mkdir, operation_id="filesystem.mkdir")

    remove = children.add_parser(
        "remove",
        help="Remove one remote regular file or empty directory",
    )
    remove.add_argument("path")
    remove.set_defaults(handler=handlers.cmd_files_remove, operation_id="filesystem.remove")


def _add_transfer_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force", action="store_true", help="Replace an existing regular file")
    parser.add_argument(
        "--max-bytes", type=_positive_integer, default=DEFAULT_MAX_TRANSFER_BYTES
    )


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _bounded_limit(requested: int, maximum: int, name: str) -> int:
    if requested > maximum:
        raise ConfigError(f"{name} must not exceed the fixed limit {maximum}")
    return requested


def _service(
    profile: Profile,
    *,
    max_bytes: int,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> FilesystemService:
    return FilesystemService(
        profile,
        limits=FilesystemLimits(
            max_bytes=max_bytes,
            max_entries=max_entries,
            max_transfer_bytes=max_bytes,
        ),
    )


def cmd_files_list(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.list", profile, namespace_arguments(args))
    maximum = _bounded_limit(args.max_entries, DEFAULT_MAX_ENTRIES, "max_entries")
    selected, _ = resolve_granted_path(args.path, profile.capabilities.remote_roots.list)
    if args.dry_run:
        print(f"filesystem list {selected} (max_entries={maximum})")
        return 0
    selected, entries, truncated = list_remote_directory(
        profile,
        args.path,
        roots=profile.capabilities.remote_roots.list,
        service=_service(profile, max_bytes=DEFAULT_MAX_BYTES, max_entries=maximum),
    )
    print(f"path: {selected}")
    for entry in entries:
        size = "-" if entry.size is None else str(entry.size)
        print(f"{entry.kind}\t{size}\t{entry.name}")
    if truncated:
        print("[listing truncated]")
    return 0


def cmd_files_read(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.read", profile, namespace_arguments(args))
    maximum = _bounded_limit(args.max_bytes, DEFAULT_MAX_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(args.path, profile.capabilities.remote_roots.read)
    if args.dry_run:
        print(f"filesystem read {selected} (max_bytes={maximum})")
        return 0
    remote = read_remote_file(
        profile,
        args.path,
        roots=profile.capabilities.remote_roots.read,
        service=_service(profile, max_bytes=maximum),
    )
    if remote.truncated:
        raise ConfigError(f"remote file exceeds the read limit of {maximum} bytes")
    if args.encoding == "base64":
        print(base64.b64encode(remote.data).decode("ascii"))
    else:
        try:
            print(remote.data.decode("utf-8"), end="")
        except UnicodeDecodeError as error:
            raise ConfigError("remote file is not valid UTF-8; use --encoding base64") from error
    return 0


def cmd_files_download(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.download", profile, namespace_arguments(args))
    maximum = _bounded_limit(args.max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(args.source, profile.capabilities.remote_roots.read)
    if args.dry_run:
        print(
            f"filesystem download {selected} -> {args.output} "
            f"(max_bytes={maximum}, force={args.force})"
        )
        return 0
    service = _service(profile, max_bytes=maximum)
    remote = read_remote_file(
        profile,
        args.source,
        roots=profile.capabilities.remote_roots.read,
        service=service,
    )
    if remote.truncated:
        raise ConfigError(f"remote file exceeds the transfer limit of {maximum} bytes")
    destination, overwritten = write_local_regular_file(
        args.output,
        remote.data,
        overwrite=args.force,
        max_bytes=maximum,
    )
    print(f"downloaded {remote.size} bytes: {remote.path} -> {destination}")
    if overwritten:
        print("replaced existing regular file")
    return 0


def cmd_files_upload(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.upload", profile, namespace_arguments(args))
    maximum = _bounded_limit(args.max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(args.destination, profile.capabilities.remote_roots.write)
    if args.dry_run:
        print(
            f"filesystem upload {args.source} -> {selected} "
            f"(max_bytes={maximum}, force={args.force})"
        )
        return 0
    source, data = read_local_regular_file(args.source, max_bytes=maximum)
    result = write_remote_file(
        profile,
        args.destination,
        data,
        roots=profile.capabilities.remote_roots.write,
        overwrite=args.force,
        service=_service(profile, max_bytes=maximum),
    )
    print(f"uploaded {result.size} bytes: {source} -> {result.destination}")
    return 0


def cmd_files_copy(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.copy", profile, namespace_arguments(args))
    maximum = _bounded_limit(args.max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    source, _ = resolve_granted_path(args.source, profile.capabilities.remote_roots.read)
    destination, _ = resolve_granted_path(
        args.destination,
        profile.capabilities.remote_roots.write,
    )
    if args.dry_run:
        print(
            f"filesystem copy {source} -> {destination} "
            f"(max_bytes={maximum}, force={args.force})"
        )
        return 0
    result = copy_remote_file(
        profile,
        args.source,
        args.destination,
        read_roots=profile.capabilities.remote_roots.read,
        write_roots=profile.capabilities.remote_roots.write,
        overwrite=args.force,
        service=_service(profile, max_bytes=maximum),
    )
    print(f"copied {result.size} bytes: {result.source} -> {result.destination}")
    return 0


def cmd_files_mkdir(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.mkdir", profile, namespace_arguments(args))
    selected, _ = resolve_granted_path(args.path, profile.capabilities.remote_roots.write)
    if args.dry_run:
        print(f"filesystem mkdir {selected}")
        return 0
    print(make_remote_directory(profile, args.path, roots=profile.capabilities.remote_roots.write))
    return 0


def cmd_files_remove(args: argparse.Namespace, profile: Profile) -> int:
    require_authorized("filesystem.remove", profile, namespace_arguments(args))
    selected, _ = resolve_granted_path(args.path, profile.capabilities.remote_roots.delete)
    if args.dry_run:
        print(f"filesystem remove {selected}")
        return 0
    removed, kind = remove_remote_path(
        profile,
        args.path,
        roots=profile.capabilities.remote_roots.delete,
    )
    print(f"removed {kind}: {removed}")
    return 0
