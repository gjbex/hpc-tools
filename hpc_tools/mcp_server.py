from __future__ import annotations

from dataclasses import asdict
from importlib import resources
import json
from pathlib import Path
import sys
from typing import Any

from hpc_tools import __version__, plugin_system, references, slurm, submissions
from hpc_tools.cli import _site_env_command, _storage_inspect_command
from hpc_tools.config import (
    Config,
    ConfigError,
    Profile,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
    load_config,
    resolve_profile,
)
from hpc_tools.hardware import render_hardware_context
from hpc_tools.references import resolve_reference_context
from hpc_tools.ssh import build_ssh_argv, format_command, run_remote_capture


TOOL_NAMES = (
    "hpc_profiles_list",
    "hpc_paths",
    "hpc_profile_show",
    "hpc_hardware_context",
    "hpc_hardware_sources",
    "hpc_references_list",
    "hpc_references_show",
    "hpc_plugins_list",
    "hpc_submissions_list",
    "hpc_jobs",
    "hpc_job",
    "hpc_slurm_limits",
    "hpc_storage_inspect",
    "hpc_site_env",
)

RESOURCE_URIS = (
    "hpc://paths",
    "hpc://config",
    "hpc://submissions/active",
    "hpc://submissions/all",
)

RESOURCE_TEMPLATES = (
    "hpc://profiles/{profile}",
    "hpc://profiles/{profile}/hardware",
    "hpc://profiles/{profile}/slurm",
    "hpc://profiles/{profile}/storage",
    "hpc://reference-sets/{name}",
)


def create_server():
    """Create the FastMCP server for hpc-tools read-only tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise ConfigError(
            "hpc-mcp requires the optional MCP dependency. "
            "Install it with `uv pip install -e '.[mcp]'` or `pip install 'hpc-tools[mcp]'`."
        ) from error

    server = FastMCP(
        "hpc-tools",
        instructions=(
            "Read-only hpc-tools interface for agents. This server exposes "
            "profile, reference, plugin, Slurm-inspection, and submission-log "
            "context. It does not expose write, install, or Slurm submission tools."
        ),
    )
    for function in (
        hpc_profiles_list,
        hpc_paths,
        hpc_profile_show,
        hpc_hardware_context,
        hpc_hardware_sources,
        hpc_references_list,
        hpc_references_show,
        hpc_plugins_list,
        hpc_submissions_list,
        hpc_jobs,
        hpc_job,
        hpc_slurm_limits,
        hpc_storage_inspect,
        hpc_site_env,
    ):
        server.tool()(function)
    for uri, function, mime_type in (
        ("hpc://paths", resource_paths, "application/json"),
        ("hpc://config", resource_config, "text/plain"),
        ("hpc://submissions/active", resource_submissions_active, "application/json"),
        ("hpc://submissions/all", resource_submissions_all, "application/json"),
        ("hpc://profiles/{profile}", resource_profile, "application/json"),
        ("hpc://profiles/{profile}/hardware", resource_profile_hardware, "text/markdown"),
        ("hpc://profiles/{profile}/slurm", resource_profile_slurm, "text/markdown"),
        ("hpc://profiles/{profile}/storage", resource_profile_storage, "text/markdown"),
        ("hpc://reference-sets/{name}", resource_reference_set, "application/json"),
    ):
        server.resource(uri, mime_type=mime_type)(function)
    return server


def main() -> int:
    try:
        create_server().run()
    except ConfigError as error:
        print(f"hpc-mcp: {error}", file=sys.stderr)
        return 2
    return 0


def hpc_profiles_list(config: str | None = None) -> dict[str, Any]:
    """List profiles from the hpc-tools config."""
    loaded_config = _load_config(config)
    return {
        "config": str(Path(config).expanduser() if config else default_config_path()),
        "default_profile": loaded_config.default_profile,
        "profiles": [_profile_summary(profile) for profile in loaded_config.profiles.values()],
    }


def hpc_paths() -> dict[str, Any]:
    """Show local hpc-tools config, reference, package, and skill paths."""
    config_dir = default_config_dir()
    return {
        "config": str(default_config_path()),
        "profile_references": str(config_dir / "profiles" / "<profile>"),
        "reference_sets": str(default_reference_sets_dir()),
        "codex_skills": "~/.codex/skills/",
        "hardware_probe_template": str(resources.files("hpc_tools.data").joinpath("hardware-probe.slurm")),
        "cuda_device_properties_template": str(
            resources.files("hpc_tools.data").joinpath("cuda-device-properties.slurm")
        ),
        "cuda_device_properties_source": str(resources.files("hpc_tools.data").joinpath("cuda")),
        "package_uninstall": "pipx uninstall hpc-tools",
    }


def hpc_profile_show(profile: str | None = None, config: str | None = None) -> dict[str, Any]:
    """Show one resolved hpc-tools profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    return _profile_to_dict(resolved)


