from __future__ import annotations

import argparse
from functools import wraps
import inspect
import os
import sys
from typing import Any, Callable

from hpc_tools.config import ConfigError
from hpc_tools import delegation
from hpc_tools.execution import EXECUTOR_NAMES, executor_scope, resolve_executor
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
    hpc_hardware_context,
    hpc_hardware_sources,
    hpc_install_container,
    hpc_install_probe,
    hpc_job,
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


PRESET_ENV_VAR = "HPC_TOOLS_MCP_PRESET"
PROFILE_ENV_VAR = "HPC_TOOLS_MCP_PROFILE"
DEFAULT_PRESET = "full"
PRESET_NAMES = ("full", "slurm-job")


FULL_TOOL_NAMES = (
    "hpc_profiles_list",
    "hpc_paths",
    "hpc_profile_show",
    "hpc_hardware_context",
    "hpc_hardware_sources",
    "hpc_references_list",
    "hpc_references_show",
    "hpc_plugins_list",
    "hpc_submissions_list",
    "hpc_status",
    "hpc_jobs",
    "hpc_job",
    "hpc_cancel_job",
    "hpc_slurm_limits",
    "hpc_module_spider",
    "hpc_storage_inspect",
    "hpc_site_env",
    "hpc_references_create",
    "hpc_references_import",
    "hpc_references_attach",
    "hpc_submissions_mark_collected",
    "hpc_submissions_mark_analysed",
    "hpc_submissions_close",
    "hpc_write_probe",
    "hpc_install_probe",
    "hpc_write_container",
    "hpc_install_container",
    "hpc_quote_job",
    "hpc_validate_job",
    "hpc_submit_job",
)

SLURM_JOB_TOOL_NAMES = (
    "hpc_jobs",
    "hpc_job",
    "hpc_cancel_job",
    "hpc_quote_job",
    "hpc_validate_job",
    "hpc_submit_job",
)

FULL_RESOURCE_URIS = (
    "hpc://paths",
    "hpc://config",
    "hpc://submissions/active",
    "hpc://submissions/all",
)

FULL_RESOURCE_TEMPLATES = (
    "hpc://profiles/{profile}",
    "hpc://profiles/{profile}/hardware",
    "hpc://profiles/{profile}/slurm",
    "hpc://profiles/{profile}/storage",
    "hpc://reference-sets/{name}",
)

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


def resolve_preset(name: str | None = None) -> str:
    selected = name or os.environ.get(PRESET_ENV_VAR) or DEFAULT_PRESET
    if selected not in PRESET_NAMES:
        choices = ", ".join(PRESET_NAMES)
        raise ConfigError(
            f"unknown MCP preset '{selected}'; expected one of: {choices}"
        )
    return selected


def tool_names_for_preset(preset: str) -> tuple[str, ...]:
    selected = resolve_preset(preset)
    return FULL_TOOL_NAMES if selected == "full" else SLURM_JOB_TOOL_NAMES


def resource_uris_for_preset(preset: str) -> tuple[str, ...]:
    selected = resolve_preset(preset)
    return FULL_RESOURCE_URIS if selected == "full" else SLURM_JOB_RESOURCE_URIS


def resource_templates_for_preset(preset: str) -> tuple[str, ...]:
    selected = resolve_preset(preset)
    return (
        FULL_RESOURCE_TEMPLATES
        if selected == "full"
        else SLURM_JOB_RESOURCE_TEMPLATES
    )


