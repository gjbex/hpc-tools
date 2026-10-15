from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any

from hpc_tools import delegation, references, submissions
from hpc_tools.authorization import CapabilityAuthorizationError
from hpc_tools.capabilities import (
    AuthorizationContext,
    AuthorizationDecision,
    CapabilityLevel,
    CapabilityPolicy,
    CapabilityRequirement,
    capability_level_allows,
    evaluate_capability,
    intersect_policies,
    narrow_policy,
)
from hpc_tools.config import ConfigError, Profile, default_config_path, load_config, resolve_profile
from hpc_tools.execution import EXECUTOR_NAMES, executor_scope, resolve_executor
from hpc_tools.mcp.common import McpBinding, mcp_binding_scope
from hpc_tools.mcp.resources import (
    resource_config,
    resource_paths,
    resource_profile,
    resource_profile_hardware,
    resource_profile_slurm,
    resource_profile_storage,
    resource_reference_set,
    resource_runtime,
    resource_submissions_active,
    resource_submissions_all,
)
from hpc_tools.mcp.submit import hpc_quote_job, hpc_submit_job, hpc_validate_job
from hpc_tools.mcp.tools import (
    hpc_cancel_job,
    hpc_files_copy,
    hpc_files_download,
    hpc_files_list,
    hpc_files_mkdir,
    hpc_files_read,
    hpc_files_remove,
    hpc_files_upload,
    hpc_hardware_context,
    hpc_hardware_sources,
    hpc_install_container,
    hpc_install_probe,
    hpc_job,
    hpc_job_accounting,
    hpc_jobs,
    hpc_module_spider,
    hpc_paths,
    hpc_plugins_list,
    hpc_profile_show,
    hpc_profiles_list,
    hpc_references_attach,
    hpc_references_create,
    hpc_references_import,
    hpc_references_list,
    hpc_references_show,
    hpc_repo_clone,
    hpc_site_env,
    hpc_slurm_limits,
    hpc_status,
    hpc_storage_inspect,
    hpc_submissions_close,
    hpc_submissions_list,
    hpc_submissions_mark_analysed,
    hpc_submissions_mark_collected,
    hpc_write_container,
    hpc_write_probe,
)
from hpc_tools.operation_registry import (
    OPERATION_REGISTRY,
    OperationDescriptor,
    OperationSurface,
    RequestContext,
)
from hpc_tools.references import resolve_reference_context

PRESET_ENV_VAR = "HPC_TOOLS_MCP_PRESET"
PROFILE_ENV_VAR = "HPC_TOOLS_MCP_PROFILE"
DEFAULT_PRESET = "full"
PRESET_NAMES = (
    "context",
    "discovery",
    "job-inspect",
    "job-lifecycle",
    "full",
    "slurm-job",
)

PRESET_LEVELS = {
    "context": CapabilityLevel.PROFILE_CONTEXT,
    "discovery": CapabilityLevel.CLUSTER_DISCOVERY,
    "job-inspect": CapabilityLevel.JOB_INSPECTION,
    "job-lifecycle": CapabilityLevel.JOB_LIFECYCLE,
    "slurm-job": CapabilityLevel.JOB_LIFECYCLE,
}


FULL_TOOL_NAMES = tuple(OPERATION_REGISTRY.bindings(OperationSurface.MCP_TOOL))

SLURM_JOB_TOOL_NAMES = (
    "hpc_jobs",
    "hpc_job",
    "hpc_job_accounting",
    "hpc_cancel_job",
    "hpc_quote_job",
    "hpc_validate_job",
    "hpc_submit_job",
)

FULL_RESOURCE_URIS = tuple(OPERATION_REGISTRY.bindings(OperationSurface.MCP_RESOURCE))
FULL_RESOURCE_TEMPLATES: tuple[str, ...] = ()

SLURM_JOB_RESOURCE_URIS = (
    "hpc://runtime",
    "hpc://cluster/hardware",
    "hpc://cluster/slurm",
    "hpc://cluster/storage",
)
SLURM_JOB_RESOURCE_TEMPLATES: tuple[str, ...] = ()

