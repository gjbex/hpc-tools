from __future__ import annotations

from pathlib import Path

from hpc_tools.config import ConfigError, Profile
from hpc_tools.references import resolve_reference_context


def profile_has_hardware_context(profile: Profile | None) -> bool:
    if profile is None:
        return True
    context = resolve_reference_context(profile)
    return any(
        [
            context.hardware_reference,
            context.hardware_url,
            context.slurm_reference,
            context.slurm_url,
            context.storage_reference,
            context.storage_url,
        ]
    )


def render_hardware_context(profile: Profile, *, source_only: bool = False, path_only: bool = False) -> str:
    if not profile_has_hardware_context(profile):
        raise ConfigError(f"profile '{profile.name}' does not define hardware or Slurm reference metadata")
    context = resolve_reference_context(profile)

    if source_only:
        return _render_sources(context)
    if path_only:
        return _render_paths(context)

    parts = []
    if context.reference_set:
        parts.append(f"reference_set: {context.reference_set}")
    if context.hardware_reference:
        parts.append(_render_reference("Hardware reference", context.hardware_reference))
    if context.slurm_reference:
        parts.append(_render_reference("Slurm reference", context.slurm_reference))
    if context.storage_reference:
        parts.append(_render_reference("Storage reference", context.storage_reference))

    sources = _render_sources(context)
    if sources:
        parts.append(sources)

    return "\n\n".join(part for part in parts if part)


def _render_reference(title: str, path: str) -> str:
    reference_path = Path(path).expanduser()
    if not reference_path.exists():
        raise ConfigError(f"{title.lower()} file not found: {reference_path}")
    return f"# {title}: {reference_path}\n\n{reference_path.read_text(encoding='utf-8').rstrip()}"


def _render_sources(context) -> str:
    lines = []
    if context.hardware_url:
        lines.append(f"hardware_url: {context.hardware_url}")
    if context.slurm_url:
        lines.append(f"slurm_url: {context.slurm_url}")
    if context.storage_url:
        lines.append(f"storage_url: {context.storage_url}")
    return "\n".join(lines)


def _render_paths(context) -> str:
    lines = []
    if context.reference_set:
        lines.append(f"reference_set: {context.reference_set}")
    if context.hardware_reference:
        lines.append(f"hardware_reference: {Path(context.hardware_reference).expanduser()}")
    if context.slurm_reference:
        lines.append(f"slurm_reference: {Path(context.slurm_reference).expanduser()}")
    if context.storage_reference:
        lines.append(f"storage_reference: {Path(context.storage_reference).expanduser()}")
    return "\n".join(lines)
