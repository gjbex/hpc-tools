from __future__ import annotations

from dataclasses import dataclass
import posixpath
from typing import Mapping

from hpc_tools.config import ConfigError, Profile
from hpc_tools.filesystem import (
    FilesystemEntry,
    FilesystemFailureCode,
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