# Compatibility aliases for code that inspects the original full registry.
TOOL_NAMES = FULL_TOOL_NAMES
RESOURCE_URIS = FULL_RESOURCE_URIS
RESOURCE_TEMPLATES = FULL_RESOURCE_TEMPLATES


_TOOLS = (
    hpc_profiles_list,
    hpc_paths,
    hpc_profile_show,
    hpc_hardware_context,
    hpc_hardware_sources,
    hpc_references_list,
    hpc_references_show,
    hpc_plugins_list,
    hpc_submissions_list,
    hpc_status,
    hpc_jobs,
    hpc_job,
    hpc_job_accounting,
    hpc_cancel_job,
    hpc_slurm_limits,
    hpc_module_spider,
    hpc_storage_inspect,
    hpc_files_list,
    hpc_files_read,
    hpc_files_download,
    hpc_files_upload,
    hpc_files_copy,
    hpc_files_mkdir,
    hpc_files_remove,
    hpc_repo_clone,
    hpc_site_env,
    hpc_references_create,
    hpc_references_import,
    hpc_references_attach,
    hpc_submissions_mark_collected,
    hpc_submissions_mark_analysed,
    hpc_submissions_close,
    hpc_write_probe,
    hpc_install_probe,
    hpc_write_container,
    hpc_install_container,
    hpc_quote_job,
    hpc_validate_job,
    hpc_submit_job,
)
_TOOLS_BY_NAME = {function.__name__: function for function in _TOOLS}


def _no_resource_args(
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None,
) -> tuple[Any, ...]:
    return ()


def _profile_resource_args(
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None,
) -> tuple[Any, ...]:
    return (binding.profile.name,)


def _runtime_resource_args(
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None,
) -> tuple[Any, ...]:
    return (binding.profile.name, binding.preset, runtime)


def _reference_resource_args(
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None,
) -> tuple[Any, ...]:
    return (binding.profile.reference_set,)


_RESOURCES = (
    ("hpc://paths", resource_paths, _no_resource_args, "application/json"),
    ("hpc://profile", resource_profile, _profile_resource_args, "application/json"),
    ("hpc://config", resource_config, _no_resource_args, "application/toml"),
    ("hpc://reference-set", resource_reference_set, _reference_resource_args, "application/json"),
    ("hpc://cluster/hardware", resource_profile_hardware, _profile_resource_args, "text/markdown"),
    ("hpc://cluster/slurm", resource_profile_slurm, _profile_resource_args, "text/markdown"),
    ("hpc://cluster/storage", resource_profile_storage, _profile_resource_args, "text/markdown"),
    ("hpc://submissions/active", resource_submissions_active, _no_resource_args, "application/json"),
    ("hpc://submissions/all", resource_submissions_all, _no_resource_args, "application/json"),
    ("hpc://runtime", resource_runtime, _runtime_resource_args, "application/json"),
)


def _effective_policy(profile: Profile, preset: str) -> CapabilityPolicy:
    level = PRESET_LEVELS.get(preset)
    return narrow_policy(profile.capabilities, level)


def _default_arguments(function: Callable[..., Any]) -> dict[str, Any]:
    return {
        name: (None if parameter.default is inspect.Parameter.empty else parameter.default)
        for name, parameter in inspect.signature(function).parameters.items()
    }


def _decision(
    descriptor: OperationDescriptor,
    profile: Profile,
    policy: CapabilityPolicy,
    surface: OperationSurface,
    arguments: dict[str, Any],
) -> AuthorizationDecision:
    resolved = OPERATION_REGISTRY.resolve(RequestContext(
        operation_id=descriptor.id,
        surface=surface,
        arguments=arguments,
        profile=profile,
    ))
    context = AuthorizationContext.from_profile(profile, restrictions=(policy,))

    def representative(requirement: CapabilityRequirement) -> CapabilityRequirement:
        return replace(
            requirement,
            paths=tuple(
                replace(path, path=getattr(context.policy.remote_roots, path.grant)[0])
                if path.path is None and getattr(context.policy.remote_roots, path.grant)
                else path
                for path in requirement.paths
            ),
        )

    decisions = (
        evaluate_capability(representative(resolved.requirement), context),
        *(evaluate_capability(representative(item), context) for item in resolved.components),
    )
    denials = tuple(item for decision in decisions for item in decision.denials)
    return AuthorizationDecision(
        operation_id=descriptor.id,
        profile_name=profile.name,
        denials=denials,
    )


