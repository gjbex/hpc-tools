from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from hpc_tools import slurm, submissions
from hpc_tools.commands.slurm import _quote_command as _sam_quote_command
from hpc_tools.config import ConfigError, Profile
from hpc_tools.ssh import build_ssh_argv, format_command, run_remote_capture
from hpc_tools.mcp.common import _remote_read_result, _resolve_profile

_EVIDENCE_SECRET: bytes | None = None

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


_EVIDENCE_SECRET: bytes | None = None

def _evidence_secret() -> bytes:
    global _EVIDENCE_SECRET
    if _EVIDENCE_SECRET is None:
        import secrets

        _EVIDENCE_SECRET = secrets.token_bytes(32)
    return _EVIDENCE_SECRET

def _evidence_token(evidence: dict[str, Any]) -> str:
    import hmac

    token_evidence = {
        key: value
        for key, value in evidence.items()
        if key != "evidence_token"
    }
    encoded = json.dumps(token_evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_evidence_secret(), encoded, hashlib.sha256).hexdigest()

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

