from __future__ import annotations

import base64
from importlib import resources
from pathlib import Path
from typing import Any

from hpc_tools import delegation, plugin_system, references, slurm, submissions
from hpc_tools.commands.core import _site_env_command
from hpc_tools.commands.probes import (
    _container_bundle,
    _cuda_device_properties_bundle,
    _hardware_probe_template,
    _write_bundle_assets,
    _write_cuda_device_properties_bundle,
)
from hpc_tools.commands.remote import (
    _module_spider_command,
    clone_plan,
    prepare_clone_destination,
)
from hpc_tools.commands.slurm import build_site_status_report
from hpc_tools.config import (
    ConfigError,
    default_config_dir,
    default_config_path,
    default_reference_sets_dir,
)
from hpc_tools.hardware import render_hardware_context
from hpc_tools.execution import execution_plan, run_command_capture
from hpc_tools.filesystem import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_TRANSFER_BYTES,
    FilesystemLimits,
    FilesystemService,
)
from hpc_tools.mcp.common import (
    _append_submission_event,
    _append_submission_mark_event,
    _authorize_mcp,
    _bound_database,
    current_mcp_binding,
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
from hpc_tools.mcp.parsers import (
    _parse_module_spider_output,
    _parse_slurm_limits_output,
)
from hpc_tools.references import resolve_reference_context
from hpc_tools.remote_filesystem import (
    copy_remote_file,
    install_remote_assets,
    list_remote_directory,
    make_remote_directory,
    plan_remote_assets,
    read_local_regular_file,
    read_remote_file,
    remove_remote_path,
    resolve_granted_path,
    write_local_regular_file,
    write_remote_file,
)


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
    _authorize_mcp(resolved, "profiles.show", {"profile": profile, "config": config})
    return _profile_to_dict(resolved)

def hpc_hardware_context(profile: str | None = None, config: str | None = None) -> dict[str, Any]:
    """Render configured hardware, Slurm, and storage reference context for a profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "references.context", {"profile": profile, "config": config})
    return {
        "profile": resolved.name,
        "context": render_hardware_context(resolved),
    }

def hpc_hardware_sources(profile: str | None = None, config: str | None = None) -> dict[str, Any]:
    """Return structured hardware, Slurm, storage, and status source metadata."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "references.sources", {
        "profile": profile,
        "config": config,
    })
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
    binding = current_mcp_binding()
    if binding is not None:
        names = (binding.profile.reference_set,) if binding.profile.reference_set else ()
        return {
            "reference_sets": [
                _reference_set_to_dict(references.load_reference_set(name))
                for name in names
            ]
        }
    return {
        "reference_sets": [
            _reference_set_to_dict(reference_set)
            for reference_set in references.list_reference_sets()
        ]
    }

def hpc_references_show(name: str) -> dict[str, Any]:
    """Show one installed hpc-tools reference set."""
    binding = current_mcp_binding()
    if binding is not None and name != binding.profile.reference_set:
        raise ConfigError(
            "the MCP server can only read the selected profile's effective reference set"
        )
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