def _tool_is_available(
    name: str,
    profile: Profile,
    policy: CapabilityPolicy,
) -> bool:
    if name == "hpc_references_show":
        try:
            references.load_reference_set(profile.reference_set)
        except ConfigError:
            return False
    descriptor = OPERATION_REGISTRY.for_binding(OperationSurface.MCP_TOOL, name)
    if descriptor is None:
        return False
    return _decision(
        descriptor,
        profile,
        policy,
        OperationSurface.MCP_TOOL,
        _default_arguments(_TOOLS_BY_NAME[name]),
    ).allowed


def _resource_is_available(
    uri: str,
    profile: Profile,
    policy: CapabilityPolicy,
) -> bool:
    if uri == "hpc://reference-set":
        try:
            references.load_reference_set(profile.reference_set)
        except ConfigError:
            return False
    reference_field = {
        "hpc://cluster/hardware": "hardware_reference",
        "hpc://cluster/slurm": "slurm_reference",
        "hpc://cluster/storage": "storage_reference",
    }.get(uri)
    if reference_field is not None:
        try:
            reference_path = getattr(resolve_reference_context(profile), reference_field)
        except ConfigError:
            return False
        if not reference_path or not Path(reference_path).expanduser().is_file():
            return False
    descriptor = OPERATION_REGISTRY.for_binding(OperationSurface.MCP_RESOURCE, uri)
    if descriptor is None:
        return False
    return _decision(
        descriptor,
        profile,
        policy,
        OperationSurface.MCP_RESOURCE,
        {"profile": profile.name},
    ).allowed


def resolve_preset(name: str | None = None) -> str:
    selected = name or os.environ.get(PRESET_ENV_VAR) or DEFAULT_PRESET
    if selected not in PRESET_NAMES:
        choices = ", ".join(PRESET_NAMES)
        raise ConfigError(
            f"unknown MCP preset '{selected}'; expected one of: {choices}"
        )
    return selected


def tool_names_for_preset(
    preset: str,
    profile: Profile | None = None,
) -> tuple[str, ...]:
    selected = resolve_preset(preset)
    candidates = (
        SLURM_JOB_TOOL_NAMES if selected == "slurm-job" else FULL_TOOL_NAMES
    )
    if profile is None:
        ceiling = PRESET_LEVELS.get(selected)
        if ceiling is None or selected == "slurm-job":
            return candidates
        return tuple(
            name
            for name in candidates
            if (
                (descriptor := OPERATION_REGISTRY.for_binding(
                    OperationSurface.MCP_TOOL,
                    name,
                )) is not None
                and not descriptor.operator_only
                and capability_level_allows(ceiling, descriptor.minimum_level)
            )
        )
    policy = _effective_policy(profile, selected)
    return _tool_names_for_policy(selected, profile, policy)


def _tool_names_for_policy(
    preset: str,
    profile: Profile,
    policy: CapabilityPolicy,
) -> tuple[str, ...]:
    candidates = (
        SLURM_JOB_TOOL_NAMES if preset == "slurm-job" else FULL_TOOL_NAMES
    )
    return tuple(
        name
        for name in candidates
        if _tool_is_available(name, profile, policy)
    )


def resource_uris_for_preset(
    preset: str,
    profile: Profile | None = None,
) -> tuple[str, ...]:
    selected = resolve_preset(preset)
    candidates = (
        SLURM_JOB_RESOURCE_URIS if selected == "slurm-job" else FULL_RESOURCE_URIS
    )
    if profile is None:
        ceiling = PRESET_LEVELS.get(selected)
        if ceiling is None or selected == "slurm-job":
            return candidates
        return tuple(
            uri
            for uri in candidates
            if (
                (descriptor := OPERATION_REGISTRY.for_binding(
                    OperationSurface.MCP_RESOURCE,
                    uri,
                )) is not None
                and capability_level_allows(ceiling, descriptor.minimum_level)
            )
        )
    policy = _effective_policy(profile, selected)
    return _resource_uris_for_policy(selected, profile, policy)


