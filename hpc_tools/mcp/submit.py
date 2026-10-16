from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hpc_tools import (
    credit_quotes,
    delegation,
    restricted_jobs,
    slurm,
    slurm_contracts,
    submissions,
)
from hpc_tools.commands.slurm import _quote_command as _sam_quote_command
from hpc_tools.config import ConfigError, Profile
from hpc_tools.execution import execution_plan, run_command_capture
from hpc_tools.mcp.common import _authorize_mcp, _remote_read_result, _resolve_profile


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
    _authorize_mcp(resolved, "job.quote", {
        "jobscript": jobscript,
        "directory": directory,
        "account": account,
        "container": container,
        "idempotency_key": idempotency_key,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    })
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
    structured_quote = None
    if (
        resolved.sam_quote_format is not None
        and not result["dry_run"]
        and result["returncode"] == 0
    ):
        structured_quote = credit_quotes.parse_structured_quote(
            result["stdout"],
            format_name=resolved.sam_quote_format,
        )
    budget = _credit_budget(runtime)
    if budget is not None and structured_quote is not None:
        _require_quote_dimensions(structured_quote.maximum_cost, budget)
    evidence = _submission_evidence(
        "quote",
        shape,
        result,
        quoted_cost=(
            structured_quote.maximum_cost
            if budget is not None and structured_quote is not None
            else None
        ),
        quote_ttl_seconds=(
            budget.quote_ttl_seconds
            if budget is not None and structured_quote is not None
            else None
        ),
        now=_utc_now(),
    )
    response = result | {
        "resource_shape": shape,
        "quote_evidence": evidence,
        "output_directory": prepared.output_directory,
    }
    if structured_quote is not None:
        response["structured_quote"] = structured_quote.to_dict()
    return response

