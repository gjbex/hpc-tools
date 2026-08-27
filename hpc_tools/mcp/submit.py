from __future__ import annotations

from pathlib import Path
from typing import Any

from hpc_tools import delegation, restricted_jobs, slurm, slurm_contracts, submissions
from hpc_tools.commands.slurm import _quote_command as _sam_quote_command
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import execution_plan, run_command_capture
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
    container: str | None = None,
    idempotency_key: str | None = None,
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
    runtime = delegation.current_runtime()
    prepared = _prepare_request(
        runtime,
        resolved=resolved,
        jobscript=jobscript,
        directory=directory,
        container=container,
        idempotency_key=idempotency_key,
        normalized=normalized,
        stage=runtime is not None and not dry_run,
        temporary=runtime is not None and not dry_run,
    )
    shape = prepared.shape
    quote_jobscript = (
        str(Path(prepared.directory) / prepared.jobscript)
        if runtime is not None
        else prepared.jobscript
    )
    quote_args = _quote_args_for_submit(quote_jobscript, prepared.overrides)
    command = _sam_quote_command(resolved.sam_quote_command, quote_args)
    try:
        result = _remote_read_result(resolved, command, dry_run=dry_run)
    finally:
        prepared.cleanup()
    evidence = _submission_evidence("quote", shape, result)
    return result | {
        "resource_shape": shape,
        "quote_evidence": evidence,
        "output_directory": prepared.output_directory,
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
    container: str | None = None,
    idempotency_key: str | None = None,
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
    runtime = delegation.current_runtime()
    prepared = _prepare_request(
        runtime,
        resolved=resolved,
        jobscript=jobscript,
        directory=directory,
        container=container,
        idempotency_key=idempotency_key,
        normalized=normalized,
        stage=runtime is not None and not dry_run,
        temporary=runtime is not None and not dry_run,
    )
    shape = prepared.shape
    command = slurm.submit_command(
        prepared.jobscript,
        directory=prepared.directory,
        test_only=True,
        overrides=prepared.overrides,
    )
    try:
        result = _remote_read_result(resolved, command, dry_run=dry_run)
    finally:
        prepared.cleanup()
    evidence = _submission_evidence("validation", shape, result)
    return result | {
        "resource_shape": shape,
        "validation_evidence": evidence,
        "output_directory": prepared.output_directory,
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
    container: str | None = None,
    idempotency_key: str | None = None,
    database: str | None = None,
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
    runtime = delegation.current_runtime()
    prepared = _prepare_request(
        runtime,
        resolved=resolved,
        jobscript=jobscript,
        directory=directory,
        container=container,
        idempotency_key=idempotency_key,
        normalized=normalized,
        stage=False,
        temporary=False,
    )
    shape = prepared.shape
    command = slurm.submit_command(
        prepared.jobscript,
        directory=prepared.directory,
        test_only=False,
        overrides=prepared.overrides,
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
        "output_directory": prepared.output_directory,
        "confirm_required": runtime is None and not confirm,
        "dry_run": dry_run,
        "executed": False,
        "logged": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }
    if dry_run or (runtime is None and not confirm):
        return preview

    ledger = None
    reservation = None
    staged: restricted_jobs.PreparedJob | None = None
    if runtime is not None:
        if not idempotency_key:
            raise delegation.DelegationError(
                "restricted submission requires an idempotency_key"
            )
        ledger = delegation.DelegationLedger(runtime.ledger_path)
        reservation = ledger.reserve_submission(
            runtime.manifest,
            idempotency_key=idempotency_key,
            shape=shape,
        )
        if reservation["status"] == "submitted":
            return preview | {
                "confirm_required": False,
                "idempotent_replay": True,
                "executed": False,
                "logged": False,
                "ledger_recorded": True,
                "submission_event": None,
                "job_id": reservation["job_id"],
                "cluster": reservation["cluster"],
            }
        if reservation["idempotent_replay"]:
            raise delegation.DelegationError(
                f"idempotent operation is in {reservation['status']!r} state; "
                "use a new key after failure or reconcile an uncertain reservation"
            )

        try:
            staged = _prepare_request(
                runtime,
                resolved=resolved,
                jobscript=jobscript,
                directory=directory,
                container=container,
                idempotency_key=idempotency_key,
                normalized=normalized,
                stage=True,
                temporary=False,
            )
            if staged.shape["shape_token"] != shape["shape_token"]:
                raise delegation.DelegationError(
                    "job payload changed after evidence validation; quote and validate again"
                )
            if (staged.jobscript, staged.directory, staged.overrides) != (
                prepared.jobscript,
                prepared.directory,
                prepared.overrides,
            ):
                raise delegation.DelegationError(
                    "server-generated job paths changed during submission"
                )
        except (delegation.DelegationError, OSError) as staging_error:
            ledger.release_reservation(
                runtime.manifest,
                idempotency_key=idempotency_key,
                reason=f"unable to stage restricted job: {staging_error}",
            )
            raise

    try:
        completed = run_command_capture(resolved, command)
    except OSError as execution_error:
        if ledger is not None and idempotency_key is not None:
            ledger.release_reservation(
                runtime.manifest,
                idempotency_key=idempotency_key,
                reason=f"unable to execute sbatch: {execution_error}",
            )
            if staged is not None:
                staged.discard()
        raise
    stdout = completed.stdout
    stderr = completed.stderr
    logged = False
    database_error = None
    submission_event = None
    ledger_recorded = runtime is None
    if completed.returncode == 0:
        try:
            job_id, cluster = submissions.parse_sbatch_submission(stdout + stderr)
        except ValueError:
            if ledger is not None and idempotency_key is not None:
                ledger.release_reservation(
                    runtime.manifest,
                    idempotency_key=idempotency_key,
                    reason="scheduler accepted submission but job id could not be parsed",
                    uncertain=True,
                )
            raise
        selected_cluster = cluster or normalized.get("cluster") or resolved.default_cluster
        if ledger is not None and idempotency_key is not None:
            ledger.record_submission(
                runtime.manifest,
                idempotency_key=idempotency_key,
                job_id=job_id,
                cluster=selected_cluster,
            )
            ledger_recorded = True
        submission_event = submissions.submitted_event(
            profile=resolved.name,
            job_id=job_id,
            cluster=selected_cluster,
            remote_directory=directory,
            jobscript=jobscript,
            submit_command=command,
            overrides=normalized,
        )
        database_path = (
            Path(database).expanduser()
            if database
            else submissions.default_database_path()
        )
        try:
            submissions.append_event(submission_event, path=database_path)
            logged = True
        except (OSError, ValueError) as database_exception:
            database_error = str(database_exception)
    staging_cleanup_error = None
    if completed.returncode != 0 and ledger is not None and idempotency_key is not None:
        ledger.release_reservation(
            runtime.manifest,
            idempotency_key=idempotency_key,
            reason=f"sbatch failed with return code {completed.returncode}",
        )
        if staged is not None:
            staging_cleanup_error = staged.discard()
    return preview | {
        "confirm_required": False,
        "idempotent_replay": False,
        "executed": True,
        "ledger_recorded": ledger_recorded,
        "logged": logged,
        "database": str(
            Path(database).expanduser()
            if database
            else submissions.default_database_path()
        ),
        "database_error": database_error,
        "staging_cleanup_error": staging_cleanup_error,
        "submission_event": submission_event,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }

def _submit_overrides(account: str | None = None, **overrides: str | None) -> dict[str, str | None]:
    return slurm_contracts.normalize_submit_overrides(account=account, **overrides)


def _prepare_request(
    runtime: delegation.DelegationRuntime | None,
    *,
    resolved: Profile,
    jobscript: str,
    directory: str,
    container: str | None,
    idempotency_key: str | None,
    normalized: dict[str, str | None],
    stage: bool,
    temporary: bool,
) -> restricted_jobs.PreparedJob:
    if runtime is not None:
        return restricted_jobs.prepare_job(
            runtime,
            profile=resolved,
            jobscript=jobscript,
            directory=directory,
            container=container,
            idempotency_key=idempotency_key,
            overrides=normalized,
            stage=stage,
            temporary=temporary,
        )
    if container is not None:
        raise ConfigError(
            "container is a restricted-delegation parameter; full mode submits the jobscript directly"
        )
    shape = _submission_shape(resolved, jobscript, directory, normalized)
    return restricted_jobs.PreparedJob(
        shape=shape,
        jobscript=jobscript,
        directory=directory,
        overrides=normalized,
        output_directory="",
    )

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