def create_server(
    *,
    preset: str | None = None,
    profile: str | None = None,
    delegation_manifest: str | None = None,
    ledger: str | None = None,
):
    """Create the FastMCP server for hpc-tools guarded agent tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise ConfigError(
            "hpc-mcp requires the optional MCP dependency. "
            "Install it with `uv pip install -e '.[mcp]'` or `pip install 'hpc-tools[mcp]'."
        ) from error

    selected_preset = resolve_preset(preset)
    executor = resolve_executor()
    selected_profile = profile or os.environ.get(PROFILE_ENV_VAR)
    runtime = None
    if selected_preset == "slurm-job":
        from hpc_tools.mcp.common import _resolve_profile

        selected_profile = _resolve_profile(profile_name=selected_profile).name
        manifest_path = delegation_manifest or os.environ.get(delegation.DELEGATION_ENV_VAR)
        if manifest_path:
            parent_job_id = os.environ.get(delegation.PARENT_JOB_ENV_VAR)
            if not parent_job_id:
                raise ConfigError(
                    f"{delegation.PARENT_JOB_ENV_VAR} is required with a delegation manifest"
                )
            runtime = delegation.load_runtime(
                manifest_path,
                profile=selected_profile,
                ledger_path=ledger,
                parent_job_id=parent_job_id,
            )

    server = FastMCP(
        "hpc-tools",
        instructions=(
            "Guarded hpc-tools interface for agents. This server exposes "
            f"the {selected_preset} capability preset. "
            "Slurm job submission is exposed only through quote, validation, "
            "and confirm-gated submit tools with matching evidence. "
            "The slurm-job preset is restricted to stored cluster context and "
            "job-lifecycle operations bound to one selected profile. "
            f"Delegation enforcement is {'enabled' if runtime else 'not configured'}. "
            f"Cluster commands use the {executor.name} executor."
        ),
    )
    tools = (
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
        hpc_cancel_job,
        hpc_slurm_limits,
        hpc_module_spider,
        hpc_storage_inspect,
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
    tools_by_name = {function.__name__: function for function in tools}
    for name in tool_names_for_preset(selected_preset):
        function = tools_by_name[name]
        if selected_preset == "slurm-job":
            function = _bind_profile(function, selected_profile, runtime)
        server.tool()(function)

    full_resources = (
        ("hpc://paths", resource_paths, "application/json"),
        ("hpc://config", resource_config, "text/plain"),
        ("hpc://submissions/active", resource_submissions_active, "application/json"),
        ("hpc://submissions/all", resource_submissions_all, "application/json"),
        ("hpc://profiles/{profile}", resource_profile, "application/json"),
        ("hpc://profiles/{profile}/hardware", resource_profile_hardware, "text/markdown"),
        ("hpc://profiles/{profile}/slurm", resource_profile_slurm, "text/markdown"),
        ("hpc://profiles/{profile}/storage", resource_profile_storage, "text/markdown"),
        ("hpc://reference-sets/{name}", resource_reference_set, "application/json"),
    )
    if selected_preset == "full":
        selected_resources = full_resources
    else:
        selected_resources = (
            (
                "hpc://runtime",
                _bind_resource(resource_runtime, selected_profile, selected_preset, runtime),
                "application/json",
            ),
            (
                "hpc://cluster/hardware",
                _bind_resource(resource_profile_hardware, selected_profile),
                "text/markdown",
            ),
            (
                "hpc://cluster/slurm",
                _bind_resource(resource_profile_slurm, selected_profile),
                "text/markdown",
            ),
            (
                "hpc://cluster/storage",
                _bind_resource(resource_profile_storage, selected_profile),
                "text/markdown",
            ),
        )
    for uri, function, mime_type in selected_resources:
        server.resource(uri, mime_type=mime_type)(function)
    return server


def _bind_resource(function: Callable[..., str], *args: str) -> Callable[[], str]:
    """Bind fixed resource arguments while preserving a useful MCP name."""

    @wraps(function)
    def bound() -> str:
        return function(*args)

    bound.__signature__ = inspect.Signature(return_annotation=str)
    return bound


def _bind_profile(
    function: Callable[..., Any],
    profile: str,
    runtime: delegation.DelegationRuntime | None = None,
) -> Callable[..., Any]:
    """Bind a restricted tool to one profile and hide profile/config inputs."""
    signature = inspect.signature(function)
    if "profile" not in signature.parameters:
        return function
    public_parameters = [
        parameter
        for name, parameter in signature.parameters.items()
        if name not in {"profile", "config"}
    ]

    @wraps(function)
    def bound(**kwargs: Any) -> Any:
        with delegation.delegation_scope(runtime):
            return function(**kwargs, profile=profile, config=None)

    bound.__signature__ = signature.replace(parameters=public_parameters)
    return bound


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
            "profile bound to the slurm-job preset; defaults to "
            f"{PROFILE_ENV_VAR} or the configured default"
        ),
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
            ).run()
    except ConfigError as error:
        print(f"hpc-mcp: {error}", file=sys.stderr)
        return 2
    return 0
