from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from hpc_tools.config import ConfigError, default_config_dir

MANIFEST_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
DELEGATION_ENV_VAR = "HPC_TOOLS_MCP_DELEGATION"
LEDGER_ENV_VAR = "HPC_TOOLS_MCP_LEDGER"
PARENT_JOB_ENV_VAR = "HPC_TOOLS_PARENT_JOB_ID"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class DelegationError(ConfigError):
    """Raised when delegation authorization or accounting fails."""


@dataclass(frozen=True)
class FilesystemPolicy:
    """Host-selected paths used to isolate an unattended agent and its jobs."""

    state_root: Path
    work_root: Path
    output_root: Path
    input_roots: tuple[Path, ...]
    apptainer_path: Path
    max_file_blocks: int | None = None
    max_open_files: int | None = None

    def public_summary(self) -> dict[str, Any]:
        # state_root and apptainer_path are deliberately host-private details.
        return {
            "configured": True,
            "work_root": str(self.work_root),
            "output_root": str(self.output_root),
            "input_roots": [str(path) for path in self.input_roots],
            "max_file_blocks": self.max_file_blocks,
            "max_open_files": self.max_open_files,
        }


@dataclass(frozen=True)
class DelegationManifest:
    identifier: str
    issuer: str
    profile: str
    parent_job_id: str
    issued_at: str
    expires_at: str
    allowed: dict[str, tuple[str, ...]]
    per_job_limits: dict[str, int]
    budget: dict[str, int]
    filesystem: FilesystemPolicy | None
    source_path: Path
    digest: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "configured": True,
            "identifier": self.identifier,
            "issuer": self.issuer,
            "profile": self.profile,
            "parent_job_id": self.parent_job_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "allowed": {key: list(value) for key, value in self.allowed.items()},
            "per_job_limits": self.per_job_limits,
            "budget": self.budget,
            "filesystem": (
                self.filesystem.public_summary()
                if self.filesystem is not None
                else {"configured": False}
            ),
        }


@dataclass(frozen=True)
class DelegationRuntime:
    manifest: DelegationManifest
    ledger_path: Path


_CURRENT: ContextVar[DelegationRuntime | None] = ContextVar("hpc_tools_delegation", default=None)


def default_ledger_path() -> Path:
    return default_config_dir() / "delegations.sqlite3"


def load_runtime(
    manifest_path: str | Path,
    *,
    profile: str,
    ledger_path: str | Path | None = None,
    parent_job_id: str | None = None,
) -> DelegationRuntime:
    manifest = load_manifest(
        Path(manifest_path),
        expected_profile=profile,
        expected_parent_job_id=parent_job_id,
    )
    selected = Path(
        ledger_path or os.environ.get(LEDGER_ENV_VAR) or default_ledger_path()
    ).expanduser()
    DelegationLedger(selected).register(manifest)
    return DelegationRuntime(manifest, selected)


@contextmanager
def delegation_scope(runtime: DelegationRuntime | None) -> Iterator[None]:
    token = _CURRENT.set(runtime)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_runtime() -> DelegationRuntime | None:
    return _CURRENT.get()