def hpc_hardware_context(profile: str | None = None, config: str | None = None) -> dict[str, Any]:
    """Render configured hardware, Slurm, and storage reference context for a profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    return {
        "profile": resolved.name,
        "context": render_hardware_context(resolved),
    }


def hpc_hardware_sources(profile: str | None = None, config: str | None = None) -> dict[str, Any]:
    """Return structured hardware, Slurm, storage, and status source metadata."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    context = resolve_reference_context(resolved)
    return {
        "profile": resolved.name,
        "reference_set": context.reference_set,
        "hardware_reference": _expanded(context.hardware_reference),
        "hardware_url": context.hardware_url,
        "slurm_reference": _expanded(context.slurm_reference),
        "slurm_url": context.slurm_url,
        "storage_reference": _expanded(context.storage_reference),
        "storage_url": context.storage_url,
        "status_url": context.status_url,
        "probe_hardware_report": _expanded(context.probe_hardware_report),
    }


def hpc_references_list() -> dict[str, Any]:
    """List installed hpc-tools reference sets."""
    return {
        "reference_sets": [
            _reference_set_to_dict(reference_set)
            for reference_set in references.list_reference_sets()
        ]
    }


def hpc_references_show(name: str) -> dict[str, Any]:
    """Show one installed hpc-tools reference set."""
    return _reference_set_to_dict(references.load_reference_set(name))


def hpc_plugins_list() -> dict[str, Any]:
    """List installed hpc-tools CLI plugins."""
    return {
        "plugins": [
            {
                "name": plugin.name,
                "version": plugin.version,
                "source": plugin.source,
                "description": plugin.description,
            }
            for plugin in plugin_system.load_plugins()
        ]
    }


def hpc_submissions_list(all: bool = False, log: str | None = None) -> dict[str, Any]:
    """List hpc-tools submission records from the append-only local event log."""
    log_path = Path(log).expanduser() if log else None
    events = submissions.read_events(log_path)
    records = submissions.records_from_events(events) if all else submissions.active_records(events)
    return {
        "log": str(log_path or submissions.default_log_path()),
        "all": all,
        "submissions": [_submission_record_to_dict(record) for record in records],
    }