def hpc_submissions_list(
    all: bool = False,
    database: str | None = None,
    profile: str | None = None,
    config: str | None = None,
) -> dict[str, Any]:
    """List hpc-tools submission records from the local SQLite database."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "submissions.list", {
        "all": all,
        "database": database,
        "profile": profile,
        "config": config,
    })
    database_path = _bound_database(database)
    events = submissions.read_events(database_path)
    records = (
        submissions.records_from_events(events, profile=resolved.name)
        if all
        else submissions.active_records(events, profile=resolved.name)
    )
    return {
        "database": str(database_path),
        "profile": resolved.name,
        "all": all,
        "submissions": [_submission_record_to_dict(record) for record in records],
    }

def hpc_status(
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show the public site status page for a profile."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "cluster.status", {
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    })
    return build_site_status_report(resolved, dry_run=dry_run)

def hpc_jobs(
    profile: str | None = None,
    config: str | None = None,
    cluster: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show jobs, restricted to active jobs owned by the current delegation."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "job.list", {
        "profile": profile,
        "config": config,
        "cluster": cluster,
        "dry_run": dry_run,
    })
    runtime = delegation.current_runtime()
    if runtime is None:
        command = slurm.squeue_user_command(cluster)
        return _remote_read_result(resolved, command, dry_run=dry_run)

    ledger = delegation.DelegationLedger(runtime.ledger_path)
    all_owned = ledger.owned_jobs(runtime.manifest)
    owned = all_owned
    if cluster != "all":
        if cluster not in runtime.manifest.allowed["clusters"]:
            raise delegation.DelegationError(
                f"cluster {cluster!r} is outside the delegation"
            )
        owned = [job for job in owned if job["cluster"] == cluster]
    grouped: dict[str, list[str]] = {}
    for job in owned:
        grouped.setdefault(job["cluster"], []).append(job["job_id"])
    queries = []
    queued: set[tuple[str, str]] = set()
    for selected_cluster, job_ids in sorted(grouped.items()):
        command = slurm.squeue_jobs_command(job_ids, selected_cluster or None)
        query = _remote_read_result(resolved, command, dry_run=dry_run)
        queries.append(query)
        if not dry_run and query["returncode"] == 0:
            for line in query["stdout"].splitlines():
                token = line.split(maxsplit=1)[0] if line.split() else ""
                try:
                    base_job_id = delegation.normalize_job_id(token)
                except delegation.DelegationError:
                    continue
                queued.add((selected_cluster, base_job_id))

    reconciliation_queries: list[dict[str, Any]] = []
    reconciliation_complete = False
    controller = ledger.controller_summary(runtime.manifest)
    if not dry_run and controller["reconciliation_required"]:
        unresolved: list[dict[str, str]] = []
        for job in owned:
            identity = (job["cluster"], job["job_id"])
            if identity in queued:
                continue
            result = _remote_read_result(
                resolved,
                slurm.sacct_command(job["job_id"], job["cluster"] or None),
                dry_run=False,
            )
            reconciliation_queries.append(result)
            if result["returncode"] != 0:
                unresolved.append(job)
                continue
            state, _, _ = submissions.parse_sacct_observation(
                result["stdout"], job["job_id"]
            )
            if state == "UNKNOWN":
                unresolved.append(job)
                continue
            ledger.reconcile_job(
                runtime.manifest,
                job_id=job["job_id"],
                cluster=job["cluster"] or None,
                state=state,
            )
        complete_scope = len(owned) == len(all_owned)
        if (
            complete_scope
            and not unresolved
            and all(query["returncode"] == 0 for query in queries)
        ):
            ledger.complete_reconciliation(runtime.manifest)
            reconciliation_complete = True
    return {
        "profile": resolved.name,
        "delegation_id": runtime.manifest.identifier,
        "cluster": cluster,
        "owned_job_ids": [
            {"job_id": job["job_id"], "cluster": job["cluster"]}
            for job in owned
        ],
        "queries": queries,
        "reconciliation_queries": reconciliation_queries,
        "reconciliation_complete": reconciliation_complete,
        "dry_run": dry_run,
    }


def _delegated_job_context(
    resolved: Any,
    *,
    jobid: str,
    cluster: str | None,
) -> tuple[delegation.DelegationRuntime | None, str | None]:
    runtime = delegation.current_runtime()
    selected_cluster = cluster or resolved.default_cluster
    if runtime is not None:
        if not selected_cluster or selected_cluster == "all":
            selected_cluster = resolved.default_cluster
        if not selected_cluster:
            raise delegation.DelegationError(
                "restricted job operation requires one explicit cluster"
            )
        delegation.DelegationLedger(runtime.ledger_path).require_ownership(
            runtime.manifest,
            job_id=jobid,
            cluster=selected_cluster,
        )
    return runtime, selected_cluster


def hpc_job(
    jobid: str,
    profile: str | None = None,
    config: str | None = None,
    cluster: str = "all",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show Slurm queue status for one authorized job ID."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "job.show", {
        "jobid": jobid,
        "profile": profile,
        "config": config,
        "cluster": cluster,
        "dry_run": dry_run,
    })
    runtime, selected_cluster = _delegated_job_context(
        resolved, jobid=jobid, cluster=cluster
    )
    command = slurm.squeue_job_command(jobid, selected_cluster)
    result = _remote_read_result(resolved, command, dry_run=dry_run)
    return result | {
        "delegation_id": runtime.manifest.identifier if runtime else None,
        "owned": runtime is not None,
    }


def hpc_job_accounting(
    jobid: str,
    profile: str | None = None,
    config: str | None = None,
    cluster: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Show Slurm accounting for one authorized job and reconcile terminal state."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "job.accounting", {
        "jobid": jobid,
        "profile": profile,
        "config": config,
        "cluster": cluster,
        "dry_run": dry_run,
    })
    runtime, selected_cluster = _delegated_job_context(
        resolved, jobid=jobid, cluster=cluster
    )
    result = _remote_read_result(
        resolved,
        slurm.sacct_command(jobid, selected_cluster),
        dry_run=dry_run,
    )
    state = "UNKNOWN"
    exit_code = None
    elapsed = None
    ledger_reconciled = False
    ledger_error = None
    if not dry_run and result["returncode"] == 0:
        state, exit_code, elapsed = submissions.parse_sacct_observation(
            result["stdout"], delegation.normalize_job_id(jobid)
        )
        if runtime is not None and state != "UNKNOWN":
            try:
                delegation.DelegationLedger(runtime.ledger_path).reconcile_job(
                    runtime.manifest,
                    job_id=jobid,
                    cluster=selected_cluster,
                    state=state,
                )
                ledger_reconciled = True
            except delegation.DelegationError as error:
                ledger_error = str(error)
    return result | {
        "operation": "job_accounting",
        "delegation_id": runtime.manifest.identifier if runtime else None,
        "owned": runtime is not None,
        "jobid": jobid,
        "cluster": selected_cluster,
        "state": state,
        "exit_code": exit_code,
        "elapsed": elapsed,
        "ledger_reconciled": ledger_reconciled,
        "ledger_error": ledger_error,
    }


def hpc_cancel_job(
    jobid: str,
    profile: str | None = None,
    config: str | None = None,
    cluster: str | None = None,
    reason: str | None = None,
    database: str | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Cancel one authorized Slurm job and record the request."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "job.cancel", {
        "jobid": jobid,
        "profile": profile,
        "config": config,
        "cluster": cluster,
        "reason": reason,
        "database": database,
        "idempotency_key": idempotency_key,
        "dry_run": dry_run,
        "confirm": confirm,
    })
    runtime, selected_cluster = _delegated_job_context(
        resolved, jobid=jobid, cluster=cluster
    )
    command = slurm.cancel_command(jobid, selected_cluster)
    ledger = None
    reservation = None
    if runtime is not None and not dry_run:
        if not idempotency_key:
            raise delegation.DelegationError(
                "restricted cancellation requires an idempotency_key"
            )
        ledger = delegation.DelegationLedger(runtime.ledger_path)
        reservation = ledger.reserve_lifecycle_operation(
            runtime.manifest,
            idempotency_key=idempotency_key,
            operation="cancel",
            job_id=jobid,
            cluster=selected_cluster,
        )
        if reservation["idempotent_replay"]:
            if reservation["status"] == "succeeded":
                previous = reservation["result"] or {}
                return previous | {
                    "idempotent_replay": True,
                    "executed": False,
                    "ledger_recorded": True,
                }
            raise delegation.DelegationError(
                f"idempotent cancellation is in {reservation['status']!r} state; "
                "use a new key after failure or reconcile a reserved operation"
            )

    result = _remote_mutation_result(
        resolved,
        command,
        confirm=(confirm or runtime is not None),
        dry_run=dry_run,
    )
    ledger_error = None
    ledger_recovery_error = None
    ledger_status = "not_applicable" if runtime is None else "not_executed"
    ledger_recorded = runtime is None
    if ledger is not None and idempotency_key is not None and result["executed"]:
        lifecycle_result = {
            "operation": "cancel_job",
            "jobid": jobid,
            "cluster": selected_cluster,
            "returncode": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
        try:
            ledger.record_lifecycle_result(
                runtime.manifest,
                idempotency_key=idempotency_key,
                succeeded=result["returncode"] == 0,
                result=lifecycle_result,
            )
            ledger_recorded = True
            ledger_status = "succeeded" if result["returncode"] == 0 else "failed"
        except delegation.DelegationError as error:
            ledger_error = str(error)
            try:
                ledger.record_accepted_lifecycle_uncertain(
                    runtime.manifest,
                    idempotency_key=idempotency_key,
                    result=lifecycle_result,
                    reason=ledger_error,
                )
                ledger_recorded = True
                ledger_status = "uncertain"
            except delegation.DelegationError as recovery_error:
                ledger_recovery_error = str(recovery_error)
                ledger_status = "unrecorded"

    database_path = _bound_database(database)
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
    response = result | {
        "operation": "cancel_job",
        "delegation_id": runtime.manifest.identifier if runtime else None,
        "owned": runtime is not None,
        "jobid": jobid,
        "cluster": selected_cluster,
        "reason": reason,
        "database": str(database_path),
        "recorded_run_ids": [event["run_id"] for event in cancellation_events],
        "database_error": database_error,
        "idempotent_replay": False,
        "ledger_recorded": ledger_recorded,
        "ledger_status": ledger_status,
        "ledger_error": ledger_error,
        "ledger_recovery_error": ledger_recovery_error,
    }
    return response

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
    _authorize_mcp(resolved, "cluster.limits", {
        "profile": profile,
        "config": config,
        "cluster": cluster,
        "partition": partition,
        "qos": qos,
        "dry_run": dry_run,
    })
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
    _authorize_mcp(resolved, "cluster.modules", {
        "name": name,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    })
    result = _remote_read_result(resolved, _module_spider_command(name), dry_run=dry_run)
    parsed, warnings = _parse_module_spider_output(result["stdout"])
    return result | {"parsed": parsed, "parse_warnings": warnings}

def hpc_storage_inspect(
    profile: str | None = None,
    config: str | None = None,
    path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect one remote filesystem path with bounded read-only checks."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "filesystem.inspect", {
        "profile": profile,
        "config": config,
        "path": path,
        "dry_run": dry_run,
    })
    selected_path = resolved.projects_dir if path in {None, "."} else path
    if not selected_path:
        raise ConfigError(
            f"profile '{resolved.name}' does not define projects_dir; pass path"
        )
    if dry_run:
        return {
            "profile": resolved.name,
            "path": selected_path,
            "dry_run": True,
            "entries": [],
            "truncated": False,
        }
    selected, entries, truncated = list_remote_directory(
        resolved,
        selected_path,
        roots=resolved.capabilities.remote_roots.list,
    )
    return {
        "profile": resolved.name,
        "path": selected,
        "dry_run": False,
        "entries": [
            {
                "name": entry.name,
                "kind": entry.kind,
                "size": entry.size,
                "mode": entry.mode,
            }
            for entry in entries
        ],
        "truncated": truncated,
    }


def hpc_files_list(
    path: str,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """List one remote directory without recursion or symlink traversal."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = {
        "path": path,
        "max_entries": max_entries,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    }
    _authorize_mcp(resolved, "filesystem.list", arguments)
    maximum = _bounded_limit(max_entries, DEFAULT_MAX_ENTRIES, "max_entries")
    selected, _ = resolve_granted_path(path, resolved.capabilities.remote_roots.list)
    preview = {
        "operation": "files_list",
        "profile": resolved.name,
        "path": selected,
        "max_entries": maximum,
        "dry_run": dry_run,
        "entries": [],
        "truncated": False,
    }
    if dry_run:
        return preview
    selected, entries, truncated = list_remote_directory(
        resolved,
        path,
        roots=resolved.capabilities.remote_roots.list,
        service=_filesystem_service(resolved, max_bytes=DEFAULT_MAX_BYTES, max_entries=maximum),
    )
    return preview | {
        "path": selected,
        "dry_run": False,
        "entries": [entry.__dict__ for entry in entries],
        "truncated": truncated,
    }


