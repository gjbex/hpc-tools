from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

from hpc_tools import plugin_system, references, slurm, submissions
from hpc_tools.commands.core import _site_env_command
from hpc_tools.commands.probes import (
    _container_bundle,
    _cuda_device_properties_bundle,
    _hardware_probe_template,
    _install_bundle_command,
    _install_cuda_device_properties_command,
    _install_hardware_probe_command,
    _write_bundle_assets,
    _write_cuda_device_properties_bundle,
)
from hpc_tools.commands.remote import _module_spider_command, _storage_inspect_command
from hpc_tools.commands.slurm import build_status_report
from hpc_tools.config import ConfigError, default_config_dir, default_config_path, default_reference_sets_dir
from hpc_tools.hardware import render_hardware_context
from hpc_tools.references import resolve_reference_context
from hpc_tools.mcp.common import (
    _append_submission_event,
    _append_submission_mark_event,
    _expanded,
    _load_config,
    _probe_args,
    _profile_summary,
    _profile_to_dict,
    _reference_set_to_dict,
    _remote_mutation_result,
    _remote_read_result,
    _resolve_profile,
    _submission_record_to_dict,
    _write_preview,
)
from hpc_tools.mcp.parsers import _parse_module_spider_output, _parse_slurm_limits_output

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
        "submissions_database": str(submissions.default_database_path()),
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

def hpc_submissions_list(all: bool = False, database: str | None = None) -> dict[str, Any]:
    """List hpc-tools submission records from the local SQLite database."""
    database_path = Path(database).expanduser() if database else None
    events = submissions.read_events(database_path)
    records = submissions.records_from_events(events) if all else submissions.active_records(events)
    return {
        "database": str(database_path or submissions.default_database_path()),
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

def hpc_cancel_job(
    jobid: str,
    profile: str | None = None,
    config: str | None = None,
    cluster: str | None = None,
    reason: str | None = None,
    database: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Cancel one Slurm job and record the request; execution requires confirmation."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    selected_cluster = cluster or resolved.default_cluster
    command = slurm.cancel_command(jobid, selected_cluster)
    result = _remote_mutation_result(
        resolved,
        command,
        confirm=confirm,
        dry_run=dry_run,
    )
    database_path = Path(database).expanduser() if database else submissions.default_database_path()
    cancellation_events: list[dict[str, Any]] = []
    database_error = None
    if result["executed"] and result["returncode"] == 0:
        try:
            cancellation_events = submissions.append_cancel_requested_events(
                profile=resolved.name,
                job_id=jobid,
                cluster=selected_cluster,
                cancel_command=command,
                reason=reason,
                path=database_path,
            )
        except (OSError, ValueError) as error:
            database_error = str(error)
    return result | {
        "operation": "cancel_job",
        "jobid": jobid,
        "cluster": selected_cluster,
        "reason": reason,
        "database": str(database_path),
        "recorded_run_ids": [event["run_id"] for event in cancellation_events],
        "database_error": database_error,
    }

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
    result = _remote_read_result(resolved, command, dry_run=dry_run)
    parsed, warnings = _parse_slurm_limits_output(result["stdout"])
    return result | {"parsed": parsed, "parse_warnings": warnings}

def hpc_module_spider(
    name: str,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Search Lmod modules on the remote profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    result = _remote_read_result(resolved, _module_spider_command(name), dry_run=dry_run)
    parsed, warnings = _parse_module_spider_output(result["stdout"])
    return result | {"parsed": parsed, "parse_warnings": warnings}

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
    database: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a results_collected event to the submission database; requires confirm=true."""
    return _append_submission_mark_event(
        run_id,
        "results_collected",
        path=path,
        database=database,
        confirm=confirm,
    )

def hpc_submissions_mark_analysed(
    run_id: str,
    path: str | None = None,
    database: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append an analysed event to the submission database; requires confirm=true."""
    return _append_submission_mark_event(
        run_id,
        "analysed",
        path=path,
        database=database,
        confirm=confirm,
    )

def hpc_submissions_close(
    run_id: str,
    reason: str | None = None,
    database: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a closed event to the submission database; requires confirm=true."""
    event = submissions.mark_event(run_id, "closed", reason=reason)
    return _append_submission_event(event, database=database, confirm=confirm)

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
