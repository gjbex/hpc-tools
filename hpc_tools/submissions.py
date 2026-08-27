from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import sqlite3
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


SCHEMA_VERSION = 1


class SubmissionDatabaseError(ValueError):
    """Raised when the local submission database cannot be used safely."""


def default_database_path() -> Path:
    return default_config_dir() / "submissions.sqlite3"


def make_run_id(profile: str, job_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{timestamp}-{profile}-{job_id}-{suffix}"


def append_event(event: dict[str, Any], *, path: Path | None = None) -> None:
    append_events([event], path=path)


def append_events(
    events: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> None:
    if not events:
        return

    database_path = path or default_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    prepared = [_prepare_event(event) for event in events]

    with _database(database_path) as connection:
        _ensure_schema(connection)
        connection.executemany(
            """
            INSERT INTO submission_events (
                event_id,
                run_id,
                event_type,
                occurred_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    uuid.uuid4().hex,
                    event["run_id"],
                    event["event"],
                    event["timestamp"],
                    json.dumps(event, sort_keys=True, separators=(",", ":")),
                )
                for event in prepared
            ],
        )


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    database_path = path or default_database_path()
    if not database_path.exists():
        return []

    with _database(database_path) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT sequence, payload_json
            FROM submission_events
            ORDER BY sequence
            """
        ).fetchall()

    events: list[dict[str, Any]] = []
    for sequence, payload_json in rows:
        try:
            raw_event = json.loads(payload_json)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{database_path}: event {sequence} contains invalid JSON"
            ) from error
        if not isinstance(raw_event, dict):
            raise ValueError(
                f"{database_path}: event {sequence} payload must be an object"
            )
        events.append(raw_event)
    return events


@contextmanager
def _database(path: Path) -> Iterator[sqlite3.Connection]:
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(path)
        with connection:
            yield connection
    except sqlite3.Error as error:
        raise SubmissionDatabaseError(
            f"unable to use submissions database {path}: {error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()


def _connect(path: Path) -> sqlite3.Connection:
    database_existed = path.exists()
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        if not database_existed:
            path.chmod(0o600)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        return connection
    except Exception:
        connection.close()
        raise


def _ensure_schema(connection: sqlite3.Connection) -> None:
    version = _schema_version(connection)
    if version == 0:
        connection.execute("BEGIN IMMEDIATE")
        version = _schema_version(connection)
        if version == 0:
            connection.execute(
                """
                CREATE TABLE submission_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX submission_events_by_run
                ON submission_events (run_id, sequence)
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        connection.commit()

    if version != SCHEMA_VERSION:
        raise SubmissionDatabaseError(
            f"unsupported submissions database schema version {version}; "
            f"expected {SCHEMA_VERSION}"
        )


def _schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _prepare_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = event.get("event")
    run_id = event.get("run_id")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("submission event requires a non-empty 'event' string")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("submission event requires a non-empty 'run_id' string")
    timestamp = event.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        raise ValueError("submission event 'timestamp' must be a string")
    prepared = dict(event)
    prepared["timestamp"] = timestamp or _timestamp()
    return prepared


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


def cancel_requested_event(
    record: SubmissionRecord,
    *,
    requested_job_id: str,
    cancel_command: str,
    reason: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "cancel_requested",
        "run_id": record.run_id,
        "profile": record.profile,
        "job_id": record.job_id,
        "requested_job_id": requested_job_id,
        "cluster": record.cluster,
        "cancel_command": cancel_command,
    }
    if reason:
        event["reason"] = reason
    return event


def active_records_for_job(
    events: list[dict[str, Any]],
    *,
    profile: str,
    job_id: str,
    cluster: str | None,
) -> list[SubmissionRecord]:
    base_job_id = re.match(r"\d+", job_id)
    submitted_job_id = base_job_id.group(0) if base_job_id else job_id
    return [
        record
        for record in active_records(events)
        if record.profile == profile
        and record.job_id in {job_id, submitted_job_id}
        and record.cluster == cluster
    ]


def append_cancel_requested_events(
    *,
    profile: str,
    job_id: str,
    cluster: str | None,
    cancel_command: str,
    reason: str | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    records = active_records_for_job(
        read_events(path),
        profile=profile,
        job_id=job_id,
        cluster=cluster,
    )
    events = [
        cancel_requested_event(
            record,
            requested_job_id=job_id,
            cancel_command=cancel_command,
            reason=reason,
        )
        for record in records
    ]
    append_events(events, path=path)
    return events


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
        if len(parts) >= 7:
            raw_job_id, state, exit_code, elapsed = (
                parts[0], parts[4], parts[5], parts[6]
            )
        else:
            raw_job_id, state, exit_code, elapsed = parts[:4]
        if (
            raw_job_id == job_id
            or raw_job_id.startswith(f"{job_id}_")
            or raw_job_id.startswith(f"{job_id}+")
        ):
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
