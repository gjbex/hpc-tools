from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
import tarfile
import tempfile
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    tomllib = None  # type: ignore[assignment]

from hpc_tools.config import ConfigError, Profile, default_reference_sets_dir, _load_basic_toml


MANIFEST_NAME = "manifest.toml"
FORMAT_VERSION = 1
REFERENCE_FILE_KEYS = {
    "hardware_reference": "hardware.md",
    "slurm_reference": "slurm.md",
    "storage_reference": "storage.md",
}
OPTIONAL_FILE_KEYS = {
    "probe_hardware_report": "probe-hardware-report.md",
}
REFERENCE_URL_KEYS = (
    "hardware_url",
    "slurm_url",
    "storage_url",
    "status_url",
)


@dataclass(frozen=True)
class ReferenceContext:
    reference_set: str | None
    hardware_reference: str | None
    hardware_url: str | None
    slurm_reference: str | None
    slurm_url: str | None
    storage_reference: str | None
    storage_url: str | None
    status_url: str | None
    probe_hardware_report: str | None


@dataclass(frozen=True)
class ReferenceSet:
    name: str
    path: Path
    format_version: int
    created_at: str | None
    source_profile: str | None
    hardware_reference: Path
    hardware_url: str | None
    slurm_reference: Path
    slurm_url: str | None
    storage_reference: Path
    storage_url: str | None
    status_url: str | None
    probe_hardware_report: Path | None


def resolve_reference_context(profile: Profile) -> ReferenceContext:
    reference_set = load_reference_set(profile.reference_set) if profile.reference_set else None
    return ReferenceContext(
        reference_set=reference_set.name if reference_set else None,
        hardware_reference=_prefer_path(reference_set.hardware_reference if reference_set else None, profile.hardware_reference),
        hardware_url=_prefer_value(reference_set.hardware_url if reference_set else None, profile.hardware_url),
        slurm_reference=_prefer_path(reference_set.slurm_reference if reference_set else None, profile.slurm_reference),
        slurm_url=_prefer_value(reference_set.slurm_url if reference_set else None, profile.slurm_url),
        storage_reference=_prefer_path(reference_set.storage_reference if reference_set else None, profile.storage_reference),
        storage_url=_prefer_value(reference_set.storage_url if reference_set else None, profile.storage_url),
        status_url=_prefer_value(reference_set.status_url if reference_set else None, profile.status_url),
        probe_hardware_report=_prefer_path(
            reference_set.probe_hardware_report if reference_set else None,
            _profile_probe_hardware_report(profile),
        ),
    )


def load_reference_set(name: str | None, *, base_dir: Path | None = None) -> ReferenceSet:
    if not name:
        raise ConfigError("reference set name is required")

    root = (base_dir or default_reference_sets_dir()).expanduser()
    path = root / name
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.exists():
        raise ConfigError(f"reference set manifest not found: {manifest_path}")

    manifest = _load_toml(manifest_path)
    format_version = _parse_format_version(manifest.get("format_version"))
    if format_version != FORMAT_VERSION:
        raise ConfigError(
            f"reference set '{name}' uses unsupported format_version {format_version!r}"
        )

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ConfigError(f"reference set '{name}' manifest is missing a [files] table")
    sources = manifest.get("sources", {})
    if sources is None:
        sources = {}
    if not isinstance(sources, dict):
        raise ConfigError(f"reference set '{name}' manifest [sources] must be a table")

    resolved_files = {
        key: _manifest_file_path(path, files, key, filename)
        for key, filename in REFERENCE_FILE_KEYS.items()
    }
    optional_probe = _manifest_optional_file_path(path, files, "probe_hardware_report")
    source_profile = _optional_string(manifest, "source_profile")
    created_at = _optional_string(manifest, "created_at")

    return ReferenceSet(
        name=name,
        path=path,
        format_version=format_version,
        created_at=created_at,
        source_profile=source_profile,
        hardware_reference=resolved_files["hardware_reference"],
        hardware_url=_optional_string(sources, "hardware_url"),
        slurm_reference=resolved_files["slurm_reference"],
        slurm_url=_optional_string(sources, "slurm_url"),
        storage_reference=resolved_files["storage_reference"],
        storage_url=_optional_string(sources, "storage_url"),
        status_url=_optional_string(sources, "status_url"),
        probe_hardware_report=optional_probe,
    )


def list_reference_sets(*, base_dir: Path | None = None) -> list[ReferenceSet]:
    root = (base_dir or default_reference_sets_dir()).expanduser()
    if not root.exists():
        return []
    reference_sets = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        reference_sets.append(load_reference_set(child.name, base_dir=root))
    return reference_sets


