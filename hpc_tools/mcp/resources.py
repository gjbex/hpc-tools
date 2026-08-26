from __future__ import annotations

from hpc_tools import references, submissions
from hpc_tools.execution import resolve_executor
from hpc_tools.config import default_config_path
from hpc_tools.references import resolve_reference_context
from hpc_tools.mcp.common import (
    _json_resource,
    _load_config,
    _profile_to_dict,
    _read_reference_text,
    _reference_set_to_dict,
    _resolve_profile,
    _submission_record_to_dict,
)
from hpc_tools.mcp.tools import hpc_paths, hpc_profile_show, hpc_references_show

def resource_runtime(profile: str, preset: str) -> str:
    """Return the effective restricted-server context without profile secrets."""
    resolved = _resolve_profile(profile_name=profile)
    return _json_resource(
        {
            "preset": preset,
            "executor": resolve_executor().name,
            "profile": resolved.name,
            "cluster": resolved.default_cluster,
            "delegation": {
                "configured": False,
                "identifier": None,
                "expires_at": None,
                "allowed_accounts": None,
                "allowed_partitions": None,
                "allowed_roots": None,
                "remaining_submissions": None,
                "remaining_resource_budget": None,
            },
            "limitations": [
                "delegation policy and budget enforcement are not implemented",
                "job operations are not yet scoped to delegation ownership",
            ],
        }
    )

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