def hpc_validate_job(
    jobscript: str,
    directory: str = ".",
    quote_evidence: dict[str, Any] | None = None,
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
    _authorize_mcp(resolved, "job.validate", {
        "jobscript": jobscript,
        "directory": directory,
        "quote_evidence": quote_evidence,
        "container": container,
        "idempotency_key": idempotency_key,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
    })
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
    budget = _credit_budget(runtime)
    checked_quote = None
    try:
        if budget is not None:
            if quote_evidence is None:
                raise ConfigError(
                    "credit-budget validation requires current quote evidence"
                )
            checked_quote = _require_evidence(
                "quote",
                quote_evidence,
                shape,
                executor=execution_plan(resolved, command).executor,
                now=_utc_now(),
                credit_unit=budget.unit,
                credit_scale=budget.scale,
                quote_ttl_seconds=budget.quote_ttl_seconds,
            )
        result = _remote_read_result(resolved, command, dry_run=dry_run)
        issued_at = _utc_now()
        if budget is not None and quote_evidence is not None:
            checked_quote = _require_evidence(
                "quote",
                quote_evidence,
                shape,
                executor=execution_plan(resolved, command).executor,
                now=issued_at,
                credit_unit=budget.unit,
                credit_scale=budget.scale,
                quote_ttl_seconds=budget.quote_ttl_seconds,
            )
    finally:
        prepared.cleanup()
    evidence = _submission_evidence(
        "validation",
        shape,
        result,
        quote_evidence_token=(
            checked_quote.evidence_token if checked_quote is not None else None
        ),
        now=issued_at,
    )
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
    _authorize_mcp(resolved, "job.submit", {
        "jobscript": jobscript,
        "directory": directory,
        "database": database,
        "quote_evidence": quote_evidence,
        "validation_evidence": validation_evidence,
        "profile": profile,
        "config": config,
        "dry_run": dry_run,
        "confirm": confirm,
    })
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
    budget = _credit_budget(runtime)
    checked_at = _utc_now()
    checked_quote = _require_evidence(
        "quote",
        quote_evidence,
        shape,
        executor=plan.executor,
        now=checked_at,
        credit_unit=budget.unit if budget is not None else None,
        credit_scale=budget.scale if budget is not None else None,
        quote_ttl_seconds=(
            budget.quote_ttl_seconds if budget is not None else None
        ),
    )
    _require_evidence(
        "validation",
        validation_evidence,
        shape,
        executor=plan.executor,
        now=checked_at,
        expected_quote_evidence_token=(
            checked_quote.evidence_token if budget is not None else None
        ),
        not_before=(checked_quote.timestamp if budget is not None else None),
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
        quoted_credit = _quoted_credit_reservation(checked_quote, budget)
        ledger = delegation.DelegationLedger(runtime.ledger_path)
        reservation = ledger.reserve_submission(
            runtime.manifest,
            idempotency_key=idempotency_key,
            shape=shape,
            quoted_credit=quoted_credit,
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
    ledger_error = None
    ledger_recovery_error = None
    ledger_status = "not_applicable" if runtime is None else "reserved"
    submission_event = None
    ledger_recorded = runtime is None
    submitted_job_id = None
    submitted_cluster = None
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
        submitted_job_id = job_id
        submitted_cluster = selected_cluster
        if ledger is not None and idempotency_key is not None:
            try:
                ledger.record_submission(
                    runtime.manifest,
                    idempotency_key=idempotency_key,
                    job_id=job_id,
                    cluster=selected_cluster,
                    output_directory=prepared.output_directory,
                )
                ledger_recorded = True
                ledger_status = "submitted"
            except delegation.DelegationError as persistence_error:
                ledger_error = str(persistence_error)
                try:
                    ledger.record_accepted_submission_uncertain(
                        runtime.manifest,
                        idempotency_key=idempotency_key,
                        job_id=job_id,
                        cluster=selected_cluster,
                        reason=ledger_error,
                    )
                    ledger_recorded = True
                    ledger_status = "uncertain"
                except delegation.DelegationError as recovery_error:
                    ledger_recovery_error = str(recovery_error)
                    ledger_status = "unrecorded"
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
        ledger_recorded = True
        ledger_status = "failed"
        if staged is not None:
            staging_cleanup_error = staged.discard()
    return preview | {
        "confirm_required": False,
        "idempotent_replay": False,
        "executed": True,
        "ledger_recorded": ledger_recorded,
        "ledger_status": ledger_status,
        "ledger_error": ledger_error,
        "ledger_recovery_error": ledger_recovery_error,
        "job_id": submitted_job_id,
        "cluster": submitted_cluster,
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
    *,
    quoted_cost: credit_quotes.CreditAmount | None = None,
    quote_ttl_seconds: int | None = None,
    quote_evidence_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return slurm_contracts.submission_evidence(
        evidence_type,
        shape,
        result,
        quoted_cost=quoted_cost,
        quote_ttl_seconds=quote_ttl_seconds,
        quote_evidence_token=quote_evidence_token,
        now=now,
    )

def _evidence_token(evidence: dict[str, Any]) -> str:
    return slurm_contracts.evidence_token(evidence)

def _require_evidence(
    evidence_type: str,
    evidence: dict[str, Any],
    shape: dict[str, Any],
    *,
    executor: str | None = None,
    now: datetime | None = None,
    credit_unit: str | None = None,
    credit_scale: int | None = None,
    quote_ttl_seconds: int | None = None,
    expected_quote_evidence_token: str | None = None,
    not_before: datetime | None = None,
) -> slurm_contracts.ValidatedEvidence:
    return slurm_contracts.validate_evidence(
        evidence_type,
        evidence,
        shape,
        executor=executor,
        now=now,
        credit_unit=credit_unit,
        credit_scale=credit_scale,
        quote_ttl_seconds=quote_ttl_seconds,
        expected_quote_evidence_token=expected_quote_evidence_token,
        not_before=not_before,
    )


def _credit_budget(
    runtime: delegation.DelegationRuntime | None,
) -> delegation.CreditBudget | None:
    if runtime is None:
        return None
    return runtime.controller_authority.credit_budget


def _quoted_credit_reservation(
    evidence: slurm_contracts.ValidatedEvidence,
    budget: delegation.CreditBudget | None,
) -> delegation.QuotedCreditReservation | None:
    if budget is None:
        return None
    if evidence.quoted_cost is None or evidence.expires_at is None:
        raise ConfigError("validated quote is missing quoted-credit authority")
    return delegation.QuotedCreditReservation(
        cost=evidence.quoted_cost,
        evidence_token=evidence.evidence_token,
        expires_at=evidence.expires_at,
    )


def _require_quote_dimensions(
    amount: credit_quotes.CreditAmount,
    budget: delegation.CreditBudget,
) -> None:
    if amount.unit != budget.unit:
        raise ConfigError(
            f"structured quote credit unit {amount.unit!r} does not match "
            f"the delegated unit {budget.unit!r}"
        )
    if amount.scale != budget.scale:
        raise ConfigError(
            f"structured quote credit scale {amount.scale} does not match "
            f"the delegated scale {budget.scale}"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