def create_reference_set(
    name: str,
    profile: Profile,
    *,
    force: bool = False,
    base_dir: Path | None = None,
) -> ReferenceSet:
    context = resolve_reference_context(profile)
    required_paths = {
        key: getattr(context, key)
        for key in REFERENCE_FILE_KEYS
    }
    missing = [key for key, path in required_paths.items() if not path]
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ConfigError(
            f"profile '{profile.name}' does not provide the required reference files: {missing_fields}"
        )

    destination_root = (base_dir or default_reference_sets_dir()).expanduser()
    destination = destination_root / name
    if destination.exists():
        if not force:
            raise ConfigError(f"reference set already exists: {destination}; use --force to overwrite")
        shutil.rmtree(destination)

    destination.mkdir(parents=True, exist_ok=True)
    for key, filename in REFERENCE_FILE_KEYS.items():
        source_path = Path(required_paths[key]).expanduser()
        if not source_path.exists():
            raise ConfigError(f"reference source file not found: {source_path}")
        shutil.copyfile(source_path, destination / filename)

    if context.probe_hardware_report:
        probe_path = Path(context.probe_hardware_report).expanduser()
        if probe_path.exists():
            shutil.copyfile(probe_path, destination / OPTIONAL_FILE_KEYS["probe_hardware_report"])

    _write_manifest(
        destination / MANIFEST_NAME,
        name=name,
        source_profile=profile.name,
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        sources={
            "hardware_url": context.hardware_url,
            "slurm_url": context.slurm_url,
            "storage_url": context.storage_url,
            "status_url": context.status_url,
        },
        include_probe=(destination / OPTIONAL_FILE_KEYS["probe_hardware_report"]).exists(),
    )
    return load_reference_set(name, base_dir=destination_root)


def export_reference_set(
    name: str,
    *,
    output: Path | None = None,
    force: bool = False,
    base_dir: Path | None = None,
) -> Path:
    reference_set = load_reference_set(name, base_dir=base_dir)
    archive_path = (output or Path.cwd() / f"{name}-reference-set.tar.gz").expanduser()
    if archive_path.exists() and not force:
        raise ConfigError(f"archive already exists: {archive_path}; use --force to overwrite")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(reference_set.path, arcname=reference_set.name)
    return archive_path


def import_reference_set(
    archive_path: Path,
    *,
    force: bool = False,
    base_dir: Path | None = None,
) -> ReferenceSet:
    source_archive = archive_path.expanduser()
    if not source_archive.exists():
        raise ConfigError(f"archive not found: {source_archive}")

    destination_root = (base_dir or default_reference_sets_dir()).expanduser()
    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        with tarfile.open(source_archive, "r:gz") as archive:
            _safe_extract_reference_archive(archive, staging)

        extracted_roots = [path for path in staging.iterdir() if path.is_dir()]
        if len(extracted_roots) != 1:
            raise ConfigError("reference set archive must contain exactly one top-level directory")

        extracted_root = extracted_roots[0]
        reference_set = load_reference_set(extracted_root.name, base_dir=staging)
        destination = destination_root / reference_set.name
        if destination.exists():
            if not force:
                raise ConfigError(
                    f"reference set already exists: {destination}; use --force to overwrite"
                )
            shutil.rmtree(destination)
        destination_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(extracted_root, destination)

    return load_reference_set(reference_set.name, base_dir=destination_root)


def validate_reference_set(name: str, *, base_dir: Path | None = None) -> ReferenceSet:
    return load_reference_set(name, base_dir=base_dir)


def format_reference_set_list(reference_sets: list[ReferenceSet]) -> str:
    if not reference_sets:
        return "No reference sets."
    lines = ["NAME            CREATED_AT                 SOURCE_PROFILE  PATH"]
    lines.append("--------------  -------------------------  --------------  ----")
    for reference_set in reference_sets:
        lines.append(
            f"{reference_set.name:<14}  "
            f"{(reference_set.created_at or ''):<25}  "
            f"{(reference_set.source_profile or ''):<14}  "
            f"{reference_set.path}"
        )
    return "\n".join(lines)


def format_reference_set(reference_set: ReferenceSet) -> str:
    lines = [
        f"name: {reference_set.name}",
        f"path: {reference_set.path}",
        f"format_version: {reference_set.format_version}",
    ]
    if reference_set.created_at:
        lines.append(f"created_at: {reference_set.created_at}")
    if reference_set.source_profile:
        lines.append(f"source_profile: {reference_set.source_profile}")
    lines.extend(
        [
            f"hardware_reference: {reference_set.hardware_reference}",
            f"slurm_reference: {reference_set.slurm_reference}",
            f"storage_reference: {reference_set.storage_reference}",
        ]
    )
    if reference_set.probe_hardware_report:
        lines.append(f"probe_hardware_report: {reference_set.probe_hardware_report}")
    if reference_set.hardware_url:
        lines.append(f"hardware_url: {reference_set.hardware_url}")
    if reference_set.slurm_url:
        lines.append(f"slurm_url: {reference_set.slurm_url}")
    if reference_set.storage_url:
        lines.append(f"storage_url: {reference_set.storage_url}")
    if reference_set.status_url:
        lines.append(f"status_url: {reference_set.status_url}")
    return "\n".join(lines)