def _resource_uris_for_policy(
    preset: str,
    profile: Profile,
    policy: CapabilityPolicy,
) -> tuple[str, ...]:
    candidates = (
        SLURM_JOB_RESOURCE_URIS if preset == "slurm-job" else FULL_RESOURCE_URIS
    )
    return tuple(
        uri
        for uri in candidates
        if _resource_is_available(uri, profile, policy)
    )


def resource_templates_for_preset(preset: str) -> tuple[str, ...]:
    resolve_preset(preset)
    return ()


def create_server(
    *,
    preset: str | None = None,
    profile: str | None = None,
    delegation_manifest: str | None = None,
    ledger: str | None = None,
    config: str | None = None,
):
    """Create the FastMCP server for hpc-tools guarded agent tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise ConfigError(
            "hpc-mcp requires the optional MCP dependency. "
            "Install it with `uv sync --locked --extra mcp` or `pip install 'hpc-tools[mcp]'."
        ) from error

    selected_preset = resolve_preset(preset)
    executor = resolve_executor()
    config_path = (
        Path(config).expanduser() if config else default_config_path().expanduser()
    ).resolve()
    loaded_config = load_config(str(config_path))
    selected = resolve_profile(
        loaded_config,
        profile or os.environ.get(PROFILE_ENV_VAR),
    )
    effective_policy = _effective_policy(selected, selected_preset)
    runtime = None
    if selected_preset == "slurm-job":
        manifest_path = delegation_manifest or os.environ.get(
            delegation.DELEGATION_ENV_VAR
        )
        if not manifest_path:
            raise ConfigError(
                f"the slurm-job preset requires --delegation or "
                f"{delegation.DELEGATION_ENV_VAR}"
            )
        if manifest_path:
            parent_job_id = os.environ.get(delegation.PARENT_JOB_ENV_VAR)
            if not parent_job_id:
                raise ConfigError(
                    f"{delegation.PARENT_JOB_ENV_VAR} is required with a delegation manifest"
                )
            runtime = delegation.load_runtime(
                manifest_path,
                profile=selected.name,
                ledger_path=ledger,
                parent_job_id=parent_job_id,
                profile_policy=effective_policy,
                config_path=config_path,
                config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
            )
            effective_policy = intersect_policies(
                effective_policy,
                runtime.controller_authority.policy,
            )

    binding = McpBinding(
        profile=selected,
        effective_policy=effective_policy,
        config_path=config_path,
        database_path=submissions.default_database_path().expanduser(),
        preset=selected_preset,
    )

    server = FastMCP(
        "hpc-tools",
        instructions=(
            "Guarded hpc-tools interface for agents. This server exposes "
            f"the {selected_preset} preset for profile {selected.name}. "
            "Slurm job submission is exposed only through quote, validation, "
            "and evidence-gated submit tools. Ordinary mode also requires explicit "
            "confirmation; delegated mode uses host-side authorization. "
            "Tools and resources are filtered from the immutable startup policy "
            "snapshot; restart the server after configuration changes. "
            f"Delegation enforcement is {'enabled' if runtime else 'not configured'}. "
            f"Cluster commands use the {executor.name} executor."
        ),
    )
    for name in _tool_names_for_policy(selected_preset, selected, effective_policy):
        server.tool()(_bind_profile(_TOOLS_BY_NAME[name], binding, runtime))

    allowed_resources = set(
        _resource_uris_for_policy(selected_preset, selected, effective_policy)
    )
    for uri, function, args, mime_type in _RESOURCES:
        if uri not in allowed_resources:
            continue
        if uri == "hpc://reference-set" and not selected.reference_set:
            continue
        bound = _bind_resource(
            uri,
            function,
            binding,
            runtime,
            *args(binding, runtime),
        )
        server.resource(uri, mime_type=mime_type)(bound)
    return server


def _bind_resource(
    uri: str,
    function: Callable[..., str],
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None,
    *args: Any,
) -> Callable[[], str]:
    """Bind fixed resource arguments while preserving a useful MCP name."""

    @wraps(function)
    def bound() -> str:
        with mcp_binding_scope(binding), delegation.delegation_scope(runtime):
            descriptor = OPERATION_REGISTRY.for_binding(
                OperationSurface.MCP_RESOURCE,
                uri,
            )
            if descriptor is None:
                raise ConfigError(f"MCP resource is not registered: {uri}")
            decision = _decision(
                descriptor,
                binding.profile,
                binding.effective_policy,
                OperationSurface.MCP_RESOURCE,
                {"profile": binding.profile.name},
            )
            if not decision.allowed:
                raise CapabilityAuthorizationError(decision)
            return function(*args)

    bound.__signature__ = inspect.Signature(return_annotation=str)
    return bound


def _bind_profile(
    function: Callable[..., Any],
    binding: McpBinding,
    runtime: delegation.DelegationRuntime | None = None,
) -> Callable[..., Any]:
    """Bind one MCP tool to trusted startup selections and hide overrides."""
    signature = inspect.signature(function)
    public_signature = _bound_tool_signature(function, delegated=runtime is not None)
    restricted_submission = runtime is not None and function.__name__ in {
        "hpc_quote_job", "hpc_validate_job", "hpc_submit_job"
    }
    fixed_kwargs: dict[str, Any] = {}
    if "profile" in signature.parameters:
        fixed_kwargs["profile"] = binding.profile.name
    if "config" in signature.parameters:
        fixed_kwargs["config"] = str(binding.config_path)
    if "database" in signature.parameters:
        fixed_kwargs["database"] = str(binding.database_path)
    if runtime is not None and "confirm" in signature.parameters:
        fixed_kwargs["confirm"] = False
    if restricted_submission:
        fixed_kwargs.update({"error": None, "output": None, "export": None})

    @wraps(function)
    def bound(**kwargs: Any) -> Any:
        with mcp_binding_scope(binding), delegation.delegation_scope(runtime):
            descriptor = OPERATION_REGISTRY.for_binding(
                OperationSurface.MCP_TOOL,
                function.__name__,
            )
            if descriptor is None:
                raise ConfigError(
                    f"MCP tool is not registered: {function.__name__}"
                )
            decision = _decision(
                descriptor,
                binding.profile,
                binding.effective_policy,
                OperationSurface.MCP_TOOL,
                {**kwargs, **fixed_kwargs},
            )
            if not decision.allowed:
                raise CapabilityAuthorizationError(decision)
            return function(**kwargs, **fixed_kwargs)

    bound.__signature__ = public_signature
    return bound


def _bound_tool_signature(
    function: Callable[..., Any],
    *,
    delegated: bool = False,
) -> inspect.Signature:
    """Return the public schema for a profile-bound MCP tool."""
    signature = inspect.signature(function)
    hidden = {"profile", "config", "database"}
    if delegated:
        hidden.add("confirm")
        if function.__name__ in {
            "hpc_quote_job", "hpc_validate_job", "hpc_submit_job"
        }:
            hidden.update({"error", "output", "export"})
    return signature.replace(parameters=[
        parameter
        for name, parameter in signature.parameters.items()
        if name not in hidden
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpc-mcp")
    parser.add_argument(
        "--executor",
        choices=EXECUTOR_NAMES,
        help="Command executor; defaults to HPC_TOOLS_EXECUTOR or ssh",
    )
    parser.add_argument(
        "--preset",
        choices=PRESET_NAMES,
        help=f"MCP capability preset; defaults to {PRESET_ENV_VAR} or full",
    )
    parser.add_argument(
        "--profile",
        help=(
            "profile bound to this server; defaults to "
            f"{PROFILE_ENV_VAR} or the configured default"
        ),
    )
    parser.add_argument(
        "--config",
        help="configuration file path; defaults to HPC_TOOLS_CONFIG or the standard path",
    )
    parser.add_argument(
        "--delegation",
        help=f"host-side delegation manifest; defaults to {delegation.DELEGATION_ENV_VAR}",
    )
    parser.add_argument(
        "--ledger",
        help=f"server-owned delegation ledger; defaults to {delegation.LEDGER_ENV_VAR}",
    )
    args = parser.parse_args(argv)
    try:
        with executor_scope(args.executor):
            create_server(
                preset=args.preset,
                profile=args.profile,
                delegation_manifest=args.delegation,
                ledger=args.ledger,
                config=args.config,
            ).run()
    except ConfigError as error:
        print(f"hpc-mcp: {error}", file=sys.stderr)
        return 2
    return 0