def load_manifest(
    path: Path,
    *,
    expected_profile: str,
    expected_parent_job_id: str | None = None,
    now: datetime | None = None,
) -> DelegationManifest:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DelegationError(f"delegation manifest is not a regular file: {path}")
    if os.name == "posix":
        stat = path.stat()
        if stat.st_uid != os.geteuid():
            raise DelegationError(f"delegation manifest is not owned by the server user: {path}")
        if stat.st_mode & 0o022:
            raise DelegationError(
                f"delegation manifest must not be group- or world-writable: {path}"
            )
    payload = path.read_bytes()
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise DelegationError(f"invalid delegation manifest {path}: {error}") from error
    if raw.get("format_version") != MANIFEST_VERSION:
        raise DelegationError(
            f"unsupported delegation manifest version {raw.get('format_version')!r}; "
            f"expected {MANIFEST_VERSION}"
        )
    identifier = _string(raw, "id")
    profile = _string(raw, "profile")
    parent = _string(raw, "parent_job_id")
    issued = _timestamp_field(raw, "issued_at")
    expires = _timestamp_field(raw, "expires_at")
    instant = now or datetime.now(timezone.utc)
    if profile != expected_profile:
        raise DelegationError("delegation profile does not match the selected profile")
    if expected_parent_job_id and parent != expected_parent_job_id:
        raise DelegationError("delegation parent job does not match the server context")
    if _parse_time(expires) <= instant:
        raise DelegationError(f"delegation {identifier!r} is expired")
    if _parse_time(issued) > instant:
        raise DelegationError(f"delegation {identifier!r} has a future issue time")

    allowed_table = _table(raw, "allowed")
    keys = (
        "accounts", "clusters", "partitions", "qos", "reservations",
        "containers", "script_sha256", "roots",
    )
    allowed = {key: _strings(allowed_table, key) for key in keys}
    if not allowed["accounts"] or not allowed["clusters"]:
        raise DelegationError("allowed accounts and clusters must not be empty")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in allowed["script_sha256"]):
        raise DelegationError("script_sha256 values must be lowercase SHA-256 hashes")
    for value in allowed["roots"]:
        root = Path(value)
        if not root.is_absolute() or ".." in root.parts:
            raise DelegationError("allowed roots must be absolute normalized paths")
    filesystem = _filesystem_policy(raw.get("filesystem"))
    if filesystem is not None:
        if not allowed["containers"]:
            raise DelegationError(
                "a filesystem policy requires at least one allowed container"
            )
        if not _under_roots(str(filesystem.work_root), allowed["roots"]):
            raise DelegationError(
                "filesystem.work_root must be authorized by allowed.roots"
            )

    return DelegationManifest(
        identifier=identifier,
        issuer=_string(raw, "issuer"),
        profile=profile,
        parent_job_id=parent,
        issued_at=issued,
        expires_at=expires,
        allowed=allowed,
        per_job_limits=_positive_ints(raw.get("per_job_limits", {}), "per_job_limits"),
        budget=_positive_ints(raw.get("budget", {}), "budget"),
        filesystem=filesystem,
        source_path=path,
        digest=hashlib.sha256(payload).hexdigest(),
    )


def authorize_shape(manifest: DelegationManifest, shape: dict[str, Any]) -> None:
    if shape.get("profile") != manifest.profile:
        raise DelegationError("submission profile is outside the delegation")
    overrides = shape.get("overrides")
    if not isinstance(overrides, dict):
        raise DelegationError("submission shape has no overrides")
    _allow("account", overrides.get("account"), manifest.allowed["accounts"], required=True)
    _allow("cluster", overrides.get("cluster"), manifest.allowed["clusters"], required=True)
    _allow("partition", overrides.get("partition"), manifest.allowed["partitions"])
    _allow("qos", overrides.get("qos"), manifest.allowed["qos"])
    _allow("reservation", overrides.get("reservation"), manifest.allowed["reservations"])
    roots = manifest.allowed["roots"]
    if roots and not _under_roots(shape.get("directory"), roots):
        raise DelegationError("submission directory is outside allowed roots")
    boundary = shape.get("boundary")
    if boundary is not None:
        if not isinstance(boundary, dict):
            raise DelegationError("submission boundary must be an object")
        _allow(
            "container",
            boundary.get("container"),
            manifest.allowed["containers"],
            required=True,
        )
        script_digest = boundary.get("script_sha256")
        if not isinstance(script_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", script_digest
        ):
            raise DelegationError("submission boundary has no valid script SHA-256")
        approved_scripts = manifest.allowed["script_sha256"]
        if approved_scripts and script_digest not in approved_scripts:
            raise DelegationError("script_sha256 is outside the delegation")
    resources = shape_resources(overrides)
    for key, limit in manifest.per_job_limits.items():
        if resources.get(key, 0) > limit:
            raise DelegationError(
                f"requested {key}={resources[key]} exceeds delegation limit {limit}"
            )