def set_profile_reference_set(config_path: Path, profile_name: str, reference_set: str | None) -> None:
    path = config_path.expanduser()
    contents = path.read_text(encoding="utf-8")
    lines = contents.splitlines()
    start, end = _profile_block_range(lines, profile_name, path)
    field_pattern = re.compile(r"^\s*reference_set\s*=")

    for index in range(start + 1, end):
        if field_pattern.match(lines[index]):
            if reference_set is None:
                del lines[index]
            else:
                lines[index] = f'reference_set = "{reference_set}"'
            path.write_text("\n".join(lines) + ("\n" if contents.endswith("\n") else ""), encoding="utf-8")
            return

    if reference_set is not None:
        lines.insert(start + 1, f'reference_set = "{reference_set}"')
        path.write_text("\n".join(lines) + ("\n" if contents.endswith("\n") else ""), encoding="utf-8")


def _profile_probe_hardware_report(profile: Profile) -> str | None:
    candidates = []
    for path in (
        profile.hardware_reference,
        profile.slurm_reference,
        profile.storage_reference,
    ):
        if path:
            candidates.append(Path(path).expanduser().parent / OPTIONAL_FILE_KEYS["probe_hardware_report"])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _prefer_value(primary: str | None, secondary: str | None) -> str | None:
    return primary if primary else secondary


def _prefer_path(primary: Path | None, secondary: str | None) -> str | None:
    if primary is not None:
        return str(primary)
    return secondary


def _manifest_file_path(root: Path, files: dict[str, Any], key: str, default_filename: str) -> Path:
    filename = files.get(key, default_filename)
    if not isinstance(filename, str):
        raise ConfigError(f"reference set manifest entry '{key}' must be a string")
    path = _safe_relative_path(root, filename)
    if not path.exists():
        raise ConfigError(f"reference set file not found: {path}")
    return path


def _manifest_optional_file_path(root: Path, files: dict[str, Any], key: str) -> Path | None:
    filename = files.get(key)
    if filename is None:
        return None
    if not isinstance(filename, str):
        raise ConfigError(f"reference set manifest entry '{key}' must be a string")
    path = _safe_relative_path(root, filename)
    if not path.exists():
        raise ConfigError(f"reference set file not found: {path}")
    return path


def _safe_relative_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    root_resolved = root.resolve()
    if os.path.commonpath([str(path), str(root_resolved)]) != str(root_resolved):
        raise ConfigError(f"reference set path escapes root: {relative}")
    return path


def _profile_block_range(lines: list[str], profile_name: str, path: Path) -> tuple[int, int]:
    header = f"[profiles.{profile_name}]"
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == header:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    if start is None:
        raise ConfigError(f"profile '{profile_name}' not found in {path}")
    return start, end


def _safe_extract_reference_archive(archive: tarfile.TarFile, destination: Path) -> None:
    for member in archive.getmembers():
        parts = Path(member.name).parts
        if not parts:
            continue
        if Path(member.name).is_absolute() or ".." in parts:
            raise ConfigError(f"unsafe archive member: {member.name}")
    archive.extractall(destination)


def _write_manifest(
    path: Path,
    *,
    name: str,
    source_profile: str | None,
    created_at: str,
    sources: dict[str, str | None],
    include_probe: bool,
) -> None:
    lines = [
        f'name = "{name}"',
        f'format_version = "{FORMAT_VERSION}"',
        f'created_at = "{created_at}"',
    ]
    if source_profile:
        lines.append(f'source_profile = "{source_profile}"')
    lines.append("")
    lines.append("[files]")
    for key, filename in REFERENCE_FILE_KEYS.items():
        lines.append(f'{key} = "{filename}"')
    if include_probe:
        lines.append(f'probe_hardware_report = "{OPTIONAL_FILE_KEYS["probe_hardware_report"]}"')
    lines.append("")
    lines.append("[sources]")
    for key in REFERENCE_URL_KEYS:
        value = sources.get(key)
        if value:
            lines.append(f'{key} = "{value}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        data = _load_basic_toml(path)
    else:
        with path.open("rb") as file:
            data = tomllib.load(file)
    if not isinstance(data, dict):
        raise ConfigError(f"invalid reference set manifest: {path}")
    return data


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"reference set manifest field '{key}' must be a string")
    return value


def _parse_format_version(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ConfigError("reference set manifest field 'format_version' must be an integer")