def hpc_files_read(
    path: str,
    encoding: str = "utf-8",
    max_bytes: int = DEFAULT_MAX_BYTES,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read one bounded remote regular file as UTF-8 text or base64."""
    if encoding not in {"utf-8", "base64"}:
        raise ConfigError("encoding must be 'utf-8' or 'base64'")
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = {
        "path": path,
        "encoding": encoding,
        "max_bytes": max_bytes,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    }
    _authorize_mcp(resolved, "filesystem.read", arguments)
    maximum = _bounded_limit(max_bytes, DEFAULT_MAX_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(path, resolved.capabilities.remote_roots.read)
    preview = {
        "operation": "files_read",
        "profile": resolved.name,
        "path": selected,
        "encoding": encoding,
        "max_bytes": maximum,
        "dry_run": dry_run,
        "size": None,
        "truncated": False,
        "content": "",
    }
    if dry_run:
        return preview
    remote = read_remote_file(
        resolved,
        path,
        roots=resolved.capabilities.remote_roots.read,
        service=_filesystem_service(resolved, max_bytes=maximum),
    )
    if encoding == "base64":
        content = base64.b64encode(remote.data).decode("ascii")
    else:
        try:
            content = remote.data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ConfigError("remote file is not valid UTF-8; use encoding='base64'") from error
    return preview | {
        "dry_run": False,
        "size": remote.size,
        "truncated": remote.truncated,
        "content": content,
    }


def hpc_files_download(
    source: str,
    output: str,
    force: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Download one remote file; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "filesystem.download", arguments)
    maximum = _bounded_limit(max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(source, resolved.capabilities.remote_roots.read)
    preview = _file_mutation_preview(
        "files_download", resolved.name, dry_run, confirm,
        source=selected, destination=str(Path(output).expanduser()), force=force,
        max_bytes=maximum,
    )
    if dry_run or not confirm:
        return preview
    remote = read_remote_file(
        resolved,
        source,
        roots=resolved.capabilities.remote_roots.read,
        service=_filesystem_service(resolved, max_bytes=maximum),
    )
    if remote.truncated:
        raise ConfigError(f"remote file exceeds the transfer limit of {maximum} bytes")
    destination, overwritten = write_local_regular_file(
        output, remote.data, overwrite=force, max_bytes=maximum
    )
    return preview | {
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
        "destination": str(destination),
        "size": remote.size,
        "overwritten": overwritten,
    }


def hpc_files_upload(
    source: str,
    destination: str,
    force: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload one local file; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "filesystem.upload", arguments)
    maximum = _bounded_limit(max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    selected, _ = resolve_granted_path(destination, resolved.capabilities.remote_roots.write)
    preview = _file_mutation_preview(
        "files_upload", resolved.name, dry_run, confirm,
        source=str(Path(source).expanduser()), destination=selected, force=force,
        max_bytes=maximum,
    )
    if dry_run or not confirm:
        return preview
    local_source, data = read_local_regular_file(source, max_bytes=maximum)
    result = write_remote_file(
        resolved,
        destination,
        data,
        roots=resolved.capabilities.remote_roots.write,
        overwrite=force,
        service=_filesystem_service(resolved, max_bytes=maximum),
    )
    return preview | {
        "source": str(local_source),
        "destination": result.destination,
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
        "size": result.size,
        "overwritten": result.overwritten,
    }


def hpc_files_copy(
    source: str,
    destination: str,
    force: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSFER_BYTES,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Copy one remote file; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "filesystem.copy", arguments)
    maximum = _bounded_limit(max_bytes, DEFAULT_MAX_TRANSFER_BYTES, "max_bytes")
    selected_source, _ = resolve_granted_path(source, resolved.capabilities.remote_roots.read)
    selected_destination, _ = resolve_granted_path(
        destination, resolved.capabilities.remote_roots.write
    )
    preview = _file_mutation_preview(
        "files_copy", resolved.name, dry_run, confirm,
        source=selected_source, destination=selected_destination, force=force,
        max_bytes=maximum,
    )
    if dry_run or not confirm:
        return preview
    result = copy_remote_file(
        resolved,
        source,
        destination,
        read_roots=resolved.capabilities.remote_roots.read,
        write_roots=resolved.capabilities.remote_roots.write,
        overwrite=force,
        service=_filesystem_service(resolved, max_bytes=maximum),
    )
    return preview | {
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
        "size": result.size,
        "overwritten": result.overwritten,
    }


def hpc_files_mkdir(
    path: str,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create one remote directory; execution requires confirm=true and dry_run=false."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "filesystem.mkdir", arguments)
    selected, _ = resolve_granted_path(path, resolved.capabilities.remote_roots.write)
    preview = _file_mutation_preview(
        "files_mkdir", resolved.name, dry_run, confirm, path=selected
    )
    if dry_run or not confirm:
        return preview
    created = make_remote_directory(
        resolved, path, roots=resolved.capabilities.remote_roots.write
    )
    return preview | {
        "path": created,
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
    }


def hpc_files_remove(
    path: str,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Remove one remote file or empty directory; requires confirmation."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "filesystem.remove", arguments)
    selected, root = resolve_granted_path(path, resolved.capabilities.remote_roots.delete)
    if selected == root:
        raise ConfigError("refusing to remove a configured remote root")
    preview = _file_mutation_preview(
        "files_remove", resolved.name, dry_run, confirm, path=selected
    )
    if dry_run or not confirm:
        return preview
    removed, kind = remove_remote_path(
        resolved, path, roots=resolved.capabilities.remote_roots.delete
    )
    return preview | {
        "path": removed,
        "kind": kind,
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
    }


def hpc_repo_clone(
    url: str,
    directory: str | None = None,
    name: str | None = None,
    branch: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Clone a network Git repository; requires confirmation and no submodules."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    arguments = locals().copy()
    _authorize_mcp(resolved, "repository.clone", arguments)
    selected_directory, destination_name, command = clone_plan(
        resolved, url, directory=directory, name=name, branch=branch
    )
    plan = execution_plan(resolved, command)
    preview = {
        "operation": "repo_clone",
        "profile": resolved.name,
        "url": url,
        "directory": selected_directory,
        "name": destination_name,
        "branch": branch,
        "command": command,
        **plan.metadata(),
        "dry_run": dry_run,
        "confirm_required": not confirm,
        "executed": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
    if dry_run or not confirm:
        return preview
    prepare_clone_destination(resolved, selected_directory, destination_name)
    completed = run_command_capture(resolved, command)
    return preview | {
        "dry_run": False,
        "confirm_required": False,
        "executed": True,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _bounded_limit(requested: int, maximum: int, name: str) -> int:
    if type(requested) is not int or requested <= 0 or requested > maximum:
        raise ConfigError(f"{name} must be between 1 and {maximum}")
    return requested


def _filesystem_service(
    profile: Any,
    *,
    max_bytes: int,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> FilesystemService:
    return FilesystemService(
        profile,
        limits=FilesystemLimits(
            max_bytes=max_bytes,
            max_entries=max_entries,
            max_transfer_bytes=max_bytes,
        ),
    )


def _file_mutation_preview(
    operation: str,
    profile: str,
    dry_run: bool,
    confirm: bool,
    **details: Any,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "profile": profile,
        **details,
        "dry_run": dry_run,
        "confirm_required": not confirm,
        "executed": False,
    }

def hpc_site_env(
    profile: str | None = None,
    config: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect remote site environment variables and common HPC helper tools."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "cluster.site-env", {
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    })
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
    _authorize_mcp(resolved, "references.create", {
        "name": name,
        "profile": profile,
        "config": config,
        "force": force,
        "confirm": confirm,
    })
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
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import a reference-set archive; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "references.import", {
        "archive": archive,
        "force": force,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
    archive_path = Path(archive).expanduser()
    preview = {
        "operation": "references_import",
        "archive": str(archive_path),
        "reference_sets": str(default_reference_sets_dir()),
        "profile": resolved.name,
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
    _authorize_mcp(resolved, "references.attach", {
        "name": name,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
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
        "profile": _profile_summary(
            _resolve_profile(profile_name=resolved.name, config_path=str(config_path))
        ),
    }

def hpc_submissions_mark_collected(
    run_id: str,
    path: str | None = None,
    database: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a results_collected event to the submission database; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "submissions.mark-collected", {
        "run_id": run_id,
        "path": path,
        "database": database,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
    return _append_submission_mark_event(
        run_id,
        "results_collected",
        profile=resolved,
        path=path,
        database=database,
        confirm=confirm,
    )

def hpc_submissions_mark_analysed(
    run_id: str,
    path: str | None = None,
    database: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append an analysed event to the submission database; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "submissions.mark-analysed", {
        "run_id": run_id,
        "path": path,
        "database": database,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
    return _append_submission_mark_event(
        run_id,
        "analysed",
        profile=resolved,
        path=path,
        database=database,
        confirm=confirm,
    )

def hpc_submissions_close(
    run_id: str,
    reason: str | None = None,
    database: str | None = None,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Append a closed event to the submission database; requires confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "submissions.close", {
        "run_id": run_id,
        "reason": reason,
        "database": database,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
    database_path = Path(database).expanduser() if database else submissions.default_database_path()
    submissions.require_record_for_profile(
        submissions.read_events(database_path),
        run_id=run_id,
        profile=resolved.name,
    )
    event = submissions.mark_event(
        run_id,
        "closed",
        profile=resolved.name,
        reason=reason,
    )
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
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "probe.write", {
        "kind": kind,
        "output": output,
        "force": force,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
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
    _authorize_mcp(resolved, "probe.install", {
        "directory": directory,
        "kind": kind,
        "name": name,
        "force": force,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
        "confirm": confirm,
    })
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
        assets = {
            name or "hardware-probe.slurm": _hardware_probe_template(probe_args, resolved),
        }
    elif kind == "cuda-device-properties":
        bundle = _cuda_device_properties_bundle()
        assets = {
            name or "cuda-device-properties.slurm": bundle["cuda-device-properties.slurm"],
            "cuda/CMakeLists.txt": bundle["cuda/CMakeLists.txt"],
            "cuda/device_properties.cu": bundle["cuda/device_properties.cu"],
        }
    else:
        raise ConfigError(f"unsupported probe kind: {kind}")
    planned = plan_remote_assets(
        directory,
        assets,
        roots=resolved.capabilities.remote_roots.install,
    )
    preview = {
        "operation": "install_probe",
        "profile": resolved.name,
        "directory": directory,
        "files": [asset.relative_path for asset in planned],
        "force": force,
        "confirm_required": not confirm,
        "dry_run": dry_run,
        "executed": False,
    }
    if not confirm or dry_run:
        return preview
    installed = install_remote_assets(
        resolved,
        directory,
        assets,
        roots=resolved.capabilities.remote_roots.install,
        overwrite=force,
    )
    return preview | {
        "confirm_required": False,
        "executed": True,
        "installed": [asset.__dict__ for asset in installed],
    }

def hpc_write_container(
    output: str,
    kind: str = "generic",
    force: bool = False,
    profile: str | None = None,
    config: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Generate or write a local container bundle; writes require confirm=true."""
    resolved = _resolve_profile(profile_name=profile, config_path=config)
    _authorize_mcp(resolved, "container.write", {
        "output": output,
        "kind": kind,
        "force": force,
        "profile": profile,
        "config": config,
        "confirm": confirm,
    })
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
    _authorize_mcp(resolved, "container.install", {
        "directory": directory,
        "kind": kind,
        "force": force,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
        "confirm": confirm,
    })
    bundle = _container_bundle(kind)
    planned = plan_remote_assets(
        directory,
        bundle,
        roots=resolved.capabilities.remote_roots.install,
    )
    preview = {
        "operation": "install_container",
        "profile": resolved.name,
        "directory": directory,
        "files": [asset.relative_path for asset in planned],
        "force": force,
        "confirm_required": not confirm,
        "dry_run": dry_run,
        "executed": False,
    }
    if not confirm or dry_run:
        return preview
    installed = install_remote_assets(
        resolved,
        directory,
        bundle,
        roots=resolved.capabilities.remote_roots.install,
        overwrite=force,
    )
    return preview | {
        "confirm_required": False,
        "executed": True,
        "installed": [asset.__dict__ for asset in installed],
    }
