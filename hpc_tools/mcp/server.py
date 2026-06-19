from __future__ import annotations

import sys

from hpc_tools.config import ConfigError
from hpc_tools.mcp.resources import (
    resource_config,
    resource_paths,
    resource_profile,
    resource_profile_hardware,
    resource_profile_slurm,
    resource_profile_storage,
    resource_reference_set,
    resource_submissions_active,
    resource_submissions_all,
)
from hpc_tools.mcp.submit import hpc_quote_job, hpc_submit_job, hpc_validate_job
from hpc_tools.mcp.tools import (
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
    "hpc_status",
    "hpc_jobs",
    "hpc_job",
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
    """Create the FastMCP server for hpc-tools guarded agent tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover - depends on optional extra.
        raise ConfigError(
            "hpc-mcp requires the optional MCP dependency. "
            "Install it with `uv pip install -e '.[mcp]'` or `pip install 'hpc-tools[mcp]'."
        ) from error

    server = FastMCP(
        "hpc-tools",
        instructions=(
            "Guarded hpc-tools interface for agents. This server exposes "
            "profile, reference, plugin, Slurm-inspection, submission-log, "
            "and explicit confirm-gated local write and remote install tools. "
            "Slurm job submission is exposed only through quote, validation, "
            "and confirm-gated submit tools with matching evidence."
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
        hpc_status,
        hpc_jobs,
        hpc_job,
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
