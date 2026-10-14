from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import posixpath
import stat
import tempfile
from typing import Mapping

from hpc_tools.config import ConfigError, Profile
from hpc_tools.filesystem import (
    DEFAULT_MAX_TRANSFER_BYTES,
    FilesystemEntry,
    FilesystemFailureCode,
    FilesystemLimits,
    FilesystemResult,
    FilesystemService,
)


@dataclass(frozen=True)
class InstalledAsset:
    path: str
    size: int
    overwritten: bool


@dataclass(frozen=True)
class PlannedAsset:
    relative_path: str
    path: str
    data: bytes
    mode: int


@dataclass(frozen=True)
class RemoteFile:
    path: str
    data: bytes
    size: int
    truncated: bool


@dataclass(frozen=True)
class FileTransfer:
    source: str
    destination: str
    size: int
    overwritten: bool


def resolve_granted_path(path: str, roots: tuple[str, ...]) -> tuple[str, str]:
    """Bind a declared path to one configured root without shell expansion."""
    if not roots:
        raise ConfigError("operation has no configured remote root grants")
    if path == ".":
        if len(roots) != 1:
            raise ConfigError("relative path '.' requires exactly one remote root grant")
        return roots[0], roots[0]
    if not path or path != path.strip() or path.endswith("/"):
        raise ConfigError("remote path is empty, padded, or ends with '/'")
    if any(character in path for character in "\0\n\r*?[]`"):
        raise ConfigError("remote path contains unsupported expansion syntax")
    path_segments = path[1:].split("/") if path.startswith("/") else path.split("/")
    if any(part in {"", ".", ".."} for part in path_segments):
        raise ConfigError("remote path contains an empty, . or .. segment")

    matches = tuple(
        root for root in roots if path == root or path.startswith(f"{root}/")
    )
    if matches:
        root = max(matches, key=len)
        return path, root
    if path.startswith(("/", "~", "$")):
        raise ConfigError("remote path is outside the configured root grants")
    if len(roots) != 1:
        raise ConfigError("relative remote path requires exactly one root grant")
    return f"{roots[0]}/{path}", roots[0]


