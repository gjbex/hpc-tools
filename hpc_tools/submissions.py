from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import uuid
from typing import Any

from hpc_tools.config import default_config_dir


TERMINAL_SLURM_STATES = {
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


@dataclass(frozen=True)
class SubmissionRecord:
    run_id: str
    job_id: str
    cluster: str | None
    profile: str
    jobscript: str
    remote_directory: str
    latest_event: str
    latest_state: str
    action: str


def default_log_path() -> Path:
    return default_config_dir() / "submissions.jsonl"


def make_run_id(profile: str, job_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{profile}-{job_id}-{suffix}"


def append_event(event: dict[str, Any], *, path: Path | None = None) -> None:
    log_path = path or default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {"timestamp": _timestamp(), **event}
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    log_path = path or default_log_path()
    if not log_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw_event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{log_path}:{line_number}: invalid JSONL event") from error
        if not isinstance(raw_event, dict):
            raise ValueError(f"{log_path}:{line_number}: event must be an object")
        events.append(raw_event)
    return events


def records_from_events(events: list[dict[str, Any]]) -> list[SubmissionRecord]:
    by_run: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        run_id = event.get("run_id")
        if isinstance(run_id, str):
            by_run.setdefault(run_id, []).append(event)

    records = []
    for run_id, run_events in by_run.items():
        submitted = next(
            (event for event in run_events if event.get("event") == "submitted"),
            run_events[0],
        )
        latest = run_events[-1]
        latest_event = str(latest.get("event", "unknown"))
        latest_state = _latest_state(run_events)
        records.append(
            SubmissionRecord(
                run_id=run_id,
                job_id=str(submitted.get("job_id", "")),
                cluster=_optional_str(submitted.get("cluster")),
                profile=str(submitted.get("profile", "")),
                jobscript=str(submitted.get("jobscript", "")),
                remote_directory=str(submitted.get("remote_directory", "")),
                latest_event=latest_event,
                latest_state=latest_state,
                action=_action_for(run_events, latest_state),
            )
        )
    return sorted(records, key=lambda record: record.run_id)


def active_records(events: list[dict[str, Any]]) -> list[SubmissionRecord]:
    return [
        record for record in records_from_events(events)
        if record.action != "closed"
    ]


def parse_sbatch_submission(output: str) -> tuple[str, str | None]:
    match = re.search(
        r"Submitted batch job (?P<job_id>\d+)(?: on cluster (?P<cluster>\S+))?",
        output,
    )
    if not match:
        raise ValueError("could not parse sbatch job ID from output")
    return match.group("job_id"), match.group("cluster")


def submitted_event(
    *,
    profile: str,
    job_id: str,
    cluster: str | None,
    remote_directory: str,
    jobscript: str,
    submit_command: str,
    overrides: dict[str, str | None],
) -> dict[str, Any]:
    return {
        "event": "submitted",
        "run_id": make_run_id(profile, job_id),
        "profile": profile,
        "job_id": job_id,
        "cluster": cluster,
        "remote_directory": remote_directory,
        "jobscript": jobscript,
        "submit_command": submit_command,
        "slurm_overrides": {
            name: value for name, value in overrides.items()
            if value is not None
        },
    }


def observed_event(
    record: SubmissionRecord,
    *,
    state: str,
    exit_code: str | None,
    elapsed: str | None,
    raw_output: str,
) -> dict[str, Any]:
    return {
        "event": "observed",
        "run_id": record.run_id,
        "profile": record.profile,
        "job_id": record.job_id,
        "cluster": record.cluster,
        "state": state,
        "exit_code": exit_code,
        "elapsed": elapsed,
        "raw_output": raw_output,
    }


def mark_event(
    run_id: str,
    event: str,
    *,
    path: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"event": event, "run_id": run_id}
    if path:
        data["path"] = path
    if reason:
        data["reason"] = reason
    return data


def format_records(records: list[SubmissionRecord]) -> str:
    if not records:
        return "No submissions."

    rows = [
        [
            record.run_id,
            record.profile,
            record.cluster or "",
            record.job_id,
            record.latest_state,
            record.action,
            record.jobscript,
        ]
        for record in records
    ]
    headers = ["RUN_ID", "PROFILE", "CLUSTER", "JOBID", "STATE", "ACTION", "JOBSCRIPT"]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines = [_format_row(headers, widths), _format_row(["-" * width for width in widths], widths)]
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def sacct_observe_command(job_id: str, cluster: str | None) -> str:
    parts = ["sacct"]
    if cluster:
        parts.extend(["-M", cluster])
    parts.extend([
        "-j",
        job_id,
        "--parsable2",
        "--noheader",
        "--format=JobIDRaw,State,ExitCode,Elapsed",
    ])
    return " ".join(shlex.quote(part) for part in parts)


def parse_sacct_observation(output: str, job_id: str) -> tuple[str, str | None, str | None]:
    candidates = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        raw_job_id, state, exit_code, elapsed = parts[:4]
        if raw_job_id == job_id or raw_job_id.startswith(f"{job_id}_"):
            candidates.append((state, exit_code, elapsed))

    if not candidates:
        return "UNKNOWN", None, None

    states = [state for state, _, _ in candidates]
    if any(state not in TERMINAL_SLURM_STATES for state in states):
        state = next(state for state in states if state not in TERMINAL_SLURM_STATES)
        exit_code = next(
            exit_code for cand_state, exit_code, _ in candidates
            if cand_state == state
        )
        elapsed = next(elapsed for cand_state, _, elapsed in candidates if cand_state == state)
        return state, exit_code, elapsed
    if all(state == "COMPLETED" for state in states):
        state, exit_code, elapsed = candidates[0]
        return state, exit_code, elapsed
    state = next(state for state in states if state != "COMPLETED")
    exit_code = next(exit_code for cand_state, exit_code, _ in candidates if cand_state == state)
    elapsed = next(elapsed for cand_state, _, elapsed in candidates if cand_state == state)
    return state, exit_code, elapsed


def _timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _latest_state(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        state = event.get("state")
        if isinstance(state, str):
            return state
    return "SUBMITTED"


def _action_for(events: list[dict[str, Any]], latest_state: str) -> str:
    event_names = {str(event.get("event")) for event in events}
    if "closed" in event_names:
        return "closed"
    if latest_state in {"FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"}:
        return "triage"
    if latest_state == "COMPLETED" and "results_collected" not in event_names:
        return "collect"
    if latest_state == "COMPLETED" and "analysed" not in event_names:
        return "analyse"
    if latest_state in {"PENDING", "RUNNING", "SUBMITTED", "UNKNOWN"}:
        return "observe"
    return "observe"


def _format_row(row: list[str], widths: list[int]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(row, widths))


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
