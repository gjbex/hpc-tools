from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from hpc_tools import delegation
from hpc_tools.config import ConfigError

TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}
CONTINUING_STATES = {
    "COMPLETING",
    "CONFIGURING",
    "PENDING",
    "REQUEUED",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "RESIZING",
    "RUNNING",
    "SIGNALING",
    "SPECIAL_EXIT",
    "STAGE_OUT",
    "STOPPED",
    "SUSPENDED",
}


def cleanup_action(policy: delegation.LifecyclePolicy, parent_state: str) -> str:
    """Return cancel, leave-running, or defer for one parent scheduler state."""
    state = _normalize_state(parent_state)
    if state in CONTINUING_STATES:
        return "defer"
    if state == "CANCELLED":
        return policy.on_cancel
    if state == "TIMEOUT":
        return "cancel" if policy.on_timeout == "requeue-or-cancel" else policy.on_timeout
    if state == "COMPLETED":
        return policy.on_normal_exit_with_active_jobs
    if state in TERMINAL_STATES:
        return policy.on_failure
    raise ConfigError(f"cannot apply cleanup policy to parent state {parent_state!r}")


def run_cleanup(
    *,
    manifest_path: Path,
    ledger_path: Path,
    profile: str,
    parent_job_id: str,
    cleanup_job_id: str | None = None,
    retries: int = 6,
    retry_delay: float = 10.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Apply the parent terminal-state policy to exact ledger-owned jobs."""
    if retries < 1:
        raise ConfigError("cleanup retries must be positive")
    manifest = delegation.load_manifest(
        manifest_path,
        expected_profile=profile,
        expected_parent_job_id=parent_job_id,
        allow_expired=True,
    )
    ledger = delegation.DelegationLedger(ledger_path)
    registered_cleanup_job = ledger.cleanup_job_id(manifest)
    if registered_cleanup_job is None:
        raise delegation.DelegationError("delegation has no registered cleanup job")
    if cleanup_job_id is not None:
        current_cleanup_job = delegation.normalize_job_id(cleanup_job_id)
        if current_cleanup_job != registered_cleanup_job:
            raise delegation.DelegationError(
                "cleanup process does not match the registered cleanup job"
            )
    ledger.record_cleanup_status(manifest, status="running")

    parent_state = _observe_parent_state(
        parent_job_id,
        retries=retries,
        retry_delay=retry_delay,
        runner=runner,
    )
    controller = ledger.controller_summary_for_cleanup(manifest)
    if str(controller["reason"] or "").startswith("timeout-requeue-failed"):
        action = "cancel"
    elif controller["reason"] == "timeout":
        action = (
            "cancel"
            if manifest.lifecycle.on_timeout == "requeue-or-cancel"
            else manifest.lifecycle.on_timeout
        )
    else:
        action = cleanup_action(manifest.lifecycle, parent_state)
    if action == "defer":
        error = f"parent job is still {parent_state}; cleanup must be retried"
        ledger.record_cleanup_status(manifest, status="failed", error=error)
        raise ConfigError(error)

    if controller["state"] != "final":
        ledger.finalize_controller(
            manifest, reason=f"parent scheduler state {parent_state}"
        )
    owned = ledger.owned_jobs_for_cleanup(manifest)
    if action == "leave-running":
        ledger.record_cleanup_status(manifest, status="preserved")
        return {
            "parent_job_id": parent_job_id,
            "parent_state": parent_state,
            "action": action,
            "preserved": owned,
            "cancelled": [],
            "reconciled": [],
        }

    cancelled: list[dict[str, str]] = []
    reconciled: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for job in owned:
        job_id = job["job_id"]
        cluster = job["cluster"] or None
        state = _observe_state(
            job_id,
            cluster=cluster,
            retries=1,
            retry_delay=0,
            runner=runner,
            allow_unknown=True,
        )
        if state in TERMINAL_STATES:
            ledger.reconcile_job(
                manifest, job_id=job_id, cluster=cluster, state=state
            )
            reconciled.append({"job_id": job_id, "cluster": cluster or "", "state": state})
            continue

        key, reservation = ledger.reserve_cleanup_cancellation(
            manifest, job_id=job_id, cluster=cluster
        )
        if reservation["status"] == "succeeded":
            ledger.reconcile_job(
                manifest, job_id=job_id, cluster=cluster, state="CANCELLED"
            )
            cancelled.append({"job_id": job_id, "cluster": cluster or ""})
            continue
        if reservation["status"] in {"failed", "uncertain"}:
            failures.append(
                {
                    "job_id": job_id,
                    "error": (
                        "previous cleanup cancellation is "
                        f"{reservation['status']}; operator reconciliation is required"
                    ),
                }
            )
            continue
        command = ["scancel"]
        if cluster:
            command.extend(["-M", cluster])
        command.append(job_id)
        completed = runner(command, check=False, capture_output=True, text=True)
        result = {
            "operation": "parent_cleanup_cancel",
            "jobid": job_id,
            "cluster": cluster,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        try:
            ledger.record_lifecycle_result(
                manifest,
                idempotency_key=key,
                succeeded=completed.returncode == 0,
                result=result,
            )
        except delegation.DelegationError as error:
            ledger.record_accepted_lifecycle_uncertain(
                manifest,
                idempotency_key=key,
                result=result,
                reason=str(error),
            )
            failures.append({"job_id": job_id, "error": str(error)})
            continue
        if completed.returncode == 0:
            ledger.reconcile_job(
                manifest, job_id=job_id, cluster=cluster, state="CANCELLED"
            )
            cancelled.append({"job_id": job_id, "cluster": cluster or ""})
        else:
            failures.append(
                {
                    "job_id": job_id,
                    "error": completed.stderr.strip() or f"scancel exited {completed.returncode}",
                }
            )

    if failures:
        error = json.dumps(failures, sort_keys=True)
        ledger.record_cleanup_status(manifest, status="failed", error=error)
    else:
        ledger.record_cleanup_status(manifest, status="succeeded")
    return {
        "parent_job_id": parent_job_id,
        "parent_state": parent_state,
        "action": action,
        "preserved": [],
        "cancelled": cancelled,
        "reconciled": reconciled,
        "failures": failures,
    }


def _observe_state(
    job_id: str,
    *,
    cluster: str | None,
    retries: int,
    retry_delay: float,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    allow_unknown: bool = False,
) -> str:
    command = ["sacct", "-n", "-P"]
    if cluster:
        command.extend(["-M", cluster])
    command.extend(["-j", job_id, "--format=JobIDRaw,State"])
    error = ""
    for attempt in range(retries):
        completed = runner(command, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            state = _parse_state(completed.stdout, job_id)
            if state != "UNKNOWN":
                return state
            error = "scheduler accounting returned no matching job state"
        else:
            error = completed.stderr.strip() or f"sacct exited {completed.returncode}"
        if attempt + 1 < retries and retry_delay:
            time.sleep(retry_delay)
    if allow_unknown:
        return "UNKNOWN"
    raise ConfigError(f"unable to determine Slurm state for job {job_id}: {error}")


def _observe_parent_state(
    job_id: str,
    *,
    retries: int,
    retry_delay: float,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Prefer current queue state so requeued attempts are not mistaken for terminal."""
    queue = runner(
        ["squeue", "-h", "-j", job_id, "-o", "%T"],
        check=False,
        capture_output=True,
        text=True,
    )
    if queue.returncode == 0:
        for line in queue.stdout.splitlines():
            state = _normalize_state(line)
            if state:
                return state
    return _observe_state(
        job_id,
        cluster=None,
        retries=retries,
        retry_delay=retry_delay,
        runner=runner,
    )


def _parse_state(output: str, job_id: str) -> str:
    base_job_id = delegation.normalize_job_id(job_id)
    for line in output.splitlines():
        fields = line.split("|", 2)
        if len(fields) < 2:
            continue
        try:
            observed = delegation.normalize_job_id(fields[0])
        except delegation.DelegationError:
            continue
        if observed == base_job_id:
            return _normalize_state(fields[1])
    return "UNKNOWN"


def _normalize_state(state: str) -> str:
    normalized = state.split("+", 1)[0].strip().upper()
    return normalized.split(maxsplit=1)[0] if normalized else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hpc-agent-reap")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--parent-job-id", required=True)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        cleanup_job_id = os.environ.get("SLURM_JOB_ID")
        if not cleanup_job_id:
            raise ConfigError("hpc-agent-reap must run inside its Slurm cleanup job")
        result = run_cleanup(
            manifest_path=args.manifest,
            ledger_path=args.ledger,
            profile=args.profile,
            parent_job_id=args.parent_job_id,
            cleanup_job_id=cleanup_job_id,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )
    except (ConfigError, OSError) as error:
        print(f"hpc-agent-reap: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