def hpc_jobs(
    profile: str | None = None,
    config: str | None = None,
    cluster: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show current user's Slurm jobs for a profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    command = slurm.squeue_user_command(cluster)
    return _remote_read_result(resolved, command, dry_run=dry_run)


def hpc_job(
    jobid: str,
    profile: str | None = None,
    config: str | None = None,
    cluster: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show Slurm status for one job ID."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    command = slurm.squeue_job_command(jobid, cluster)
    return _remote_read_result(resolved, command, dry_run=dry_run)


def hpc_slurm_limits(
    profile: str | None = None,
    config: str | None = None,
    cluster: str | None = None,
    partition: str | None = None,
    qos: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect Slurm controller, partition, QoS, and association limits."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    command = slurm.slurm_limits_command(cluster=cluster, partition=partition, qos=qos)
    return _remote_read_result(resolved, command, dry_run=dry_run)


def hpc_storage_inspect(
    profile: str | None = None,
    config: str | None = None,
    path: str = ".",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect one remote filesystem path with bounded read-only checks."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    command = _storage_inspect_command(path)
    return _remote_read_result(resolved, command, dry_run=dry_run)


def hpc_site_env(
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect remote site environment variables and common HPC helper tools."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    return _remote_read_result(resolved, _site_env_command(), dry_run=dry_run)


def resource_paths() -> str:
    """Return hpc-tools local paths as JSON."""
    return _json_resource(hpc_paths())


def resource_config() -> str:
    """Return the active hpc-tools config file."""
    config_path = default_config_path()
    if not config_path.exists():
        raise ConfigError(f"configuration file not found: {config_path}")
    return config_path.read_text(encoding="utf-8")


def resource_profile(profile: str) -> str:
    """Return one resolved hpc-tools profile as JSON."""
    return _json_resource(hpc_profile_show(profile=profile))


def resource_profile_hardware(profile: str) -> str:
    """Return the resolved hardware reference for a profile."""
    context = resolve_reference_context(_resolve_profile(profile_name=profile))
    return _read_reference_text(context.hardware_reference, "hardware", profile)


def resource_profile_slurm(profile: str) -> str:
    """Return the resolved Slurm reference for a profile."""
    context = resolve_reference_context(_resolve_profile(profile_name=profile))
    return _read_reference_text(context.slurm_reference, "Slurm", profile)


def resource_profile_storage(profile: str) -> str:
    """Return the resolved storage reference for a profile."""
    context = resolve_reference_context(_resolve_profile(profile_name=profile))
    return _read_reference_text(context.storage_reference, "storage", profile)


def resource_reference_set(name: str) -> str:
    """Return one installed hpc-tools reference set as JSON."""
    return _json_resource(hpc_references_show(name))


def resource_submissions_active() -> str:
    """Return active submission records as JSON."""
    return _json_resource(hpc_submissions_list(all=False))


def resource_submissions_all() -> str:
    """Return all submission records as JSON."""
    return _json_resource(hpc_submissions_list(all=True))


def _load_config(config_path: str | None = None) -> Config:
    return load_config(config_path)


def _resolve_profile(*, profile_name: str | None = None, config_path: str | None = None) -> Profile:
    config = _load_config(config_path)
    return resolve_profile(config, profile_name)


def _remote_read_result(profile: Profile, command: str, *, dry_run: bool = False) -> dict[str, Any]:
    ssh_argv = build_ssh_argv(profile, command)
    if dry_run:
        return {
            "profile": profile.name,
            "command": command,
            "ssh_command": format_command(ssh_argv),
            "dry_run": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    completed = run_remote_capture(profile, command)
    return {
        "profile": profile.name,
        "command": command,
        "ssh_command": format_command(ssh_argv),
        "dry_run": False,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _profile_summary(profile: Profile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "ssh_target": profile.ssh_target,
        "host": profile.host,
        "user": profile.user,
        "default_cluster": profile.default_cluster,
        "reference_set": profile.reference_set,
        "has_hardware_reference": bool(profile.hardware_reference),
        "has_slurm_reference": bool(profile.slurm_reference),
        "has_storage_reference": bool(profile.storage_reference),
        "has_status_url": bool(profile.status_url),
    }


def _profile_to_dict(profile: Profile) -> dict[str, Any]:
    return asdict(profile) | {"ssh_target": profile.ssh_target}


def _reference_set_to_dict(reference_set: references.ReferenceSet) -> dict[str, Any]:
    return {
        "name": reference_set.name,
        "path": str(reference_set.path),
        "format_version": reference_set.format_version,
        "created_at": reference_set.created_at,
        "source_profile": reference_set.source_profile,
        "hardware_reference": str(reference_set.hardware_reference),
        "hardware_url": reference_set.hardware_url,
        "slurm_reference": str(reference_set.slurm_reference),
        "slurm_url": reference_set.slurm_url,
        "storage_reference": str(reference_set.storage_reference),
        "storage_url": reference_set.storage_url,
        "status_url": reference_set.status_url,
        "probe_hardware_report": str(reference_set.probe_hardware_report) if reference_set.probe_hardware_report else None,
    }


def _submission_record_to_dict(record: submissions.SubmissionRecord) -> dict[str, Any]:
    return asdict(record)


def _json_resource(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _read_reference_text(path: str | None, label: str, profile: str) -> str:
    if not path:
        raise ConfigError(f"profile '{profile}' does not define a {label} reference")
    reference_path = Path(path).expanduser()
    if not reference_path.exists():
        raise ConfigError(f"{label} reference file not found: {reference_path}")
    return reference_path.read_text(encoding="utf-8")


def _expanded(path: str | None) -> str | None:
    return str(Path(path).expanduser()) if path else None


if __name__ == "__main__":
    raise SystemExit(main())
