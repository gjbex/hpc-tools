from __future__ import annotations

import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from hpc_tools import delegation, submissions
from hpc_tools.config import ConfigError

REPORT_FORMAT_VERSION = 4


def build_report(
    ledger_path: Path,
    *,
    submissions_database: Path | None = None,
    delegation_id: str | None = None,
) -> dict[str, Any]:
    """Build a read-only operator report from agent and submission state."""
    selected_ledger = _secure_readable_file(
        ledger_path, "delegation ledger", private=True
    )
    database_path = (
        submissions_database.expanduser().absolute()
        if submissions_database is not None
        else submissions.default_database_path()
    )
    submission_events = _read_submission_events(database_path)
    events_by_job = _submission_events_by_job(submission_events)

    with _readonly_database(selected_ledger) as database:
        version = int(database.execute("PRAGMA user_version").fetchone()[0])
        if version != delegation.LEDGER_SCHEMA_VERSION:
            raise ConfigError(
                f"unsupported delegation ledger schema version {version}; "
                f"expected {delegation.LEDGER_SCHEMA_VERSION}"
            )
        parameters: tuple[str, ...] = ()
        where = ""
        if delegation_id is not None:
            where = " WHERE delegation_id=?"
            parameters = (delegation_id,)
        rows = database.execute(
            """SELECT delegation_id,manifest_sha256,issuer,profile,parent_job_id,
                      issued_at,expires_at,network_mode,manifest_json,revoked_at,
                      revocation_reason
               FROM delegations"""
            + where
            + " ORDER BY issued_at,delegation_id",
            parameters,
        ).fetchall()
        if delegation_id is not None and not rows:
            raise ConfigError(f"delegation not found in ledger: {delegation_id}")
        reports = [_delegation_report(database, row, events_by_job) for row in rows]

    return {
        "format_version": REPORT_FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ledger": str(selected_ledger),
        "submissions_database": str(database_path),
        "delegations": reports,
    }


def format_report(report: dict[str, Any]) -> str:
    delegations = report["delegations"]
    if not delegations:
        return "No delegations recorded."
    lines = [
        f"ledger: {report['ledger']}",
        f"submissions_database: {report['submissions_database']}",
    ]
    for item in delegations:
        lines.extend(
            [
                "",
                f"delegation: {item['delegation_id']}",
                f"  profile: {item['profile']}",
                f"  parent_job_id: {item['parent_job_id']}",
                f"  network_mode: {item['network_mode']}",
                f"  expires_at: {item['expires_at']}",
                f"  revoked_at: {item['revoked_at'] or '-'}",
            ]
        )
        cleanup = item["cleanup"]
        lines.append(
            "  cleanup: "
            + (
                f"job={cleanup['job_id']} status={cleanup['status']}"
                if cleanup
                else "unconfigured"
            )
        )
        lines.append("  controller_attempts:")
        for attempt in item["controller_attempts"]:
            artifact = attempt.get("artifacts") or {}
            lines.append(
                f"    generation={attempt['generation']} state={attempt['state']} "
                f"restart={attempt['restart_count']} "
                f"artifacts={artifact.get('artifact_directory', '-')}"
            )
            materialization = artifact.get("manifest_materialization")
            if isinstance(materialization, dict):
                template = materialization.get("template")
                manifest = materialization.get("manifest")
                if isinstance(template, dict) and isinstance(manifest, dict):
                    lines.append(
                        "      manifest_template_sha256="
                        f"{template.get('sha256', '-')} "
                        f"manifest_sha256={manifest.get('sha256', '-')}"
                    )
        if not item["controller_attempts"]:
            lines.append("    -")
        lines.append("  submissions:")
        for operation in item["submission_operations"]:
            quoted = operation["quote"]
            quoted_text = (
                _format_credit(quoted["quoted_maximum"])
                if quoted is not None
                else "-"
            )
            lines.append(
                f"    key={operation['idempotency_key']} status={operation['status']} "
                f"job={operation['job_id'] or '-'} cluster={operation['cluster'] or '-'} "
                f"quoted_maximum={quoted_text} "
                f"output={operation['output_directory'] or '-'}"
            )
        if not item["submission_operations"]:
            lines.append("    -")
        quote_summary = item["quoted_credit"]
        if quote_summary["configured"]:
            lines.append(
                "  consumed_quoted_maximum: "
                + _format_credit(quote_summary["consumed_quoted_maximum"])
            )
            lines.append(
                "  remaining_quoted_maximum: "
                + _format_credit(quote_summary["remaining_quoted_maximum"])
            )
        lines.append(f"  audit_events: {len(item['audit_events'])}")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output: Path, *, force: bool = False) -> Path:
    # Do not resolve the leaf: resolving first would turn an output symlink into
    # its target and make the symlink check below ineffective.
    selected = output.expanduser().absolute()
    try:
        selected.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ConfigError(
            f"unable to create audit output directory {selected.parent}: {error}"
        ) from error
    try:
        existing = selected.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
            raise ConfigError(f"output must be a regular file: {selected}")
        if not force:
            raise ConfigError(
                f"output file already exists: {selected}; use --force to overwrite"
            )
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{selected.name}.", suffix=".tmp", dir=selected.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary, selected)
        else:
            try:
                os.link(temporary, selected)
            except FileExistsError as error:
                raise ConfigError(
                    f"output file already exists: {selected}; use --force to overwrite"
                ) from error
            temporary.unlink()
        os.chmod(selected, 0o600)
    except ConfigError:
        raise
    except OSError as error:
        raise ConfigError(
            f"unable to write audit report {selected}: {error}"
        ) from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    return selected