def list_remote_directory(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> tuple[str, tuple[FilesystemEntry, ...], bool]:
    selected_path, root = resolve_granted_path(path, roots)
    result = (service or FilesystemService(profile)).list_directory(
        selected_path,
        roots=roots,
        root=root,
    )
    _require_result(result, operation="list remote directory")
    return selected_path, result.entries, result.truncated


def read_remote_bytes(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> tuple[str, bytes]:
    """Read one regular remote file through the bounded filesystem service."""
    selected_path, root = resolve_granted_path(path, roots)
    result = (service or FilesystemService(profile)).read_bytes(
        selected_path,
        roots=roots,
        root=root,
    )
    _require_result(result, operation="read remote file")
    if result.data is None:
        raise ConfigError("could not read remote file: helper returned no data")
    return selected_path, result.data


def read_remote_file(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> RemoteFile:
    """Read one regular file while preserving size/truncation metadata."""
    selected_path, root = resolve_granted_path(path, roots)
    result = (service or FilesystemService(profile)).read_bytes(
        selected_path,
        roots=roots,
        root=root,
    )
    _require_result(result, operation="read remote file")
    if result.data is None or result.size is None:
        raise ConfigError("could not read remote file: helper returned incomplete data")
    return RemoteFile(
        path=selected_path,
        data=result.data,
        size=result.size,
        truncated=result.truncated,
    )


def write_remote_file(
    profile: Profile,
    path: str,
    data: bytes,
    *,
    roots: tuple[str, ...],
    overwrite: bool = False,
    mode: int = 0o600,
    service: FilesystemService | None = None,
) -> FileTransfer:
    selected_path, root = resolve_granted_path(path, roots)
    result = (service or FilesystemService(profile)).write_bytes(
        selected_path,
        data,
        roots=roots,
        root=root,
        overwrite=overwrite,
        mode=mode,
    )
    _require_result(result, operation="write remote file")
    return FileTransfer(
        source="local",
        destination=selected_path,
        size=result.size if result.size is not None else len(data),
        overwritten=result.overwritten,
    )


def make_remote_directory(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> str:
    selected_path, root = resolve_granted_path(path, roots)
    result = (service or FilesystemService(profile)).make_directory(
        selected_path,
        roots=roots,
        root=root,
    )
    _require_result(result, operation="create remote directory")
    return selected_path


def remove_remote_path(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> tuple[str, str]:
    selected_path, root = resolve_granted_path(path, roots)
    if selected_path == root:
        raise ConfigError("refusing to remove a configured remote root")
    result = (service or FilesystemService(profile)).remove(
        selected_path,
        roots=roots,
        root=root,
    )
    _require_result(result, operation="remove remote path")
    return selected_path, result.removed_kind or "unknown"


def copy_remote_file(
    profile: Profile,
    source: str,
    destination: str,
    *,
    read_roots: tuple[str, ...],
    write_roots: tuple[str, ...],
    overwrite: bool = False,
    service: FilesystemService | None = None,
) -> FileTransfer:
    fs = service or FilesystemService(
        profile,
        limits=FilesystemLimits(
            max_bytes=DEFAULT_MAX_TRANSFER_BYTES,
            max_transfer_bytes=DEFAULT_MAX_TRANSFER_BYTES,
        ),
    )
    remote = read_remote_file(profile, source, roots=read_roots, service=fs)
    if remote.truncated:
        raise ConfigError(
            f"remote file exceeds the transfer limit of {fs.limits.max_bytes} bytes"
        )
    written = write_remote_file(
        profile,
        destination,
        remote.data,
        roots=write_roots,
        overwrite=overwrite,
        service=fs,
    )
    return FileTransfer(
        source=remote.path,
        destination=written.destination,
        size=written.size,
        overwritten=written.overwritten,
    )


def read_local_regular_file(
    path: str,
    *,
    max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
) -> tuple[Path, bytes]:
    selected = Path(path).expanduser()
    try:
        descriptor = os.open(selected, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError as error:
        raise ConfigError(f"local source file does not exist: {selected}") from error
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise ConfigError(f"local source must not be a symbolic link: {selected}") from error
        raise ConfigError(f"could not open local source file: {selected}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigError(f"local source is not a regular file: {selected}")
        if metadata.st_size > max_bytes:
            raise ConfigError(
                f"local source exceeds the transfer limit of {max_bytes} bytes"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise ConfigError(
                f"local source exceeds the transfer limit of {max_bytes} bytes"
            )
        return selected, data
    finally:
        os.close(descriptor)


def write_local_regular_file(
    path: str,
    data: bytes,
    *,
    overwrite: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
) -> tuple[Path, bool]:
    if len(data) > max_bytes:
        raise ConfigError(f"download exceeds the transfer limit of {max_bytes} bytes")
    selected = Path(path).expanduser()
    parent = selected.parent
    try:
        parent_metadata = parent.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"local destination parent does not exist: {parent}") from error
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ConfigError(f"local destination parent is not a safe directory: {parent}")

    existed = False
    try:
        target_metadata = selected.lstat()
    except FileNotFoundError:
        pass
    else:
        existed = True
        if stat.S_ISLNK(target_metadata.st_mode) or not stat.S_ISREG(target_metadata.st_mode):
            raise ConfigError(f"local destination is not a regular file: {selected}")
        if not overwrite:
            raise ConfigError(
                f"local destination already exists: {selected}; use force to overwrite"
            )

    descriptor, temporary_name = tempfile.mkstemp(prefix=".hpc-tools-", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        if overwrite:
            os.replace(temporary, selected)
        else:
            try:
                os.link(temporary, selected, follow_symlinks=False)
            except FileExistsError as error:
                raise ConfigError(
                    f"local destination already exists: {selected}; use force to overwrite"
                ) from error
            temporary.unlink()
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return selected, existed


def read_remote_text(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> tuple[str, str]:
    """Read one UTF-8 remote file through the bounded filesystem service."""
    selected_path, data = read_remote_bytes(
        profile,
        path,
        roots=roots,
        service=service,
    )
    try:
        return selected_path, data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"remote file is not valid UTF-8: {selected_path}") from error


def ensure_remote_directory(
    profile: Profile,
    path: str,
    *,
    roots: tuple[str, ...],
    service: FilesystemService | None = None,
) -> str:
    selected_path, root = resolve_granted_path(path, roots)
    fs = service or FilesystemService(profile)
    if selected_path == root:
        _require_result(
            fs.list_directory(selected_path, roots=roots, root=root),
            operation="inspect remote root",
        )
        return selected_path

    suffix = selected_path[len(root) + 1 :]
    current = root
    for component in suffix.split("/"):
        parent_entries = fs.list_directory(current, roots=roots, root=root)
        _require_result(parent_entries, operation="inspect remote parent")
        existing = next(
            (entry for entry in parent_entries.entries if entry.name == component),
            None,
        )
        current = f"{current}/{component}"
        if existing is None:
            created = fs.make_directory(current, roots=roots, root=root)
            if not created.ok and (
                created.failure is None
                or created.failure.code is not FilesystemFailureCode.CONFLICT
            ):
                _require_result(created, operation="create remote directory")
            continue
        if existing.kind != "directory":
            raise ConfigError(f"remote path component is not a directory: {component}")
    return selected_path


def install_remote_assets(
    profile: Profile,
    directory: str,
    assets: Mapping[str, str | bytes],
    *,
    roots: tuple[str, ...],
    overwrite: bool = False,
    service: FilesystemService | None = None,
) -> tuple[InstalledAsset, ...]:
    fs = service or FilesystemService(profile)
    planned = plan_remote_assets(directory, assets, roots=roots)

    selected_directory = ensure_remote_directory(
        profile,
        directory,
        roots=roots,
        service=fs,
    )
    _, root = resolve_granted_path(selected_directory, roots)

    parent_paths = sorted(
        {
            posixpath.dirname(asset.relative_path)
            for asset in planned
            if posixpath.dirname(asset.relative_path)
        },
        key=lambda value: (value.count("/"), value),
    )
    for relative_parent in parent_paths:
        ensure_remote_directory(
            profile,
            f"{selected_directory}/{relative_parent}",
            roots=roots,
            service=fs,
        )

    if not overwrite:
        by_parent: dict[str, set[str]] = {}
        for asset in planned:
            parent = posixpath.dirname(asset.relative_path)
            by_parent.setdefault(parent, set()).add(posixpath.basename(asset.relative_path))
        for relative_parent, names in by_parent.items():
            parent_path = (
                f"{selected_directory}/{relative_parent}"
                if relative_parent
                else selected_directory
            )
            listing = fs.list_directory(parent_path, roots=roots, root=root)
            _require_result(listing, operation="inspect remote asset destination")
            conflicts = sorted(entry.name for entry in listing.entries if entry.name in names)
            if conflicts:
                raise ConfigError(
                    "remote asset destination already exists: " + ", ".join(conflicts)
                )

    installed: list[InstalledAsset] = []
    for asset in planned:
        result = fs.write_bytes(
            asset.path,
            asset.data,
            roots=roots,
            root=root,
            overwrite=overwrite,
            mode=asset.mode,
        )
        _require_result(result, operation="install remote asset")
        installed.append(InstalledAsset(
            path=asset.path,
            size=result.size or len(asset.data),
            overwritten=result.overwritten,
        ))
    return tuple(installed)


def plan_remote_assets(
    directory: str,
    assets: Mapping[str, str | bytes],
    *,
    roots: tuple[str, ...],
) -> tuple[PlannedAsset, ...]:
    """Validate an asset bundle and resolve destinations without remote effects."""
    if not assets:
        raise ConfigError("remote asset bundle must not be empty")
    selected_directory, _ = resolve_granted_path(directory, roots)
    planned: list[PlannedAsset] = []
    for relative_path, contents in assets.items():
        _validate_relative_asset(relative_path)
        if isinstance(contents, str):
            data = contents.encode("utf-8")
        elif isinstance(contents, bytes):
            data = contents
        else:
            raise ConfigError(
                f"remote asset contents must be text or bytes: {relative_path!r}"
            )
        planned.append(PlannedAsset(
            relative_path=relative_path,
            path=f"{selected_directory}/{relative_path}",
            data=data,
            mode=(
                0o700
                if relative_path.endswith((".slurm", "codex-agent", "hpc-mcp-relay"))
                else 0o600
            ),
        ))
    return tuple(planned)


def _validate_relative_asset(path: str) -> None:
    if (
        not path
        or path != path.strip()
        or path.startswith("/")
        or path.endswith("/")
        or len(path) > 4096
        or any(character in path for character in "\0\n\r*?[]`$~")
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ConfigError(f"invalid remote asset path: {path!r}")


def _require_result(result: FilesystemResult, *, operation: str) -> None:
    if result.ok:
        return
    failure = result.failure
    detail = failure.message if failure is not None else "unknown filesystem failure"
    raise ConfigError(f"could not {operation}: {detail}")
