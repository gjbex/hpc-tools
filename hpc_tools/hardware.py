from __future__ import annotations

from pathlib import Path

from hpc_tools.config import ConfigError, Profile


def profile_has_hardware_context(profile: Profile | None) -> bool:
    if profile is None:
        return True
    return any(
        [
            profile.hardware_reference,
            profile.hardware_url,
            profile.slurm_reference,
            profile.slurm_url,
            profile.storage_reference,
            profile.storage_url,
        ]
    )


def render_hardware_context(profile: Profile, *, source_only: bool = False, path_only: bool = False) -> str:
    if not profile_has_hardware_context(profile):
        raise ConfigError(f"profile '{profile.name}' does not define hardware or Slurm reference metadata")

    if source_only:
        return _render_sources(profile)
    if path_only:
        return _render_paths(profile)

    parts = []
    if profile.hardware_reference:
        parts.append(_render_reference("Hardware reference", profile.hardware_reference))
    if profile.slurm_reference:
        parts.append(_render_reference("Slurm reference", profile.slurm_reference))
    if profile.storage_reference:
        parts.append(_render_reference("Storage reference", profile.storage_reference))

    sources = _render_sources(profile)
    if sources:
        parts.append(sources)

    return "\n\n".join(part for part in parts if part)


def _render_reference(title: str, path: str) -> str:
    reference_path = Path(path).expanduser()
    if not reference_path.exists():
        raise ConfigError(f"{title.lower()} file not found: {reference_path}")
    return f"# {title}: {reference_path}\n\n{reference_path.read_text(encoding='utf-8').rstrip()}"


def _render_sources(profile: Profile) -> str:
    lines = []
    if profile.hardware_url:
        lines.append(f"hardware_url: {profile.hardware_url}")
    if profile.slurm_url:
        lines.append(f"slurm_url: {profile.slurm_url}")
    if profile.storage_url:
        lines.append(f"storage_url: {profile.storage_url}")
    return "\n".join(lines)


def _render_paths(profile: Profile) -> str:
    lines = []
    if profile.hardware_reference:
        lines.append(f"hardware_reference: {Path(profile.hardware_reference).expanduser()}")
    if profile.slurm_reference:
        lines.append(f"slurm_reference: {Path(profile.slurm_reference).expanduser()}")
    if profile.storage_reference:
        lines.append(f"storage_reference: {Path(profile.storage_reference).expanduser()}")
    return "\n".join(lines)
