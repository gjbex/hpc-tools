from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib import resources
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any

from hpc_tools import __version__, plugin_system, references, slurm, submissions
from hpc_tools.cli import (
    _container_bundle,
    _cuda_device_properties_bundle,
    _hardware_probe_template,
    _install_bundle_command,
    _install_cuda_device_properties_command,
    _install_hardware_probe_command,
    _module_spider_command,
    _quote_command as _sam_quote_command,
    _site_env_command,
    _storage_inspect_command,
    _write_bundle_assets,
    _write_cuda_device_properties_bundle,
    build_status_report,
)
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
            "Install it with `uv pip install -e '.[mcp]'` or `pip install 'hpc-tools[mcp]'`."
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


def hpc_status(
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show site status, quota, balance, and local submissions for a profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    return build_status_report(resolved, dry_run=dry_run)


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


def hpc_module_spider(
    name: str,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Search Lmod modules on the remote profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    return _remote_read_result(resolved, _module_spider_command(name), dry_run=dry_run)


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


def hpc_references_create(
    name: str,
    profile: str | None = None,
    config: str | None = None,
    force: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a reference set from the selected profile; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    destination = default_reference_sets_dir() / name
    preview = {
        "operation": "references_create",
        "name": name,
        "profile": resolved.name,
        "path": str(destination),
        "force": force,
        "confirm_required": not confirm,
    }
    if not confirm:
        return preview

    reference_set = references.create_reference_set(name, resolved, force=force)
    return preview | {
        "confirm_required": False,
        "created": True,
        "reference_set": _reference_set_to_dict(reference_set),
    }


def hpc_references_import(
    archive: str,
    force: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import a reference-set archive; requires confirm=true."""
    archive_path = Path(archive).expanduser()
    preview = {
        "operation": "references_import",
        "archive": str(archive_path),
        "reference_sets": str(default_reference_sets_dir()),
        "force": force,
        "confirm_required": not confirm,
    }
    if not confirm:
        return preview

    reference_set = references.import_reference_set(archive_path, force=force)
    return preview | {
        "confirm_required": False,
        "imported": True,
        "reference_set": _reference_set_to_dict(reference_set),
    }


def hpc_references_attach(
    name: str,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Attach an installed reference set to a profile config; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    reference_set = references.load_reference_set(name)
    config_path = Path(config).expanduser() if config else default_config_path()
    preview = {
        "operation": "references_attach",
        "name": name,
        "profile": resolved.name,
        "config": str(config_path),
        "reference_set_path": str(reference_set.path),
        "confirm_required": not confirm,
    }
    if not confirm:
        return preview

    references.set_profile_reference_set(config_path, resolved.name, name)
    return preview | {
        "confirm_required": False,
        "attached": True,
        "profile": _profile_to_dict(_resolve_profile(profile_name=resolved.name, config_path=str(config_path))),
    }


def hpc_submissions_mark_collected(
    run_id: str,
    path: str | None = None,
    log: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a results_collected event to the submission log; requires confirm=true."""
    return _append_submission_mark_event(
        run_id,
        "results_collected",
        path=path,
        log=log,
        confirm=confirm,
    )


def hpc_submissions_mark_analysed(
    run_id: str,
    path: str | None = None,
    log: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append an analysed event to the submission log; requires confirm=true."""
    return _append_submission_mark_event(
        run_id,
        "analysed",
        path=path,
        log=log,
        confirm=confirm,
    )


def hpc_submissions_close(
    run_id: str,
    reason: str | None = None,
    log: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a closed event to the submission log; requires confirm=true."""
    event = submissions.mark_event(run_id, "closed", reason=reason)
    return _append_submission_event(event, log=log, confirm=confirm)


def hpc_write_probe(
    kind: str = "hardware",
    output: str = "-",
    force: bool = False,
    account: str | None = None,
    cluster: str | None = None,
    partition: str | None = None,
    qos: str | None = None,
    cpus_per_task: str | None = None,
    time: str | None = None,
    mail_user: str | None = None,
    mail_notifications: bool = False,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate or write a local probe script or bundle; writes require confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config) if profile or config else None
    if kind == "hardware":
        probe_args = _probe_args(
            account=account,
            cluster=cluster,
            partition=partition,
            qos=qos,
            cpus_per_task=cpus_per_task,
            time=time,
            mail_user=mail_user,
            mail_notifications=mail_notifications,
        )
        contents = _hardware_probe_template(probe_args, resolved)
        preview = _write_preview("write_probe", kind, output, force, confirm) | {
            "contents": contents,
        }
        if not confirm or output == "-":
            if confirm and output == "-":
                raise ConfigError("hpc_write_probe requires an output path when confirm=true")
            return preview
        output_path = Path(output).expanduser()
        if output_path.exists() and not force:
            raise ConfigError(f"output file already exists: {output_path}; use force=true to overwrite")
        output_path.write_text(contents, encoding="utf-8")
        return preview | {"confirm_required": False, "written": True, "path": str(output_path)}

    if kind == "cuda-device-properties":
        bundle = _cuda_device_properties_bundle()
        preview = _write_preview("write_probe", kind, output, force, confirm) | {
            "files": bundle,
        }
        if output == "-":
            raise ConfigError("hpc_write_probe kind cuda-device-properties requires an output directory")
        if not confirm:
            return preview
        output_dir = Path(output).expanduser()
        _write_cuda_device_properties_bundle(output_dir, force=force)
        return preview | {"confirm_required": False, "written": True, "path": str(output_dir)}

    raise ConfigError(f"unsupported probe kind: {kind}")


def hpc_install_probe(
    directory: str,
    kind: str = "hardware",
    name: str | None = None,
    force: bool = False,
    account: str | None = None,
    cluster: str | None = None,
    partition: str | None = None,
    qos: str | None = None,
    cpus_per_task: str | None = None,
    time: str | None = None,
    mail_user: str | None = None,
    mail_notifications: bool = False,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Install a generated probe on a remote profile; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    if kind == "hardware":
        probe_args = _probe_args(
            account=account,
            cluster=cluster,
            partition=partition,
            qos=qos,
            cpus_per_task=cpus_per_task,
            time=time,
            mail_user=mail_user,
            mail_notifications=mail_notifications,
        )
        command = _install_hardware_probe_command(
            directory,
            name or "hardware-probe.slurm",
            _hardware_probe_template(probe_args, resolved),
            force=force,
        )
    elif kind == "cuda-device-properties":
        command = _install_cuda_device_properties_command(
            directory,
            name or "cuda-device-properties.slurm",
            force=force,
        )
    else:
        raise ConfigError(f"unsupported probe kind: {kind}")
    return _remote_mutation_result(resolved, command, confirm=confirm, dry_run=dry_run)


def hpc_write_container(
    output: str,
    kind: str = "generic",
    force: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate or write a local container bundle; writes require confirm=true."""
    bundle = _container_bundle(kind)
    preview = _write_preview("write_container", kind, output, force, confirm) | {
        "files": bundle,
    }
    if not confirm:
        return preview
    output_dir = Path(output).expanduser()
    _write_bundle_assets(output_dir, bundle, force=force)
    return preview | {"confirm_required": False, "written": True, "path": str(output_dir)}


def hpc_install_container(
    directory: str,
    kind: str = "generic",
    force: bool = False,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Install a generated container bundle remotely; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    command = _install_bundle_command(
        directory=directory,
        bundle=_container_bundle(kind),
        force=force,
    )
    return _remote_mutation_result(resolved, command, confirm=confirm, dry_run=dry_run)


def hpc_quote_job(
    jobscript: str,
    directory: str = ".",
    account: str | None = None,
    array: str | None = None,
    cluster: str | None = None,
    dependency: str | None = None,
    error: str | None = None,
    export: str | None = None,
    gpu_bind: str | None = None,
    gpus: str | None = None,
    gpus_per_node: str | None = None,
    gpus_per_task: str | None = None,
    gres: str | None = None,
    job_name: str | None = None,
    mem: str | None = None,
    mem_per_cpu: str | None = None,
    nodes: str | None = None,
    ntasks: str | None = None,
    ntasks_per_node: str | None = None,
    output: str | None = None,
    partition: str | None = None,
    reservation: str | None = None,
    time: str | None = None,
    cpus_per_task: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Quote a Slurm job shape before validation or submission."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    if not resolved.sam_quote_command:
        raise ConfigError(f"profile '{resolved.name}' does not define sam_quote_command")
    normalized = _submit_overrides(
        account=account,
        array=array,
        cluster=cluster,
        dependency=dependency,
        error=error,
        export=export,
        gpu_bind=gpu_bind,
        gpus=gpus,
        gpus_per_node=gpus_per_node,
        gpus_per_task=gpus_per_task,
        gres=gres,
        job_name=job_name,
        mem=mem,
        mem_per_cpu=mem_per_cpu,
        nodes=nodes,
        ntasks=ntasks,
        ntasks_per_node=ntasks_per_node,
        output=output,
        partition=partition,
        reservation=reservation,
        time=time,
        cpus_per_task=cpus_per_task,
    )
    account_value = normalized.get("account")
    if not account_value:
        raise ConfigError("hpc_quote_job requires an account")
    shape = _submission_shape(resolved, jobscript, directory, normalized)
    quote_args = _quote_args_for_submit(jobscript, normalized)
    command = _sam_quote_command(resolved.sam_quote_command, quote_args)
    result = _remote_read_result(resolved, command, dry_run=dry_run)
    evidence = _submission_evidence("quote", shape, result)
    return result | {
        "resource_shape": shape,
        "quote_evidence": evidence,
    }


def hpc_validate_job(
    jobscript: str,
    directory: str = ".",
    account: str | None = None,
    array: str | None = None,
    cluster: str | None = None,
    dependency: str | None = None,
    error: str | None = None,
    export: str | None = None,
    gpu_bind: str | None = None,
    gpus: str | None = None,
    gpus_per_node: str | None = None,
    gpus_per_task: str | None = None,
    gres: str | None = None,
    job_name: str | None = None,
    mem: str | None = None,
    mem_per_cpu: str | None = None,
    nodes: str | None = None,
    ntasks: str | None = None,
    ntasks_per_node: str | None = None,
    output: str | None = None,
    partition: str | None = None,
    reservation: str | None = None,
    time: str | None = None,
    cpus_per_task: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate a Slurm job with sbatch --test-only before submission."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    normalized = _submit_overrides(
        account=account,
        array=array,
        cluster=cluster,
        dependency=dependency,
        error=error,
        export=export,
        gpu_bind=gpu_bind,
        gpus=gpus,
        gpus_per_node=gpus_per_node,
        gpus_per_task=gpus_per_task,
        gres=gres,
        job_name=job_name,
        mem=mem,
        mem_per_cpu=mem_per_cpu,
        nodes=nodes,
        ntasks=ntasks,
        ntasks_per_node=ntasks_per_node,
        output=output,
        partition=partition,
        reservation=reservation,
        time=time,
        cpus_per_task=cpus_per_task,
    )
    shape = _submission_shape(resolved, jobscript, directory, normalized)
    command = slurm.submit_command(
        jobscript,
        directory=directory,
        test_only=True,
        overrides=normalized,
    )
    result = _remote_read_result(resolved, command, dry_run=dry_run)
    evidence = _submission_evidence("validation", shape, result)
    return result | {
        "resource_shape": shape,
        "validation_evidence": evidence,
    }


def hpc_submit_job(
    jobscript: str,
    directory: str,
    quote_evidence: dict[str, Any],
    validation_evidence: dict[str, Any],
    account: str | None = None,
    array: str | None = None,
    cluster: str | None = None,
    dependency: str | None = None,
    error: str | None = None,
    export: str | None = None,
    gpu_bind: str | None = None,
    gpus: str | None = None,
    gpus_per_node: str | None = None,
    gpus_per_task: str | None = None,
    gres: str | None = None,
    job_name: str | None = None,
    mem: str | None = None,
    mem_per_cpu: str | None = None,
    nodes: str | None = None,
    ntasks: str | None = None,
    ntasks_per_node: str | None = None,
    output: str | None = None,
    partition: str | None = None,
    reservation: str | None = None,
    time: str | None = None,
    cpus_per_task: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Submit a Slurm job only when matching quote and validation evidence is supplied."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    normalized = _submit_overrides(
        account=account,
        array=array,
        cluster=cluster,
        dependency=dependency,
        error=error,
        export=export,
        gpu_bind=gpu_bind,
        gpus=gpus,
        gpus_per_node=gpus_per_node,
        gpus_per_task=gpus_per_task,
        gres=gres,
        job_name=job_name,
        mem=mem,
        mem_per_cpu=mem_per_cpu,
        nodes=nodes,
        ntasks=ntasks,
        ntasks_per_node=ntasks_per_node,
        output=output,
        partition=partition,
        reservation=reservation,
        time=time,
        cpus_per_task=cpus_per_task,
    )
    shape = _submission_shape(resolved, jobscript, directory, normalized)
    _require_evidence("quote", quote_evidence, shape)
    _require_evidence("validation", validation_evidence, shape)
    command = slurm.submit_command(
        jobscript,
        directory=directory,
        test_only=False,
        overrides=normalized,
    )
    preview = {
        "profile": resolved.name,
        "command": command,
        "ssh_command": format_command(build_ssh_argv(resolved, command)),
        "resource_shape": shape,
        "confirm_required": not confirm,
        "dry_run": dry_run,
        "executed": False,
        "logged": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
    if not confirm or dry_run:
        return preview

    completed = run_remote_capture(resolved, command)
    stdout = completed.stdout
    stderr = completed.stderr
    logged = False
    submission_event = None
    if completed.returncode == 0:
        job_id, cluster = submissions.parse_sbatch_submission(stdout + stderr)
        submission_event = submissions.submitted_event(
            profile=resolved.name,
            job_id=job_id,
            cluster=cluster or normalized.get("cluster") or resolved.default_cluster,
            remote_directory=directory,
            jobscript=jobscript,
            submit_command=command,
            overrides=normalized,
        )
        submissions.append_event(submission_event)
        logged = True
    return preview | {
        "confirm_required": False,
        "executed": True,
        "logged": logged,
        "submission_event": submission_event,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


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


def _remote_mutation_result(
    profile: Profile,
    command: str,
    *,
    confirm: bool,
    dry_run: bool,
) -> dict[str, Any]:
    ssh_argv = build_ssh_argv(profile, command)
    preview = {
        "profile": profile.name,
        "command": command,
        "ssh_command": format_command(ssh_argv),
        "confirm_required": not confirm,
        "dry_run": dry_run,
        "executed": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
    if not confirm or dry_run:
        return preview

    completed = run_remote_capture(profile, command)
    return preview | {
        "confirm_required": False,
        "executed": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _append_submission_mark_event(
    run_id: str,
    event_name: str,
    *,
    path: str | None,
    log: str | None,
    confirm: bool,
) -> dict[str, Any]:
    event = submissions.mark_event(run_id, event_name, path=path)
    return _append_submission_event(event, log=log, confirm=confirm)


def _append_submission_event(
    event: dict[str, Any],
    *,
    log: str | None,
    confirm: bool,
) -> dict[str, Any]:
    log_path = Path(log).expanduser() if log else submissions.default_log_path()
    preview = {
        "operation": event["event"],
        "log": str(log_path),
        "event": event,
        "confirm_required": not confirm,
    }
    if not confirm:
        return preview

    submissions.append_event(event, path=log_path)
    return preview | {
        "confirm_required": False,
        "appended": True,
    }


def _write_preview(
    operation: str,
    kind: str,
    output: str,
    force: bool,
    confirm: bool,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "kind": kind,
        "output": output,
        "force": force,
        "confirm_required": not confirm,
    }


def _probe_args(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def _submit_overrides(account: str | None = None, **overrides: str | None) -> dict[str, str | None]:
    normalized = {name: overrides.get(name) for name in slurm.SUBMIT_OPTION_NAMES}
    if account is not None:
        normalized["account"] = account
    unknown = sorted(set(overrides) - set(slurm.SUBMIT_OPTION_NAMES))
    if unknown:
        raise ConfigError(f"unsupported submit override(s): {', '.join(unknown)}")
    return normalized


def _quote_args_for_submit(jobscript: str, overrides: dict[str, str | None]) -> list[str]:
    parts = ["sbatch"]
    for name, value in overrides.items():
        if value is None:
            continue
        parts.extend([slurm.SUBMIT_OPTION_NAMES[name], value])
    parts.append(jobscript)
    return parts


def _submission_shape(
    profile: Profile,
    jobscript: str,
    directory: str,
    overrides: dict[str, str | None],
) -> dict[str, Any]:
    filtered_overrides = {
        key: value
        for key, value in overrides.items()
        if value is not None
    }
    shape = {
        "profile": profile.name,
        "account": filtered_overrides.get("account"),
        "jobscript": jobscript,
        "directory": directory,
        "overrides": filtered_overrides,
    }
    shape["shape_token"] = _shape_token(shape)
    return shape


def _shape_token(shape: dict[str, Any]) -> str:
    token_shape = {key: value for key, value in shape.items() if key != "shape_token"}
    encoded = json.dumps(token_shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _submission_evidence(
    evidence_type: str,
    shape: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    evidence = {
        "type": evidence_type,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": shape["profile"],
        "account": shape["account"],
        "jobscript": shape["jobscript"],
        "directory": shape["directory"],
        "overrides": shape["overrides"],
        "shape_token": shape["shape_token"],
        "command": result["command"],
        "ssh_command": result["ssh_command"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "dry_run": result["dry_run"],
    }
    evidence["ok"] = evidence["returncode"] == 0
    evidence["evidence_token"] = _evidence_token(evidence)
    return evidence


def _evidence_token(evidence: dict[str, Any]) -> str:
    token_evidence = {
        key: value
        for key, value in evidence.items()
        if key != "evidence_token"
    }
    encoded = json.dumps(token_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_evidence(
    evidence_type: str,
    evidence: dict[str, Any],
    shape: dict[str, Any],
) -> None:
    if not isinstance(evidence, dict):
        raise ConfigError(f"{evidence_type} evidence must be an object")
    if evidence.get("type") != evidence_type:
        raise ConfigError(f"expected {evidence_type} evidence")
    if evidence.get("shape_token") != shape["shape_token"]:
        raise ConfigError(
            f"{evidence_type} evidence is stale for this resource shape; quote and validate again"
        )
    if evidence.get("returncode") != 0 or not evidence.get("ok"):
        raise ConfigError(f"{evidence_type} evidence did not succeed")
    if evidence.get("dry_run"):
        raise ConfigError(f"{evidence_type} evidence came from a dry run")
    if evidence.get("evidence_token") != _evidence_token(evidence):
        raise ConfigError(f"{evidence_type} evidence token is invalid")


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