def _delegation_report(
    database: sqlite3.Connection,
    row: sqlite3.Row,
    events_by_job: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    identifier = row["delegation_id"]
    audit_rows = database.execute(
        """SELECT sequence,occurred_at,operation,decision,detail_json
           FROM delegation_audit WHERE delegation_id=? ORDER BY sequence""",
        (identifier,),
    ).fetchall()
    audit_events = [
        {
            "sequence": event["sequence"],
            "occurred_at": event["occurred_at"],
            "operation": event["operation"],
            "decision": event["decision"],
            "detail": _decode_json(event["detail_json"]),
        }
        for event in audit_rows
    ]
    artifacts_by_generation = {
        int(event["detail"]["generation"]): event["detail"]
        for event in audit_events
        if event["operation"] == "controller_artifacts"
        and isinstance(event["detail"], dict)
        and isinstance(event["detail"].get("generation"), int)
    }
    output_by_key = {
        str(event["detail"]["idempotency_key"]): event["detail"].get("output_directory")
        for event in audit_events
        if event["operation"] == "record_submission"
        and isinstance(event["detail"], dict)
        and isinstance(event["detail"].get("idempotency_key"), str)
    }
    controller_attempts = []
    for attempt in database.execute(
        """SELECT generation,parent_job_id,restart_count,state,
                  reconciliation_required,reason,started_at,updated_at
           FROM controller_attempts WHERE delegation_id=? ORDER BY generation""",
        (identifier,),
    ):
        artifacts = artifacts_by_generation.get(int(attempt["generation"]))
        controller_attempts.append(
            {
                "generation": attempt["generation"],
                "parent_job_id": attempt["parent_job_id"],
                "restart_count": attempt["restart_count"],
                "state": attempt["state"],
                "reconciliation_required": bool(attempt["reconciliation_required"]),
                "reason": attempt["reason"],
                "started_at": attempt["started_at"],
                "updated_at": attempt["updated_at"],
                "artifacts": _artifact_summary(artifacts),
            }
        )

    submission_operations = []
    for operation in database.execute(
        """SELECT idempotency_key,request_sha256,status,resource_json,job_id,
                  cluster,error,quoted_cost_value,quoted_cost_scale,
                  quoted_cost_unit,quote_evidence_token,quote_expires_at,
                  created_at,updated_at
           FROM submission_operations WHERE delegation_id=? ORDER BY created_at""",
        (identifier,),
    ):
        key = (
            row["profile"],
            operation["job_id"] or "",
            operation["cluster"] or "",
        )
        matched_events = events_by_job.get(key, [])
        output_directory = output_by_key.get(operation["idempotency_key"])
        if output_directory is None:
            output_directory = _event_output_directory(matched_events)
        submission_operations.append(
            {
                "idempotency_key": operation["idempotency_key"],
                "request_sha256": operation["request_sha256"],
                "status": operation["status"],
                "resources": _decode_json(operation["resource_json"]),
                "job_id": operation["job_id"],
                "cluster": operation["cluster"],
                "error": operation["error"],
                "quote": _operation_quote(operation),
                "created_at": operation["created_at"],
                "updated_at": operation["updated_at"],
                "output_directory": output_directory,
                "output": _output_summary(output_directory),
                "submission_events": matched_events,
            }
        )

    lifecycle_operations = [
        {
            "idempotency_key": operation["idempotency_key"],
            "operation": operation["operation"],
            "job_id": operation["job_id"],
            "cluster": operation["cluster"],
            "status": operation["status"],
            "result": _decode_json(operation["result_json"]),
            "created_at": operation["created_at"],
            "updated_at": operation["updated_at"],
        }
        for operation in database.execute(
            """SELECT idempotency_key,operation,job_id,cluster,status,result_json,
                      created_at,updated_at
               FROM lifecycle_operations WHERE delegation_id=? ORDER BY created_at""",
            (identifier,),
        )
    ]
    ownership = [
        dict(owned)
        for owned in database.execute(
            """SELECT job_id,cluster,idempotency_key,created_at
               FROM job_ownership WHERE delegation_id=? ORDER BY created_at""",
            (identifier,),
        )
    ]
    cleanup_row = database.execute(
        """SELECT job_id,status,last_error,updated_at
           FROM controller_cleanup WHERE delegation_id=?""",
        (identifier,),
    ).fetchone()
    cleanup = dict(cleanup_row) if cleanup_row else None
    manifest = _decode_json(row["manifest_json"])
    return {
        "delegation_id": identifier,
        "manifest_sha256": row["manifest_sha256"],
        "issuer": row["issuer"],
        "profile": row["profile"],
        "parent_job_id": row["parent_job_id"],
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "network_mode": row["network_mode"],
        "manifest": manifest,
        "revoked_at": row["revoked_at"],
        "revocation_reason": row["revocation_reason"],
        "controller_attempts": controller_attempts,
        "cleanup": cleanup,
        "submission_operations": submission_operations,
        "quoted_credit": _quoted_credit_summary(manifest, submission_operations),
        "job_ownership": ownership,
        "lifecycle_operations": lifecycle_operations,
        "audit_events": audit_events,
    }


def _operation_quote(operation: sqlite3.Row) -> dict[str, Any] | None:
    value = operation["quoted_cost_value"]
    if value is None:
        return None
    return {
        "quoted_maximum": {
            "value": value,
            "scale": operation["quoted_cost_scale"],
            "unit": operation["quoted_cost_unit"],
        },
        "evidence_token": operation["quote_evidence_token"],
        "expires_at": operation["quote_expires_at"],
    }


def _quoted_credit_summary(
    manifest: Any,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {"configured": False}
    budget = manifest.get("credit_budget")
    if not isinstance(budget, dict) or budget.get("configured") is False:
        return {"configured": False}
    unit = budget.get("unit")
    scale = budget.get("scale")
    maximum_total = budget.get("maximum_total")
    if (
        not isinstance(unit, str)
        or type(scale) is not int
        or type(maximum_total) is not int
    ):
        raise ConfigError("delegation manifest contains malformed credit_budget")
    consumed = sum(
        operation["quote"]["quoted_maximum"]["value"]
        for operation in operations
        if operation["quote"] is not None and operation["status"] != "failed"
    )
    released = sum(
        operation["quote"]["quoted_maximum"]["value"]
        for operation in operations
        if operation["quote"] is not None and operation["status"] == "failed"
    )

    def amount(value: int) -> dict[str, int | str]:
        return {"value": value, "scale": scale, "unit": unit}

    return {
        "configured": True,
        "consumed_quoted_maximum": amount(consumed),
        "released_quoted_maximum": amount(released),
        "remaining_quoted_maximum": amount(max(0, maximum_total - consumed)),
    }


def _format_credit(amount: dict[str, Any]) -> str:
    return f"{amount['value']}e-{amount['scale']} {amount['unit']}"


def _submission_events_by_job(
    events: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    submitted_by_run: dict[str, tuple[str, str, str]] = {}
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for event in events:
        run_id = event.get("run_id")
        if event.get("event") == "submitted" and isinstance(run_id, str):
            key = (
                str(event.get("profile") or ""),
                str(event.get("job_id") or ""),
                str(event.get("cluster") or ""),
            )
            submitted_by_run[run_id] = key
    for event in events:
        run_id = event.get("run_id")
        if not isinstance(run_id, str) or run_id not in submitted_by_run:
            continue
        grouped.setdefault(submitted_by_run[run_id], []).append(event)
    return grouped


def _event_output_directory(events: list[dict[str, Any]]) -> str | None:
    submitted = next(
        (event for event in events if event.get("event") == "submitted"), None
    )
    if submitted is None:
        return None
    overrides = submitted.get("slurm_overrides")
    if not isinstance(overrides, dict):
        return None
    for name in ("output", "error"):
        value = overrides.get(name)
        if isinstance(value, str) and value:
            return str(Path(value).parent)
    return None


def _artifact_summary(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    result = dict(detail)
    for name in ("provenance_path", "event_log", "diagnostic_log"):
        value = detail.get(name)
        result[f"{name}_file"] = _file_summary(value)
    return result


def _output_summary(directory: str | None) -> dict[str, Any] | None:
    if not directory:
        return None
    path = Path(directory)
    status_path = path / ".hpc-tools-status.json"
    status = _read_bounded_json(status_path, limit=64 * 1024)
    return {
        "directory": str(path),
        "exists": path.is_dir(),
        "incomplete": (path / ".hpc-tools-incomplete").exists(),
        "status": status,
    }


def _read_bounded_json(path: Path, *, limit: int) -> Any:
    """Read an untrusted small JSON file without following a leaf symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            contents = handle.read(limit + 1)
        if len(contents) > limit:
            return None
        return json.loads(contents.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"invalid": True}
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _file_summary(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    path = Path(value)
    try:
        info = path.lstat()
    except OSError:
        return {"path": value, "exists": False}
    return {
        "path": value,
        "exists": True,
        "regular": stat.S_ISREG(info.st_mode),
        "size": info.st_size,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
    }


def _read_submission_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        selected = _secure_readable_file(path, "submissions database")
        with _readonly_database(selected) as database:
            version = int(database.execute("PRAGMA user_version").fetchone()[0])
            if version != submissions.SCHEMA_VERSION:
                raise ConfigError(
                    f"unsupported submissions database schema version {version}; "
                    f"expected {submissions.SCHEMA_VERSION}"
                )
            rows = database.execute(
                "SELECT sequence,payload_json FROM submission_events ORDER BY sequence"
            ).fetchall()
        events = []
        for row in rows:
            event = json.loads(row["payload_json"])
            if not isinstance(event, dict):
                raise ConfigError(
                    f"submissions database event {row['sequence']} is not an object"
                )
            events.append(event)
        return events
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        raise ConfigError(
            f"unable to read submissions database {path}: {error}"
        ) from error


def _decode_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"invalid_json": value}


def _secure_readable_file(path: Path, label: str, *, private: bool = False) -> Path:
    selected = path.expanduser().absolute()
    try:
        info = selected.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"{label} does not exist: {selected}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"{label} must be a regular file: {selected}")
    if private and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ConfigError(f"{label} must be owned by this user with mode 0600")
    return selected


@contextmanager
def _readonly_database(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        database = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        raise ConfigError(f"unable to open database {path}: {error}") from error
    database.row_factory = sqlite3.Row
    try:
        database.execute("PRAGMA query_only=ON")
        yield database
    except sqlite3.Error as error:
        raise ConfigError(f"unable to read database {path}: {error}") from error
    finally:
        database.close()