def shape_resources(overrides: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for source, target in (
        ("nodes", "nodes"), ("ntasks", "tasks"),
        ("cpus_per_task", "cpus_per_task"), ("gpus", "gpus"),
        ("gpus_per_node", "gpus_per_node"), ("gpus_per_task", "gpus_per_task"),
    ):
        value = overrides.get(source)
        if value is not None:
            if not isinstance(value, str) or not value.isdigit() or int(value) < 1:
                raise DelegationError(f"delegation requires numeric {source}")
            result[target] = int(value)
    if overrides.get("array") is not None:
        array_tasks, array_concurrency = _array_shape(overrides["array"])
        result["array_tasks"] = array_tasks
        result["array_concurrency"] = array_concurrency
    if overrides.get("time") is not None:
        result["wall_seconds"] = _time_seconds(overrides["time"])
    if overrides.get("mem") is not None:
        result["memory_mib"] = _memory_mib(overrides["mem"])
    if overrides.get("mem_per_cpu") is not None:
        result["memory_per_cpu_mib"] = _memory_mib(overrides["mem_per_cpu"])
    return result


def budget_resources(overrides: dict[str, Any]) -> dict[str, int]:
    """Return cumulative requested resources, including every array element."""
    per_element = shape_resources(overrides)
    multiplier = per_element.get("array_tasks", 1)
    cumulative = dict(per_element)
    cumulative["nodes"] = per_element.get("nodes", 1) * multiplier
    cumulative["tasks"] = per_element.get("tasks", 1) * multiplier
    for key in (
        "cpus_per_task", "gpus", "gpus_per_node", "gpus_per_task",
        "wall_seconds", "memory_mib", "memory_per_cpu_mib",
    ):
        if key in per_element:
            cumulative[key] = per_element[key] * multiplier
    return cumulative


class DelegationLedger:
    """Server-owned authorization, ownership, budget, and audit database."""

    def __init__(self, path: Path):
        self.path = path.expanduser()

    def register(self, manifest: DelegationManifest) -> None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT manifest_sha256,revoked_at FROM delegations WHERE delegation_id=?",
                (manifest.identifier,),
            ).fetchone()
            if row and row[0] != manifest.digest:
                raise DelegationError("delegation id is registered with different contents")
            if row and row[1]:
                raise DelegationError("delegation is revoked")
            if not row:
                db.execute(
                    """INSERT INTO delegations
                       (delegation_id,manifest_sha256,issuer,profile,parent_job_id,
                        issued_at,expires_at,manifest_json) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        manifest.identifier, manifest.digest, manifest.issuer,
                        manifest.profile, manifest.parent_job_id, manifest.issued_at,
                        manifest.expires_at, json.dumps(manifest.public_summary(), sort_keys=True),
                    ),
                )
                self._audit(db, manifest.identifier, "register", "accepted", {})

    def reserve_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        shape: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._reserve_submission(
                manifest,
                idempotency_key=idempotency_key,
                shape=shape,
            )
        except DelegationError as error:
            self.record_rejection(
                manifest,
                operation="reserve_submission",
                detail={"idempotency_key": idempotency_key, "reason": str(error)},
            )
            raise

    def _reserve_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        shape: dict[str, Any],
    ) -> dict[str, Any]:
        validate_idempotency_key(idempotency_key)
        authorize_shape(manifest, shape)
        request_hash = hashlib.sha256(
            json.dumps(shape, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        requested = budget_resources(shape["overrides"])
        with self._transaction() as db:
            self._active(db, manifest)
            row = db.execute(
                """SELECT request_sha256,status,job_id,cluster FROM submission_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if row:
                if row[0] != request_hash:
                    raise DelegationError("idempotency key was used for a different request")
                self._audit(
                    db,
                    manifest.identifier,
                    "reserve_submission",
                    "accepted",
                    {"idempotency_key": idempotency_key, "idempotent_replay": True},
                )
                return {
                    "idempotent_replay": True,
                    "status": row[1],
                    "job_id": row[2],
                    "cluster": row[3],
                }
            used, active, totals = self._usage(db, manifest.identifier)
            self._check_budget(manifest, used, active, totals, requested)
            now = _now()
            db.execute(
                """INSERT INTO submission_operations
                   (delegation_id,idempotency_key,request_sha256,status,
                    resource_json,created_at,updated_at)
                   VALUES (?,?,?,'reserved',?,?,?)""",
                (
                    manifest.identifier, idempotency_key, request_hash,
                    json.dumps(requested, sort_keys=True), now, now,
                ),
            )
            self._audit(
                db, manifest.identifier, "reserve_submission", "accepted",
                {"idempotency_key": idempotency_key, "resources": requested},
            )
            return {
                "idempotent_replay": False,
                "status": "reserved",
                "job_id": None,
                "cluster": None,
            }

    def record_submission(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        job_id: str,
        cluster: str | None,
    ) -> None:
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            self._active(db, manifest)
            row = db.execute(
                """SELECT status,job_id FROM submission_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if not row:
                raise DelegationError("submission has no ledger reservation")
            if row[0] == "submitted" and row[1] == job_id:
                return
            if row[0] != "reserved":
                raise DelegationError(f"cannot submit operation in state {row[0]!r}")
            db.execute(
                """UPDATE submission_operations
                   SET status='submitted',job_id=?,cluster=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=?""",
                (job_id, cluster, _now(), manifest.identifier, idempotency_key),
            )
            db.execute(
                """INSERT INTO job_ownership
                   (delegation_id,job_id,cluster,idempotency_key,created_at)
                   VALUES (?,?,?,?,?)""",
                (manifest.identifier, job_id, cluster or "", idempotency_key, _now()),
            )
            self._audit(
                db, manifest.identifier, "record_submission", "accepted",
                {"idempotency_key": idempotency_key, "job_id": job_id, "cluster": cluster},
            )

    def release_reservation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        reason: str,
        uncertain: bool = False,
    ) -> None:
        status = "uncertain" if uncertain else "failed"
        with self._transaction() as db:
            db.execute(
                """UPDATE submission_operations SET status=?,error=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=? AND status='reserved'""",
                (status, reason, _now(), manifest.identifier, idempotency_key),
            )
            self._audit(
                db, manifest.identifier, "submission_result", status,
                {"idempotency_key": idempotency_key, "reason": reason},
            )

    def record_rejection(
        self,
        manifest: DelegationManifest,
        *,
        operation: str,
        detail: dict[str, Any],
    ) -> None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT manifest_sha256 FROM delegations WHERE delegation_id=?",
                (manifest.identifier,),
            ).fetchone()
            if not row or row[0] != manifest.digest:
                raise DelegationError("delegation is not registered with this ledger")
            self._audit(db, manifest.identifier, operation, "rejected", detail)

    def reconcile_job(
        self,
        manifest: DelegationManifest,
        *,
        job_id: str,
        cluster: str | None,
        state: str,
    ) -> None:
        terminal = {
            "BOOT_FAIL", "CANCELLED", "COMPLETED", "DEADLINE", "FAILED",
            "NODE_FAIL", "OUT_OF_MEMORY", "PREEMPTED", "REVOKED", "TIMEOUT",
        }
        normalized = state.split("+", 1)[0].upper()
        if normalized not in terminal:
            return
        job_id = normalize_job_id(job_id)
        with self._transaction() as db:
            row = db.execute(
                """SELECT idempotency_key FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, job_id, cluster or ""),
            ).fetchone()
            if not row:
                raise DelegationError("cannot reconcile a job outside the delegation")
            db.execute(
                """UPDATE submission_operations SET status='terminal',updated_at=?
                   WHERE delegation_id=? AND idempotency_key=? AND status='submitted'""",
                (_now(), manifest.identifier, row[0]),
            )
            self._audit(
                db, manifest.identifier, "reconcile_job", "accepted",
                {"job_id": job_id, "cluster": cluster, "state": normalized},
            )

    def owned_jobs(
        self,
        manifest: DelegationManifest,
        *,
        include_terminal: bool = False,
    ) -> list[dict[str, str]]:
        with self._connection() as db:
            self._active(db, manifest)
            terminal_filter = "" if include_terminal else "AND operations.status != 'terminal'"
            rows = db.execute(
                f"""SELECT ownership.job_id,ownership.cluster,operations.status
                    FROM job_ownership AS ownership
                    JOIN submission_operations AS operations
                      ON operations.delegation_id=ownership.delegation_id
                     AND operations.idempotency_key=ownership.idempotency_key
                    WHERE ownership.delegation_id=? {terminal_filter}
                    ORDER BY ownership.created_at,ownership.job_id""",
                (manifest.identifier,),
            ).fetchall()
        return [
            {"job_id": row[0], "cluster": row[1], "status": row[2]}
            for row in rows
        ]

    def require_ownership(
        self,
        manifest: DelegationManifest,
        *,
        job_id: str,
        cluster: str | None,
    ) -> str:
        base_job_id = normalize_job_id(job_id)
        with self._connection() as db:
            self._active(db, manifest)
            row = db.execute(
                """SELECT 1 FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (manifest.identifier, base_job_id, cluster or ""),
            ).fetchone()
        if not row:
            self.record_rejection(
                manifest,
                operation="job_ownership",
                detail={"job_id": job_id, "cluster": cluster},
            )
            raise DelegationError(
                f"job {job_id!r} on cluster {cluster!r} is outside the delegation"
            )
        return base_job_id

    def reserve_lifecycle_operation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        operation: str,
        job_id: str,
        cluster: str | None,
    ) -> dict[str, Any]:
        try:
            return self._reserve_lifecycle_operation(
                manifest,
                idempotency_key=idempotency_key,
                operation=operation,
                job_id=job_id,
                cluster=cluster,
            )
        except DelegationError as error:
            self.record_rejection(
                manifest,
                operation=operation,
                detail={
                    "idempotency_key": idempotency_key,
                    "job_id": job_id,
                    "cluster": cluster,
                    "reason": str(error),
                },
            )
            raise

    def _reserve_lifecycle_operation(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        operation: str,
        job_id: str,
        cluster: str | None,
    ) -> dict[str, Any]:
        if operation != "cancel":
            raise DelegationError(f"unsupported lifecycle mutation {operation!r}")
        validate_idempotency_key(idempotency_key)
        base_job_id = self.require_ownership(
            manifest, job_id=job_id, cluster=cluster
        )
        with self._transaction() as db:
            row = db.execute(
                """SELECT operation,job_id,cluster,status,result_json
                   FROM lifecycle_operations
                   WHERE delegation_id=? AND idempotency_key=?""",
                (manifest.identifier, idempotency_key),
            ).fetchone()
            if row:
                if (row[0], row[1], row[2]) != (
                    operation, base_job_id, cluster or ""
                ):
                    raise DelegationError(
                        "lifecycle idempotency key was used for a different operation"
                    )
                self._audit(
                    db, manifest.identifier, operation, "accepted",
                    {"idempotency_key": idempotency_key, "idempotent_replay": True},
                )
                return {
                    "idempotent_replay": True,
                    "status": row[3],
                    "result": json.loads(row[4]) if row[4] else None,
                }
            db.execute(
                """INSERT INTO lifecycle_operations
                   (delegation_id,idempotency_key,operation,job_id,cluster,status,
                    created_at,updated_at)
                   VALUES (?,?,?,?,?,'reserved',?,?)""",
                (
                    manifest.identifier, idempotency_key, operation,
                    base_job_id, cluster or "", _now(), _now(),
                ),
            )
            self._audit(
                db, manifest.identifier, operation, "accepted",
                {
                    "idempotency_key": idempotency_key,
                    "job_id": job_id,
                    "cluster": cluster,
                },
            )
            return {"idempotent_replay": False, "status": "reserved", "result": None}

    def record_lifecycle_result(
        self,
        manifest: DelegationManifest,
        *,
        idempotency_key: str,
        succeeded: bool,
        result: dict[str, Any],
    ) -> None:
        status = "succeeded" if succeeded else "failed"
        with self._transaction() as db:
            changed = db.execute(
                """UPDATE lifecycle_operations
                   SET status=?,result_json=?,updated_at=?
                   WHERE delegation_id=? AND idempotency_key=? AND status='reserved'""",
                (
                    status,
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    _now(),
                    manifest.identifier,
                    idempotency_key,
                ),
            ).rowcount
            if changed != 1:
                raise DelegationError("lifecycle operation has no active reservation")
            self._audit(
                db, manifest.identifier, "lifecycle_result", status,
                {"idempotency_key": idempotency_key, "result": result},
            )

    def owns_job(self, delegation_id: str, job_id: str, cluster: str | None) -> bool:
        base_job_id = normalize_job_id(job_id)
        with self._connection() as db:
            return db.execute(
                """SELECT 1 FROM job_ownership
                   WHERE delegation_id=? AND job_id=? AND cluster=?""",
                (delegation_id, base_job_id, cluster or ""),
            ).fetchone() is not None

    def summary(self, manifest: DelegationManifest) -> dict[str, Any]:
        with self._connection() as db:
            self._active(db, manifest)
            used, active, totals = self._usage(db, manifest.identifier)
        remaining = {}
        for key, limit in manifest.budget.items():
            consumed = (
                used if key == "max_submissions"
                else active if key == "max_active_jobs"
                else totals.get(key.removeprefix("max_total_"), 0)
            )
            remaining[key] = max(0, limit - consumed)
        return {
            "used_submissions": used,
            "active_jobs": active,
            "requested_resources": totals,
            "remaining": remaining,
        }

    def revoke(self, delegation_id: str, *, reason: str) -> None:
        with self._transaction() as db:
            count = db.execute(
                """UPDATE delegations SET revoked_at=?,revocation_reason=?
                   WHERE delegation_id=? AND revoked_at IS NULL""",
                (_now(), reason, delegation_id),
            ).rowcount
            if count != 1:
                raise DelegationError("unknown or already revoked delegation")
            self._audit(db, delegation_id, "revoke", "accepted", {"reason": reason})

    def _check_budget(
        self,
        manifest: DelegationManifest,
        used: int,
        active: int,
        totals: dict[str, int],
        requested: dict[str, int],
    ) -> None:
        if used >= manifest.budget.get("max_submissions", 2**63 - 1):
            raise DelegationError("delegation submission budget is exhausted")
        if active >= manifest.budget.get("max_active_jobs", 2**63 - 1):
            raise DelegationError("delegation active-job budget is exhausted")
        for key, limit in manifest.budget.items():
            if key.startswith("max_total_"):
                resource = key.removeprefix("max_total_")
                if totals.get(resource, 0) + requested.get(resource, 0) > limit:
                    raise DelegationError(f"delegation aggregate {resource} budget is exhausted")

    def _usage(
        self, db: sqlite3.Connection, delegation_id: str
    ) -> tuple[int, int, dict[str, int]]:
        rows = db.execute(
            """SELECT status,resource_json FROM submission_operations
               WHERE delegation_id=? AND status != 'failed'""",
            (delegation_id,),
        ).fetchall()
        totals: dict[str, int] = {}
        for _, encoded in rows:
            for key, value in json.loads(encoded).items():
                totals[key] = totals.get(key, 0) + int(value)
        used = len(rows)
        active = sum(status in {"reserved", "submitted", "uncertain"} for status, _ in rows)
        return used, active, totals

    def _active(self, db: sqlite3.Connection, manifest: DelegationManifest) -> None:
        row = db.execute(
            """SELECT manifest_sha256,expires_at,revoked_at FROM delegations
               WHERE delegation_id=?""",
            (manifest.identifier,),
        ).fetchone()
        if not row or row[0] != manifest.digest:
            raise DelegationError("delegation is not registered with this ledger")
        if row[2]:
            raise DelegationError("delegation is revoked")
        if _parse_time(row[1]) <= datetime.now(timezone.utc):
            raise DelegationError("delegation is expired")

    def _audit(
        self,
        db: sqlite3.Connection,
        delegation_id: str,
        operation: str,
        decision: str,
        detail: dict[str, Any],
    ) -> None:
        db.execute(
            """INSERT INTO delegation_audit
               (delegation_id,occurred_at,operation,decision,detail_json)
               VALUES (?,?,?,?,?)""",
            (
                delegation_id, _now(), operation, decision,
                json.dumps(detail, sort_keys=True, separators=(",", ":")),
            ),
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        if not existed:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                existed = True
            else:
                os.close(descriptor)
        if self.path.is_symlink() or not self.path.is_file():
            raise DelegationError(
                f"delegation ledger must be a regular non-symlink file: {self.path}"
            )
        if os.name == "posix":
            stat = self.path.stat()
            if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                raise DelegationError(
                    f"delegation ledger must be server-owned with mode 0600: {self.path}"
                )
        db = sqlite3.connect(self.path, timeout=5.0)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            self._ensure_schema(db)
            yield db
        except sqlite3.Error as error:
            raise DelegationError(f"unable to use delegation ledger {self.path}: {error}") from error
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except Exception:
                db.rollback()
                raise
            else:
                db.commit()

    def _ensure_schema(self, db: sqlite3.Connection) -> None:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        schema_lock = version == 0
        if schema_lock:
            db.execute("BEGIN IMMEDIATE")
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            _execute_schema(db,
                """
                CREATE TABLE delegations (
                    delegation_id TEXT PRIMARY KEY,
                    manifest_sha256 TEXT NOT NULL, issuer TEXT NOT NULL,
                    profile TEXT NOT NULL, parent_job_id TEXT NOT NULL,
                    issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    manifest_json TEXT NOT NULL, revoked_at TEXT,
                    revocation_reason TEXT
                );
                CREATE TABLE submission_operations (
                    delegation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                    resource_json TEXT NOT NULL, job_id TEXT, cluster TEXT,
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,idempotency_key),
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE TABLE job_ownership (
                    delegation_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    cluster TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,job_id,cluster),
                    FOREIGN KEY (delegation_id,idempotency_key)
                      REFERENCES submission_operations(delegation_id,idempotency_key)
                );
                CREATE TABLE lifecycle_operations (
                    delegation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    operation TEXT NOT NULL, job_id TEXT NOT NULL,
                    cluster TEXT NOT NULL, status TEXT NOT NULL,
                    result_json TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (delegation_id,idempotency_key),
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE TABLE delegation_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    delegation_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    operation TEXT NOT NULL, decision TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    FOREIGN KEY (delegation_id) REFERENCES delegations(delegation_id)
                );
                CREATE INDEX delegation_audit_by_delegation
                  ON delegation_audit(delegation_id,sequence);
                """
            )
            db.execute(f"PRAGMA user_version={LEDGER_SCHEMA_VERSION}")
            version = LEDGER_SCHEMA_VERSION
        if schema_lock:
            db.commit()
        if version != LEDGER_SCHEMA_VERSION:
            raise DelegationError(
                f"unsupported delegation ledger schema version {version}; "
                f"expected {LEDGER_SCHEMA_VERSION}"
            )




_JOB_ID_PATTERN = re.compile(
    r"(?P<base>\d+)(?:\+\d+)?(?:_\d+)?(?:\.[A-Za-z0-9_-]+)?"
)


def normalize_job_id(job_id: str) -> str:
    match = _JOB_ID_PATTERN.fullmatch(job_id)
    if not match:
        raise DelegationError(
            "job ID must identify one numeric job, heterogeneous component, "
            "array task, or job step"
        )
    return match.group("base")


def validate_idempotency_key(value: str) -> None:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise DelegationError("invalid idempotency key")

def _execute_schema(db: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            db.execute(statement)

def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise DelegationError(f"delegation field {key!r} must be a non-empty string")
    return value


def _timestamp_field(data: dict[str, Any], key: str) -> str:
    value = _string(data, key)
    _parse_time(value)
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DelegationError(f"invalid delegation timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise DelegationError("delegation timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise DelegationError(f"delegation field {key!r} must be a table")
    return value


def _strings(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DelegationError(f"allowed.{key} must be an array of strings")
    if len(set(value)) != len(value):
        raise DelegationError(f"allowed.{key} contains duplicates")
    return tuple(value)


def _positive_ints(value: Any, name: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise DelegationError(f"{name} must be a table")
    for key, item in value.items():
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise DelegationError(f"{name}.{key} must be a positive integer")
    return dict(value)


def _filesystem_policy(value: Any) -> FilesystemPolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DelegationError("filesystem must be a table")
    known = {
        "state_root", "work_root", "output_root", "input_roots",
        "apptainer_path", "max_file_blocks", "max_open_files",
    }
    unknown = sorted(set(value) - known)
    if unknown:
        raise DelegationError(
            f"unsupported filesystem field(s): {', '.join(unknown)}"
        )

    def absolute_path(name: str) -> Path:
        raw = value.get(name)
        if not isinstance(raw, str) or not raw:
            raise DelegationError(f"filesystem.{name} must be a non-empty string")
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise DelegationError(
                f"filesystem.{name} must be an absolute normalized path"
            )
        return path

    raw_inputs = value.get("input_roots", [])
    if not isinstance(raw_inputs, list) or not all(
        isinstance(item, str) and item for item in raw_inputs
    ):
        raise DelegationError("filesystem.input_roots must be an array of strings")
    input_roots: list[Path] = []
    for item in raw_inputs:
        path = Path(item)
        if not path.is_absolute() or ".." in path.parts:
            raise DelegationError(
                "filesystem.input_roots must contain absolute normalized paths"
            )
        input_roots.append(path)
    if len(set(input_roots)) != len(input_roots):
        raise DelegationError("filesystem.input_roots contains duplicates")

    limits = _positive_ints(
        {
            key: item
            for key, item in value.items()
            if key in {"max_file_blocks", "max_open_files"}
        },
        "filesystem",
    )
    policy = FilesystemPolicy(
        state_root=absolute_path("state_root"),
        work_root=absolute_path("work_root"),
        output_root=absolute_path("output_root"),
        input_roots=tuple(input_roots),
        apptainer_path=absolute_path("apptainer_path"),
        max_file_blocks=limits.get("max_file_blocks"),
        max_open_files=limits.get("max_open_files"),
    )
    roots = (policy.state_root, policy.work_root, policy.output_root, *policy.input_roots)
    for index, first in enumerate(roots):
        for second in roots[index + 1 :]:
            if _paths_overlap(first, second):
                raise DelegationError(
                    f"filesystem paths must not overlap: {first} and {second}"
                )
    for root in roots:
        if _paths_overlap(policy.apptainer_path, root):
            raise DelegationError(
                "filesystem.apptainer_path must be outside all container bind roots"
            )
    return policy


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _allow(
    name: str, value: Any, allowed: tuple[str, ...], *, required: bool = False
) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or value not in allowed:
        raise DelegationError(f"submission {name} {value!r} is outside the delegation")


def _under_roots(value: Any, roots: tuple[str, ...]) -> bool:
    if not isinstance(value, str) or "$" in value or "~" in value:
        return False
    path = Path(value)
    return path.is_absolute() and ".." not in path.parts and any(
        path == Path(root) or Path(root) in path.parents for root in roots
    )


def _array_shape(value: Any) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:-\d+)?(?:%\d+)?", value):
        raise DelegationError("only one numeric Slurm array range is supported")
    range_value, _, concurrency_value = value.partition("%")
    bounds = range_value.split("-", 1)
    if len(bounds) == 1:
        size = 1
    else:
        start, end = map(int, bounds)
        if end < start:
            raise DelegationError("Slurm array range is reversed")
        size = end - start + 1
    concurrency = int(concurrency_value) if concurrency_value else size
    if concurrency < 1:
        raise DelegationError("Slurm array concurrency must be positive")
    return size, min(size, concurrency)

def _time_seconds(value: Any) -> int:
    if not isinstance(value, str):
        raise DelegationError("time limit must be a string")
    match = re.fullmatch(r"(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})", value)
    if not match:
        raise DelegationError("time must use [days-]HH:MM:SS")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if minutes > 59 or seconds > 59:
        raise DelegationError("time has invalid minutes or seconds")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds



def _memory_mib(value: Any) -> int:
    if not isinstance(value, str):
        raise DelegationError("memory limit must be a string")
    match = re.fullmatch(r"(\d+)([KMGTP]?)", value, re.IGNORECASE)
    if not match or int(match.group(1)) < 1:
        raise DelegationError("memory must be a positive Slurm size using K, M, G, T, or P")
    amount = int(match.group(1))
    unit = match.group(2).upper() or "M"
    factors = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}
    return max(1, int(amount * factors[unit]))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
