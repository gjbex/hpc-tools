from __future__ import annotations

from typing import Any

from hpc_tools import slurm, submissions
from hpc_tools.commands.slurm import _quote_command as _sam_quote_command
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import execution_plan, run_command_capture
from hpc_tools import slurm_contracts
from hpc_tools.mcp.common import _remote_read_result, _resolve_profile

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
    command = slurm.submit_command(
        jobscript,
        directory=directory,
        test_only=False,
        overrides=normalized,
    )
    plan = execution_plan(resolved, command)
    _require_evidence("quote", quote_evidence, shape, executor=plan.executor)
    _require_evidence(
        "validation",
        validation_evidence,
        shape,
        executor=plan.executor,
    )
    preview = {
        "profile": resolved.name,
        "command": command,
        **plan.metadata(),
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

    completed = run_command_capture(resolved, command)
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
    return slurm_contracts.normalize_submit_overrides(account=account, **overrides)

def _quote_args_for_submit(jobscript: str, overrides: dict[str, str | None]) -> list[str]:
    return slurm_contracts.quote_args_for_submit(jobscript, overrides)

def _submission_shape(
    profile: Profile,
    jobscript: str,
    directory: str,
    overrides: dict[str, str | None],
) -> dict[str, Any]:
    return slurm_contracts.submission_shape(profile, jobscript, directory, overrides)

def _shape_token(shape: dict[str, Any]) -> str:
    return slurm_contracts.shape_token(shape)

def _submission_evidence(
    evidence_type: str,
    shape: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return slurm_contracts.submission_evidence(evidence_type, shape, result)

def _evidence_token(evidence: dict[str, Any]) -> str:
    return slurm_contracts.evidence_token(evidence)

def _require_evidence(
    evidence_type: str,
    evidence: dict[str, Any],
    shape: dict[str, Any],
    *,
    executor: str | None = None,
) -> None:
    slurm_contracts.validate_evidence(
        evidence_type,
        evidence,
        shape,
        executor=executor,
    )
