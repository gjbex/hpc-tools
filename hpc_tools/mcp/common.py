from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hpc_tools import references, submissions
from hpc_tools.config import Config, ConfigError, Profile, load_config, resolve_profile
from hpc_tools.execution import execution_plan, run_command_capture

def _load_config(config_path: str | None = None) -> Config:
    return load_config(config_path)

def _resolve_profile(*, profile_name: str | None = None, config_path: str | None = None) -> Profile:
    config = _load_config(config_path)
    return resolve_profile(config, profile_name)

def _remote_read_result(profile: Profile, command: str, *, dry_run: bool = False) -> dict[str, Any]:
    plan = execution_plan(profile, command)
    if dry_run:
        return {
            "profile": profile.name,
            "command": command,
            **plan.metadata(),
            "dry_run": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    completed = run_command_capture(profile, command)
    return {
        "profile": profile.name,
        "command": command,
        **plan.metadata(),
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
    plan = execution_plan(profile, command)
    preview = {
        "profile": profile.name,
        "command": command,
        **plan.metadata(),
        "confirm_required": not confirm,
        "dry_run": dry_run,
        "executed": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
    if not confirm or dry_run:
        return preview

    completed = run_command_capture(profile, command)
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
    database: str | None,
    confirm: bool,
) -> dict[str, Any]:
    event = submissions.mark_event(run_id, event_name, path=path)
    return _append_submission_event(event, database=database, confirm=confirm)

def _append_submission_event(
    event: dict[str, Any],
    *,
    database: str | None,
    confirm: bool,
) -> dict[str, Any]:
    database_path = Path(database).expanduser() if database else submissions.default_database_path()
    preview = {
        "operation": event["event"],
        "database": str(database_path),
        "event": event,
        "confirm_required": not confirm,
    }
    if not confirm:
        return preview

    submissions.append_event(event, path=database_path)
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
