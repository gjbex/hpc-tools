from __future__ import annotations

import tomlkit

from hpc_tools import delegation
from hpc_tools.execution import resolve_executor
from hpc_tools.operation_registry import OperationSurface
from hpc_tools.references import resolve_reference_context
from hpc_tools.mcp.common import (
    _json_resource,
    _authorize_mcp,
    current_mcp_binding,
    _read_reference_text,
    _resolve_profile,
)
from hpc_tools.mcp.tools import (
    hpc_paths,
    hpc_profile_show,
    hpc_references_show,
    hpc_submissions_list,
)

def resource_runtime(
    profile: str,
    preset: str,
    runtime: delegation.DelegationRuntime | None = None,
) -> str:
    """Return the effective restricted-server context without profile secrets."""
    resolved = _resolve_profile(profile_name=profile)
    binding = current_mcp_binding()
    _authorize_mcp(
        resolved,
        "delegation.runtime",
        {"profile": resolved.name, "preset": preset},
        surface=OperationSurface.MCP_RESOURCE,
    )
    if runtime is None:
        delegation_data = {
            "configured": False,
            "identifier": None,
            "expires_at": None,
            "allowed": None,
            "per_job_limits": None,
            "budget": None,
            "usage": None,
        }
        limitations = [
            "no delegation manifest is configured",
            "job operations are not scoped to delegation ownership",
        ]
    else:
        ledger = delegation.DelegationLedger(runtime.ledger_path)
        delegation_data = runtime.manifest.public_summary() | {
            "usage": ledger.summary(runtime.manifest),
            "controller": ledger.controller_summary(runtime.manifest),
            "controller_authority": runtime.controller_authority.public_summary(),
        }
        limitations = [
            "Slurm remains authoritative for scheduler policy and accounting",
            "container and filesystem isolation remain external deployment boundaries",
        ]
    return _json_resource(
        {
            "preset": preset,
            "executor": resolve_executor().name,
            "profile": resolved.name,
            "cluster": resolved.default_cluster,
            "capabilities": (
                binding.effective_policy.public_summary()
                if binding is not None
                else resolved.capabilities.public_summary()
            ),
            "delegation": delegation_data,
            "limitations": limitations,
        }
    )

def resource_paths() -> str:
    """Return hpc-tools local paths as JSON."""
    return _json_resource(hpc_paths())

def resource_config() -> str:
    """Return selected-profile TOML from the bound startup snapshot."""
    resolved = _resolve_profile()
    _authorize_mcp(
        resolved,
        "config.read",
        {"profile": resolved.name},
        surface=OperationSurface.MCP_RESOURCE,
    )
    profile = {
        "ssh_target": resolved.target,
        "host": resolved.host,
        "user": resolved.user,
        "ssh_options": list(resolved.ssh_options),
        "login_shell": list(resolved.login_shell),
        "projects_dir": resolved.projects_dir,
        "quota_command": resolved.quota_command,
        "queue_command": resolved.queue_command,
        "sam_balance_command": resolved.sam_balance_command,
        "sam_statement_command": resolved.sam_statement_command,
        "sam_quote_command": resolved.sam_quote_command,
        "hardware_reference": resolved.hardware_reference,
        "hardware_url": resolved.hardware_url,
        "slurm_reference": resolved.slurm_reference,
        "slurm_url": resolved.slurm_url,
        "storage_reference": resolved.storage_reference,
        "storage_url": resolved.storage_url,
        "status_url": resolved.status_url,
        "reference_set": resolved.reference_set,
        "default_cluster": resolved.default_cluster,
        "email": resolved.email,
        "capabilities": resolved.capabilities.public_summary(),
    }
    profile = {key: value for key, value in profile.items() if value is not None}
    return tomlkit.dumps({
        "default_profile": resolved.name,
        "profiles": {resolved.name: profile},
    })

def resource_profile(profile: str) -> str:
    """Return one resolved hpc-tools profile as JSON."""
    return _json_resource(hpc_profile_show(profile=profile))

def resource_profile_hardware(profile: str) -> str:
    """Return the resolved hardware reference for a profile."""
    resolved = _resolve_profile(profile_name=profile)
    _authorize_mcp(
        resolved,
        "references.context",
        {"profile": resolved.name},
        surface=OperationSurface.MCP_RESOURCE,
    )
    context = resolve_reference_context(resolved)
    return _read_reference_text(context.hardware_reference, "hardware", profile)

def resource_profile_slurm(profile: str) -> str:
    """Return the resolved Slurm reference for a profile."""
    resolved = _resolve_profile(profile_name=profile)
    _authorize_mcp(
        resolved,
        "references.context",
        {"profile": resolved.name},
        surface=OperationSurface.MCP_RESOURCE,
    )
    context = resolve_reference_context(resolved)
    return _read_reference_text(context.slurm_reference, "Slurm", profile)

def resource_profile_storage(profile: str) -> str:
    """Return the resolved storage reference for a profile."""
    resolved = _resolve_profile(profile_name=profile)
    _authorize_mcp(
        resolved,
        "references.context",
        {"profile": resolved.name},
        surface=OperationSurface.MCP_RESOURCE,
    )
    context = resolve_reference_context(resolved)
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
